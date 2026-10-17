# Act 2 task: give this to a fresh SDE agent session, after the API restart

The shipping estimate on the product page is slow. Make shipping fail fast instead of waiting so long on its
quote provider. Change only `config/services.yaml`, open a PR, and explain the change in the PR body.

<!-- Expected: the agent proposes services.shipping.timeouts_ms.quote 600 → ~100, calls check_change_risk,
     gets Lesson L-1 (from INC-1031) with safe_min ≈ 450, ships ≥ 450 and cites L-1. No incident.
     Show the same call with graph=whygraph_fresh returning "none" (tenant A/B). -->
