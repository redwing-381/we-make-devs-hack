"""Snapshot and restore the demo graph so we can rehearse each act in a loop (F-A4).

    uv run python scripts/reset_to.py save act1      # GRAPH.COPY whygraph_demo -> snap_act1
    uv run python scripts/reset_to.py act1           # delete whygraph_demo, copy snap_act1 back
    uv run python scripts/reset_to.py seed           # no snapshot needed: reload the seed from scratch
    uv run python scripts/reset_to.py list           # which snapshots exist
    ... --graph whygraph_fresh                       # any tenant graph, not just the demo one

Snapshots are ordinary FalkorDB graphs named snap_<name>, so they survive restarts of the API and of FalkorDB
(the data volume persists them).
"""

import argparse
import re
import sys
from pathlib import Path

from whygraph.graph.client import get_db

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PREFIX = "snap_"


def snapshot_name(name: str) -> str:
    if not NAME.match(name):
        raise SystemExit(f"invalid snapshot name {name!r}")
    return PREFIX + name


def exists(graph: str) -> bool:
    return graph in get_db().list_graphs()


def copy(src: str, dst: str) -> None:
    """GRAPH.COPY src -> dst, replacing dst."""
    db = get_db()
    if not exists(src):
        raise SystemExit(f"graph {src!r} does not exist")
    if exists(dst):
        db.select_graph(dst).delete()
    db.select_graph(src).copy(dst)


def save(name: str, graph: str) -> str:
    snap = snapshot_name(name)
    copy(graph, snap)
    return snap


def restore(name: str, graph: str) -> str:
    snap = snapshot_name(name)
    if not exists(snap):
        raise SystemExit(f"no snapshot {snap!r}; create it with: reset_to.py save {name}")
    copy(snap, graph)
    return snap


def snapshots() -> list[str]:
    return sorted(g.removeprefix(PREFIX) for g in get_db().list_graphs() if g.startswith(PREFIX))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="reset_to.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--graph", default="whygraph_demo", help="tenant graph to snapshot or restore")
    ap.add_argument("target", help="snapshot name to restore, or: save <name> | seed | list")
    ap.add_argument("name", nargs="?", help="snapshot name for `save`")
    args = ap.parse_args(argv)

    if args.target == "list":
        print("\n".join(snapshots()) or "(no snapshots)")
    elif args.target == "save":
        if not args.name:
            ap.error("save needs a snapshot name, e.g. `save act1`")
        print(f"saved {args.graph} -> {save(args.name, args.graph)}")
    elif args.target == "seed":
        from seed.load import load

        counts = load(args.graph, reset=True)
        print(f"reseeded {args.graph}: {counts}")
    else:
        print(f"restored {args.graph} <- {restore(args.target, args.graph)}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `seed` imports from the repo root
    main()
