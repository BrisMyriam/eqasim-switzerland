import pandas as pd


def configure(context):
    context.config("data_path")
    from data.statpop.files import configure_year
    configure_year(context)


def execute(context):
    data_path = context.config("data_path")

    import lzma as xz
    import data.utils
    from data.statpop.files import statpop_path

    part_1 = statpop_path(context, "persons_1")
    part_2 = statpop_path(context, "persons_2")

    # INDIC_EGID (building-level geocoding) does not exist in older releases, e.g. 2015
    with open(part_1, mode="rb") as f:
        has_egid_indicator = "INDIC_EGID" in f.readline().decode("latin1").strip().split(";")

    fields = {
        "personPseudoID": int,
        "SEX": int,
        "AGE": int,
        "MARITALSTATUS": int,
        "NATIONALITYCATEGORY": int,
        "GEOCOORDN": float,
        "GEOCOORDE": float,
        "POPULATIONTYPE": int,
        "TYPEOFRESIDENCE": int,
        "REPORTINGMUNICIPALITYID": int,
        "INDIC_EGID": int,
    }

    renames = {
        "personPseudoID": "person_id",
        "SEX": "sex",
        "AGE": "age",
        "MARITALSTATUS": "marital_status",
        "NATIONALITYCATEGORY": "nationality",
        "GEOCOORDN": "home_y",
        "GEOCOORDE": "home_x",
        "POPULATIONTYPE": "population_type",
        "TYPEOFRESIDENCE": "type_of_residence",
        "REPORTINGMUNICIPALITYID": "municipality_id",
        "INDIC_EGID": "statpop_geocoding_indicator",
    }

    if not has_egid_indicator:
        del fields["INDIC_EGID"]

    with open(part_1, mode="rb") as f1, open(part_2, mode="rb") as f2:
        df1 = data.utils.read_csv(context, f1, fields, renames, total=None)
        df2 = data.utils.read_csv(context, f2, fields, renames, total=None)

    # Combine them into one DataFrame
    df = pd.concat([df1, df2], ignore_index=True)

    # Legacy flag used by matching to restrict donors to home-only activity chains.
    # It detects administrative-centre/unknown coordinates, NOT verified residence
    # in an institution: geocoded dorm/care-home residents can have this flag False.

    municipality_centers = pd.read_excel(f"{data_path}/spatial/municipality_centers/be-b-00.03-gg22.xlsx", sheet_name = "g1g22")
    municipality_centers = list(zip(municipality_centers["E_CNTR"], municipality_centers["N_CNTR"]))

    df["coords"] = list(zip(df["home_x"], df["home_y"]))

    df["collective_housing_resident"] = False
    df.loc[df["coords"].isin(municipality_centers),     "collective_housing_resident"] = True
    df.loc[(df["home_x"] == -9) & (df["home_y"] == -9), "collective_housing_resident"] = True # Unknown home location?

    del df["coords"]

    if not has_egid_indicator:
        # Reconstruct INDIC_EGID = 1 (geocoded to a building) from the coordinates.
        # In STATPOP 2023, "positive coordinates and not a municipality centre" matches
        # INDIC_EGID == 1 for all but 81 of 5.7 million persons (TEIL_1).
        geocoded = (df["home_x"] > 0) & (df["home_y"] > 0) & ~df["collective_housing_resident"]
        df["statpop_geocoding_indicator"] = geocoded.astype(int)
        print("STATPOP without INDIC_EGID: geocoding indicator reconstructed from coordinates (%.2f%% geocoded)"
              % (100 * geocoded.mean()))

    return df
