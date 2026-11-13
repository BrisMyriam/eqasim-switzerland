"""Locate the STATPOP files of the configured year (statpop_year, default 2023).

Files are expected in data_path/statpop/:
    STATPOP_PP_<year>_TEIL_1.csv, STATPOP_PP_<year>_TEIL_2.csv
    STATPOP_<year>_LINK_CH.csv
    STATPOP_<year>_HOUSEHOLD_CH_K.csv or STATPOP_<year>_HOUSEHOLD_CH.csv
"""

import os

DEFAULT_YEAR = 2023

# Row counts, only used for the progress bar
KNOWN_TOTALS = {
    2023: {"household": 3964840, "link": 9191057},
}


def configure_year(context):
    context.config("statpop_year", DEFAULT_YEAR)


def statpop_year(context):
    return int(context.config("statpop_year"))


def statpop_path(context, kind):
    data_path = context.config("data_path")
    year = statpop_year(context)
    candidates = {
        "persons_1": ["STATPOP_PP_%d_TEIL_1.csv" % year],
        "persons_2": ["STATPOP_PP_%d_TEIL_2.csv" % year],
        "link": ["STATPOP_%d_LINK_CH.csv" % year],
        "household": ["STATPOP_%d_HOUSEHOLD_CH_K.csv" % year, "STATPOP_%d_HOUSEHOLD_CH.csv" % year],
    }[kind]
    paths = ["%s/statpop/%s" % (data_path, name) for name in candidates]
    for path in paths:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("STATPOP %s file for %d not found, tried: %s" % (kind, year, paths))


def known_total(context, kind):
    return KNOWN_TOTALS.get(statpop_year(context), {}).get(kind)
