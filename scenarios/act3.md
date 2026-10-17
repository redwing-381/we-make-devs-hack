# Act 3 task (optional): a human overrides the guard

As a human engineer, open a PR that sets `services.recommendation.timeouts_ms.product-catalog` from 400 to 80
("catalog is fast"). Merge it despite the PR Guard warning.

<!-- Expected: PR-[:IGNORED]->Lesson, real 5xx on recommendation + frontend, and Memory recalls INC-1031 in
     about 3 s. Fallback with no app: uv run python scenarios/inject.py act3 -->
