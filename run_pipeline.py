"""Run the synpp pipeline with a faster stage resolution.

Usage (same arguments as `python -m synpp`):
    uv run run_pipeline.py config.yml

synpp 1.7.3 resolves the stage graph in `process_stages` by walking every path
from the source stages down to the requested ones, without remembering which
stages it has already visited. The number of paths grows very quickly with the
size of the graph: for `matsim.output` this takes about 1 h 45 min before the
first stage runs.

This script replaces the two path-walking loops by a single pass over the
stages in topological order. The per-stage logic (connecting dependencies and
propagating configuration options upstream -> downstream) is kept unchanged,
so the resulting registry, and therefore every stage hash, is identical to the
one of the original function. This was checked field by field on
`synthesis.output` and `matsim.output`.

If the installed synpp does not have the expected code, the original function
is used and a warning is printed.

It also fixes the deletion of write-protected files (e.g. the .git folder of a
cloned repository) when a stage is rerun: since Python 3.12, shutil.rmtree
reports failures through os.unlink, which synpp's error handler does not
recognise, so the run stopped with "PermissionError: Access is denied".
"""
import errno
import inspect
import logging
import os
import stat
import sys

import synpp
import synpp.pipeline as pipeline

logger = logging.getLogger("synpp")

PATCHED_SYNPP_VERSIONS = ["1.7.3"]

TOPOLOGICAL_LOOPS = '''
    # Connect downstream stages with upstream stages via dependency field
    for stage_hash, stage in hashed_stages.items():
        for downstream_info in stage.get("downstream", []):
            downstream = hashed_stages[downstream_info["hash"]]
            if not "dependencies" in downstream:
                downstream["dependencies"] = [None] * downstream_info["length"]
            downstream["dependencies"][downstream_info["position"]] = stage_hash

    # Update configuration requirements, visiting each stage once after all its upstream stages
    remaining = {h: len(set(s.get("dependencies", []))) for h, s in hashed_stages.items()}
    children = {h: set() for h in hashed_stages}
    for h, s in hashed_stages.items():
        for upstream_hash in set(s.get("dependencies", [])):
            children[upstream_hash].add(h)
    pending = [h for h, n in remaining.items() if n == 0]

    while len(pending) > 0:
        stage_hash = pending.pop()
        stage = hashed_stages[stage_hash]
        for child in children[stage_hash]:
            remaining[child] -= 1
            if remaining[child] == 0:
                pending.append(child)
'''

START_ANCHOR = "    # Connect downstream stages with upstream stages"
CONFIG_ANCHOR = '        if "dependencies" in stage:\n            passed_config_options'
END_ANCHOR = '        if "downstream" in stage:\n            for downstream in stage["downstream"]:\n                pending.append'
TAIL_ANCHOR = "    # Hash all stages"


def build_fast_process_stages():
    source = inspect.getsource(pipeline.process_stages)
    for anchor in (START_ANCHOR, CONFIG_ANCHOR, END_ANCHOR, TAIL_ANCHOR):
        if source.count(anchor) != 1:
            raise RuntimeError("unexpected synpp.process_stages source")

    start = source.index(START_ANCHOR)
    config_update = source[source.index(CONFIG_ANCHOR):source.index(END_ANCHOR)]
    tail = source[source.index(TAIL_ANCHOR):]

    fast_source = source[:start] + TOPOLOGICAL_LOOPS + config_update + "\n" + tail
    namespace = dict(vars(pipeline))
    exec(compile(fast_source, pipeline.__file__, "exec"), namespace)
    return namespace["process_stages"]


def patch_synpp():
    version = getattr(synpp, "__version__", None)
    if version is None:
        from importlib.metadata import version as package_version
        version = package_version("synpp")

    if version not in PATCHED_SYNPP_VERSIONS:
        logger.warning("synpp %s is not patched (expected %s): using the original stage resolution",
            version, ", ".join(PATCHED_SYNPP_VERSIONS))
        return

    try:
        pipeline.process_stages = build_fast_process_stages()
        logger.info("Using topological stage resolution for synpp %s", version)
    except Exception as error:
        logger.warning("Could not patch synpp (%s): using the original stage resolution", error)


def handle_rmtree_error(delegate, path, exc_info):
    # same as synpp.pipeline.handle_rmtree_error, but also accepts os.unlink
    if delegate in (os.rmdir, os.remove, os.unlink) and exc_info[1].errno == errno.EACCES:
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        delegate(path)
    else:
        raise exc_info[1]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    patch_synpp()
    pipeline.handle_rmtree_error = handle_rmtree_error
    synpp.run_from_cmd(sys.argv[1:])
