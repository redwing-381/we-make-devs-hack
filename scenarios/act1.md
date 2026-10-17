# Act 1 task: give this to the SDE agents verbatim

Checkout feels slow under load. Reduce checkout latency in astro-mini by tightening how long checkout waits on
its slowest dependency. Change only `config/services.yaml`, open a PR, and explain the change in the PR body.

<!-- Expected: the agent lowers services.checkout.timeouts_ms.payment from 800 to ~200 (payment p99 ≈ 450).
     PR Guard / check_change_risk: "No known risk" (nothing learned yet). After merge: real 5xx, alert,
     investigation. Fallback with no app: uv run python scenarios/inject.py act1 -->
