def configure(context):
    context.config("data_path")
    from data.statpop.files import configure_year
    configure_year(context)


def execute(context):
    import lzma as xz
    import data.utils
    from data.statpop.files import statpop_path, known_total

    with open(statpop_path(context, "link"), mode="rb") as f:
        fields = {
            "personPseudoId" : int,
            "HOUSEHOLDID" : int,
            "REPORTINGMUNICIPALITYID" : int
        }

        renames = {
            "personPseudoId" : "person_id",
            "HOUSEHOLDID" : "household_id",
            "REPORTINGMUNICIPALITYID" : "municipality_id"
        }

        return data.utils.read_csv(context, f, fields, renames, total = known_total(context, "link"),
                                   case_insensitive = True)
