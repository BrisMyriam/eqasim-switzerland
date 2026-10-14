"""Replace the TPG network of a merged GTFS by a theoretical TPG feed running on one chosen day.

Standalone tool (not a pipeline stage). Example, as used to build the 2026 CMDP feed:

    uv run data/gtfs/tools/replace_tpg_gtfs.py \
        D:/MATSim/CMDP_input-data/gtfs/merged_gtfs.zip \
        D:/Travaux/GTFS/gtfs_tpg_theorique_jour_ouvre.zip \
        20260611 \
        D:/MATSim/CMDP_input-data/gtfs/gtfs_cmdp2026_tpgtheo_20260611.zip

then set in the config: gtfs_name: <output name without .zip> and gtfs_date: "<yyyymmdd>".
The day must be covered by every source of the merged feed (for merged_gtfs.zip,
the French feeds end on 2026-07-05 / 2026-08-31).

- removes agency 881 (TPG) from the merged feed: routes, trips, stop_times, and the
  calendar entries that only TPG trips used;
- adds the theoretical feed with prefixed ids and route types 3/0 converted to 700/900
  like the national feed. Its stops (SLOID ids) take the id of the national stop at the
  same place (<= 5 m), or of a national stop with the same name nearby (<= 150 m), so that
  transfers with trains happen at the same stop; the others keep their own id;
- the theoretical feed runs on the chosen day only.
"""
import io, sys, zipfile
import numpy as np, pandas as pd
from scipy.spatial import cKDTree

merged_path, tpg_path, day, out_path = sys.argv[1:5]
TPG, PREFIX, MATCH_M, NAME_MATCH_M = "881", "TPGT_", 5.0, 150.0
SERVICE = PREFIX + "JOUR_OUVRE"


def read(path):
    z = zipfile.ZipFile(path)
    feed = {}
    for n in z.namelist():
        if n.endswith(".txt"):
            feed[n.split("/")[-1][:-4]] = pd.read_csv(io.BytesIO(z.read(n)), dtype=str, keep_default_na=False)
    return feed


M = read(merged_path)
N = read(tpg_path)
print("merged:", {k: len(v) for k, v in M.items()})
print("tpg:", {k: len(v) for k, v in N.items()})

# ---- 1. remove TPG from the merged feed ------------------------------------
tpg_routes = set(M["routes"].route_id[M["routes"].agency_id == TPG])
tpg_trips = set(M["trips"].trip_id[M["trips"].route_id.isin(tpg_routes)])
M["routes"] = M["routes"][~M["routes"].route_id.isin(tpg_routes)]
M["trips"] = M["trips"][~M["trips"].trip_id.isin(tpg_trips)]
M["stop_times"] = M["stop_times"][~M["stop_times"].trip_id.isin(tpg_trips)]
used_services = set(M["trips"].service_id)
for slot in ("calendar", "calendar_dates"):
    M[slot] = M[slot][M[slot].service_id.isin(used_services)]
M["agency"] = M["agency"][M["agency"].agency_id != TPG]
print(f"removed TPG: {len(tpg_routes)} routes, {len(tpg_trips)} trips")

# ---- 2. match the new stops to national stops -------------------------------
ns, ms = N["stops"], M["stops"]
lt = lambda s: s.get("location_type", pd.Series("", index=s.index)).replace("", "0")
used = set(N["stop_times"].stop_id)
new_q = ns[(lt(ns) != "1") & ns.stop_id.isin(used)]
nat_q = ms[lt(ms) != "1"]
def xy(df):
    lat, lon = df.stop_lat.astype(float).values, df.stop_lon.astype(float).values
    return np.c_[lon * 111_320 * np.cos(np.radians(46.2)), lat * 110_574]
dist, idx = cKDTree(xy(nat_q)).query(xy(new_q), k=20)
match = {}
n_same_place = n_same_name = 0
for sid, name, ds, ix in zip(new_q.stop_id, new_q.stop_name, dist, idx):
    if ds[0] <= MATCH_M:  # same place
        match[sid] = nat_q.stop_id.values[ix[0]]; n_same_place += 1
        continue
    for d_, i_ in zip(ds, ix):  # same name, close by: a moved or added quay of the same stop
        if d_ > NAME_MATCH_M:
            break
        if nat_q.stop_name.values[i_] == name:
            match[sid] = nat_q.stop_id.values[i_]; n_same_name += 1
            break
print(f"stops used by TPG: {len(new_q)} | same place (<= {MATCH_M:.0f} m): {n_same_place} | "
      f"same name (<= {NAME_MATCH_M:.0f} m): {n_same_name} | kept as new: {len(new_q) - len(match)}")

keep_new = new_q[~new_q.stop_id.isin(match)].copy()
parents = set(keep_new.get("parent_station", pd.Series(dtype=str))) - {""}
keep_new = pd.concat([keep_new, ns[ns.stop_id.isin(parents)]])
assert not set(keep_new.stop_id) & set(ms.stop_id), "stop id collision"

# ---- 3. prepare the TPG feed ------------------------------------------------
remap_stop = lambda s: s.map(lambda x: match.get(x, x))
p = lambda s: PREFIX + s

routes = N["routes"].copy()
routes["route_id"] = p(routes.route_id)
routes["route_type"] = routes.route_type.replace({"3": "700", "0": "900"})
trips = N["trips"].copy()
trips["route_id"] = p(trips.route_id); trips["trip_id"] = p(trips.trip_id); trips["service_id"] = SERVICE
if "shape_id" in trips:
    trips["shape_id"] = trips.shape_id.map(lambda x: p(x) if x else x)
st = N["stop_times"].copy()
st["trip_id"] = p(st.trip_id); st["stop_id"] = remap_stop(st.stop_id)

d = pd.Timestamp(day)
cal = {c: "0" for c in M["calendar"].columns}
cal.update({"service_id": SERVICE, "start_date": day, "end_date": day,
            ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][d.dayofweek]: "1"})

add = {"agency": N["agency"], "stops": keep_new, "routes": routes, "trips": trips, "stop_times": st,
       "calendar": pd.DataFrame([cal])}
if "shapes" in N:
    sh = N["shapes"].copy(); sh["shape_id"] = p(sh.shape_id); add["shapes"] = sh
if "transfers" in N:
    tr = N["transfers"].copy()
    for c in ("from_stop_id", "to_stop_id"):
        if c in tr: tr[c] = remap_stop(tr[c])
    for c in ("from_route_id", "to_route_id", "from_trip_id", "to_trip_id"):
        if c in tr: tr[c] = tr[c].map(lambda x: p(x) if x else x)
    add["transfers"] = tr
if "feed_info" in N:
    add["feed_info"] = N["feed_info"]

out = dict(M)
for slot, df in add.items():
    out[slot] = pd.concat([out[slot], df], ignore_index=True).fillna("") if slot in out else df

# ---- 4. checks ---------------------------------------------------------------
stop_ids = set(out["stops"].stop_id)
assert out["stops"].stop_id.is_unique, "duplicate stop ids"
assert out["trips"].trip_id.is_unique and out["routes"].route_id.is_unique, "duplicate trip/route ids"
assert set(out["stop_times"].stop_id) <= stop_ids, "stop_times reference unknown stops"
assert set(out["trips"].route_id) <= set(out["routes"].route_id), "trips reference unknown routes"
assert set(out["routes"].agency_id) <= set(out["agency"].agency_id), "routes reference unknown agencies"
services = set(out["calendar"].service_id) | set(out.get("calendar_dates", pd.DataFrame(columns=["service_id"])).service_id)
assert set(out["trips"].service_id) <= services, "trips reference unknown services"
print("checks passed")

with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for slot, df in out.items():
        z.writestr(slot + ".txt", df.to_csv(index=False, lineterminator="\n"))
print("written:", out_path, {k: len(v) for k, v in out.items()})
