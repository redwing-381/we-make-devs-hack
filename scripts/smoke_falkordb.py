"""Print which FalkorDB features work on the running server. Usage: make smoke"""

import sys

from whygraph.graph.client import get_db, ping
from whygraph.graph.smoke import CHECKS, run_check


def main() -> int:
    if not ping():
        print("FalkorDB is not reachable — run `make db` first.")
        return 2
    db = get_db()
    info = db.connection.info("server").get("redis_version", "?")
    print(f"FalkorDB server (redis {info})\n")
    failed_critical = False
    for check in CHECKS:
        ok, note = run_check(db, check)
        tag = "PASS" if ok else ("FAIL" if check.critical else "WARN")
        failed_critical |= check.critical and not ok
        print(f"  {tag:4}  {check.name:34} {note}")
    print(
        "\nAll critical checks passed." if not failed_critical else "\nCritical checks FAILED — see plan §5."
    )
    return 1 if failed_critical else 0


if __name__ == "__main__":
    sys.exit(main())
