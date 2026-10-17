## Feature

<!-- ID + name from docs/features.md, e.g. "F-A2 query catalog" -->

## What changed

-

## How to verify

<!-- commands / screenshots: make test, make smoke, UI steps -->

## Checklist

- [ ] Only touches files listed for this feature in `docs/features.md` (or explains why)
- [ ] **Contract change?** (`docs/schema.md`, `docs/events.md`, `whygraph/models/events.py`, `ui/src/types/events.ts`) — if yes, pinged the other owners and updated both mirrors
- [ ] New/changed Cypher is in `whygraph/graph/queries.py` with a plain-English `explain`, and `make docs` was run
- [ ] `make lint` and `make test` pass locally
- [ ] I can explain every query and decision in this PR to a judge
