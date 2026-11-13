"""Select the microcensus (MZ/MRMT) release used by the person-level models.

Config option microcensus_year: 2021 (default, current model) or 2015 (retrofit 2015-16).
With 2015, no data.microcensus.21.* stage is required anywhere.
"""

import pandas as pd

DEFAULT_YEAR = 2021


def configure_year(context):
    context.config("microcensus_year", DEFAULT_YEAR)
    year = int(context.config("microcensus_year"))
    if year not in (2015, 2021):
        raise ValueError("microcensus_year must be 2015 or 2021, got %s" % year)
    return year


def microcensus_year(context):
    return int(context.config("microcensus_year"))


def stage_name(context, name):
    """e.g. stage_name(context, "persons") -> data.microcensus.21.persons or data.microcensus.persons"""
    prefix = "data.microcensus.21" if microcensus_year(context) == 2021 else "data.microcensus"
    return "%s.%s" % (prefix, name)


def household_persons_with_license(context):
    """Household persons with a 0/1 driving_license column, for both releases.

    The 2015 household_persons stage has no licence column. It is added here from the
    raw file (f20400a == 1, same coding as 2021) instead of in the shared 2015 stage,
    which subscriptions.py also reads (adding it there would change the 2021 model).
    """
    household_persons = context.stage(stage_name(context, "household_persons"))[0].copy()
    if "driving_license" not in household_persons:
        raw = pd.read_csv("%s/microcensus/haushaltspersonen.csv" % context.config("data_path"),
                          sep=",", encoding="latin1", usecols=["HHNR", "HPNR", "f20400a"])
        raw = raw.rename(columns={"HHNR": "household_id", "HPNR": "hhpers_id"})
        household_persons = household_persons.merge(raw, on=["household_id", "hhpers_id"],
                                                    how="left", validate="one_to_one")
        household_persons["driving_license"] = pd.to_numeric(
            household_persons.pop("f20400a"), errors="coerce").eq(1).astype(int)
    return household_persons
