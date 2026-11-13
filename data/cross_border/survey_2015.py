"""AuGQPV 2015 in the format of the 2021 survey (retrofit 2015-16).

Config cross_border_survey_year: 2021 (default, current model) or 2015. With 2015, the
individual observations come from the 2015 survey instead of the 2021 one, and the
same processing as for 2021 applies (read_2021_data in generate_od / swiss_residents_od).
The 2015 survey stays the volume reference, so the calibration becomes an identity.

Differences of the 2015 file, handled here:
- one weight GEWICHT (vehicles for road, persons for rail, as already assumed by
  read_2015_data), copied to GEWICHT_Personen and GEWICHT_Fahrzeuge;
- no GISCO ids: built from the BFS number (CH_CH0261) or the NUTS code (DE_DE132),
  which survey_locations.recover_locations understands;
- ZUGTYP FV / RV instead of 1 / 2; FAHRZEUGTYP 3 = motorcycle (2 in 2021),
  4 = coach (dropped, as in read_2015_data: the 2021 survey has none);
- interview place names differ from the reference places (built on the 2021 names),
  and rail ids are shifted in 2021, so names are matched: road by group letter or
  name, rail by station name.
"""

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

logger = logging.getLogger("synpp")

DEFAULT_YEAR = 2021
SURVEY_2015 = "crossborder/AuGQPV_2015/Finale_Auswertungsdatenbank_AGQPV2015_V2.csv"
CODEBOOK_2015 = "crossborder/AuGQPV_2015/Beschreibung_Finale_Auswertungsdatenbank_AGQPV2015_V2.xls"


def configure_year(context):
    context.config("cross_border_survey_year", DEFAULT_YEAR)
    year = int(context.config("cross_border_survey_year"))
    if year not in (2015, 2021):
        raise ValueError("cross_border_survey_year must be 2015 or 2021, got %s" % year)
    return year


def survey_year(context):
    return int(context.config("cross_border_survey_year"))


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", value)


def _base(value):
    return _normalize(re.sub(r"\s*\(\d+\)\s*$", "", str(value)))


def canonical_place_names(names, carriers, known):
    """Map 2015 interview place names to the reference names (known, with their labels)."""
    known = set(known)  # several points per place in the reference file
    road = sorted({k for k, label in known if label == "road"})
    rail = sorted({k for k, label in known if label != "road"})
    mapping = {}
    for name, carrier in set(zip(names, carriers)):
        group = re.match(r"\s*Gruppe\s+([A-Z])\s*:", str(name))
        if carrier == 1 and group:
            matches = [k for k in road if re.match(r"\s*Gruppe\s+%s\s*:" % group.group(1), str(k))]
        elif carrier == 1:
            matches = [k for k in road if _base(k) == _base(name)]
        else:
            matches = [k for k in rail if _normalize(k) == _normalize(name)]
        if len(matches) == 1:
            mapping[(name, carrier)] = matches[0]
        else:
            logger.warning("AuGQPV 2015: interview place %s (carrier %s) matches %d reference places, left as is",
                           name, carrier, len(matches))
    return [mapping.get((name, carrier), name) for name, carrier in zip(names, carriers)]


def _gisco_id(iso, bfs, nuts):
    iso = str(iso).strip()
    bfs = pd.to_numeric(bfs, errors="coerce")
    nuts = str(nuts).strip()
    if iso == "CH" and pd.notna(bfs):
        return "CH_CH%04d" % int(bfs)
    if iso and nuts and nuts.lower() != "nan":
        return "%s_%s" % (iso, nuts)
    return ""


def load_2015_in_2021_format(context, known_places):
    """The 2015 survey with the 2021 column names and codes (see the module docstring)."""
    path = "%s/%s" % (context.config("data_path"), SURVEY_2015)
    df = pd.read_csv(path, encoding="latin1", sep=",", low_memory=False)

    vehicle = df["FAHRZEUGTYP"].astype(str).str.strip()
    df = df[vehicle != "4"].copy()
    df["FAHRZEUGTYP"] = df["FAHRZEUGTYP"].astype(str).str.strip().replace({"3": "2"})
    df["ZUGTYP"] = df["ZUGTYP"].astype(str).str.strip().replace({"FV": "1", "RV": "2"})

    df["GEWICHT_Personen"] = df["GEWICHT"]
    df["GEWICHT_Fahrzeuge"] = df["GEWICHT"]

    for prefix, nuts, bfs in [("WOHNORT", "WOHNORTORTGEONAMESID_NUTS", "WOHNORTORTGEONAMESID_BFSNUMMER"),
                              ("STARTORT", "STARTORTORTGEONAMESID_NUTS", "STARTORTORTGEONAMESID_BFSNUMMER"),
                              ("ZIELORT", "ZIELORTGEONAMESID_NUTS", "ZIELORTGEONAMESID_BFSNUMMER")]:
        df[prefix + "_GISCO_ID"] = [_gisco_id(i, b, n) for i, b, n in zip(df[prefix + "LANDISO"], df[bfs], df[nuts])]

    df["BEFRAGUNGSORT"] = canonical_place_names(df["BEFRAGUNGSORT"].tolist(),
                                                pd.to_numeric(df["VERKEHRSTRAEGER"]).tolist(), known_places)
    logger.info("AuGQPV 2015 loaded in 2021 format: %d observations (coaches dropped)", len(df))
    return df


def read_road_exit_names_2015(context):
    """Road exit names (GUAUSREISESTRASSE) from the 2015 codebook: same codes as 2021."""
    path = Path("%s/%s" % (context.config("data_path"), CODEBOOK_2015))
    if not path.exists():
        logger.warning("AuGQPV 2015 codebook missing at %s; exit codes kept without names", path)
        return {}
    values = pd.read_excel(path, sheet_name="Werte & Labels", header=None, usecols=[0, 1, 2])
    values.columns = ["variable", "code", "description"]
    exits = values[values["variable"].ffill().eq("GUAUSREISESTRASSE")].copy()
    exits["code"] = pd.to_numeric(exits["code"], errors="coerce")
    exits = exits[exits["code"].notna() & exits["code"].ne(9999)]
    names = exits["description"].astype(str).str.replace(r"^\s*\d+\s*:\s*", "", regex=True).str.strip()
    return dict(zip(exits["code"].astype(int), names))
