# The demo's SDE team in Band

Four Band agents play the AI engineering team that ships to **astro-mini**: a coordinator, an engineer, a reviewer
and an analyst. Why-Graph watches what they ship, works out why production broke, and the **reviewer** consults
Why-Graph's memory before approving anything. That's the whole pitch in one loop:

```
you ──task──▶ Coordinator ──assigns──▶ Engineer ──PR──▶ Reviewer ──check_change_risk──▶ Why-Graph (MCP)
                  ▲                                         │ approve / request changes
                  │ incident_report (root cause, commit)    ▼
              Why-Graph ◀──alerts, deploys── astro-mini ◀──merge── Coordinator
                  │
                  └─ Analyst asks why_is / who_knows / incident_report → post-incident note with sources
```

Why the roles are split this way:
- **The engineer is never told to check for past incidents.** It does what a reasonable engineer would.
- **The reviewer must check.** In Act 2 it blocks the PR with a lesson from Act 1 that no agent remembers. Only the
  graph does, and that's the moment judges should see.
- **A human confirms the root cause** (the UI's *Confirm root cause + fix* button). That's what turns an incident
  into a lesson, and it keeps a person in the loop.

Never write task prompts that ask an agent to create a bug. The mistake has to come out of a normal request.

---

## 1. Setup checklist

| | What | Notes |
|---|---|---|
| 1 | `redwing-381/astro-mini` repo | The demo app (Sakthi). Its `config/services.yaml` is exactly `docs/work-split.md` §2 |
| 2 | A GitHub account for the Band agents, with write access to astro-mini | End its username with `bot` (e.g. `whygraph-coder-bot`) so Why-Graph records it as `Engineer {kind: 'agent'}` |
| 3 | Why-Graph running | `make db`, then `uv run python -m seed.load`, then `make api` |
| 4 | PR Guard | `GITHUB_TOKEN` (astro-mini only: PRs read, issues read/write, contents read) and `GITHUB_REPO=redwing-381/astro-mini` in `.env` |
| 5 | MCP for each Band agent | URL `http://localhost:8000/mcp/`; header `Authorization: Bearer <WHYGRAPH_API_TOKEN from .env>`. If Band runs in the cloud, expose the API first (`ngrok http 8000`, then use `https://<id>.ngrok.app/mcp/`) |
| 6 | astro-mini deployer + watcher running | So a merge really deploys and real 5xx raise alerts. Without them, run `uv run python scenarios/inject.py act1` after the merge |

MCP tools the agents get: `check_change_risk`, `incident_report`, `why_is`, `who_knows`, `get_service_context`.
They're described in `scenarios/sde-agent-kit.md`.

---

## 2. Team charter (paste into every agent, above its role prompt)

> You are part of a four-agent engineering team (coordinator, engineer, reviewer, analyst) that maintains
> astro-mini, a small online shop in the GitHub repo `redwing-381/astro-mini`. Services and their timeouts live in
> `config/services.yaml`. Work only through GitHub (branches, pull requests, PR comments) and the `why-graph`
> tools. Never force-push, never push to `main` directly, and never change files outside the task. Keep messages
> short and factual. When a `why-graph` tool returns node ids, quote the relevant ones; they are the evidence.

## 3. The four agents

### Coordinator
Tools: GitHub (read PRs, merge), `why-graph`: `incident_report`.

> You coordinate the team. Turn each request into one task with a clear outcome and assign it to the engineer.
> Merge a pull request only after the reviewer has approved it in writing and its checks pass.
>
> When production is failing, don't guess. Call `incident_report` (no arguments returns the latest open
> incident), then assign the fix to the engineer, quoting the root-cause claim, the guilty commit and the
> config key involved. After the fix is merged, ask the analyst for a post-incident note. Never edit code
> yourself.

### Engineer
Tools: GitHub (branch, commit, open and update PRs).

> You implement tasks in astro-mini. Make the smallest change that achieves the outcome, one pull request per
> task, from a fresh branch off `main`. The PR title says what changed; the body says why, and which values
> changed from what to what. When the reviewer requests changes, update the same PR and reply to each point. If
> the reviewer or the coordinator gives you a lesson id (like `L-1`), cite it in the PR body and say how you
> applied it. Never merge your own pull requests.

### Reviewer
Tools: GitHub (read diffs, comment, approve, request changes), `why-graph`: `check_change_risk`, `who_knows`.

> You review every pull request. For any PR that changes `config/services.yaml`, you **must** call
> `check_change_risk` before deciding. Pass the exact changes as `{service, key, old, new}` (key is the dotted
> path under the service, e.g. `timeouts_ms.quote`), plus the PR number and title.
>
> - If it returns warnings: **request changes**. Quote the advice, the lesson id, the incident it was learned
>   from and the safe value.
> - When the engineer updates the PR, check again.
> - Approve only when the check returns no warnings, and say in your approval that Why-Graph found no known
>   risk.
>
> Use `who_knows` to mention the owning team when a change touches a service you don't know. Keep reviews to a
> few lines.

### Analyst
Tools: `why-graph`: `incident_report`, `why_is`, `who_knows`, `get_service_context`.

> You explain the system. Answer only from what the `why-graph` tools return, and include the node ids they
> give as sources. After an incident, write a post-incident note of at most six lines: what broke, the root
> cause (commit, PR, author), the impact, who was paged, how it was fixed, and the lesson, once one exists. When
> asked why a config value is what it is, use `why_is` and tell the story from the change back to the incident.

---

## 4. What to type, act by act

Rehearse from a clean graph each time: `uv run python -m seed.load --reset`, then restart the API.

### Act 1: a brand-new mistake (about 90 s on camera)
1. **To the coordinator:** "Checkout feels slow under load. Have the engineer reduce checkout latency by tightening
   how long checkout waits on its slowest dependency. Config change only."
2. **The engineer** opens a PR lowering `services.checkout.timeouts_ms.payment` from 800 to about 200.
3. **The reviewer** calls `check_change_risk` and gets "No known risk", because nothing has been learned yet, so
   it approves. PR Guard comments the same.
4. **The coordinator** merges. The deployer ships it, checkout starts returning 502s, and the watcher alerts.
5. **On screen:** the Why-Graph Incident view, with the four agents and the evidence path from the alert to PR to
   the bot that opened it.
6. **To the coordinator:** "Production is failing. Find out why and get it fixed." The coordinator calls
   `incident_report`, then assigns the engineer to restore the payment timeout. The reviewer checks it, the
   coordinator merges, and the service recovers.
7. **You** click **Confirm root cause + fix** in the UI, or run:
   `curl -s -X POST localhost:8000/api/incidents/<ID>/resolve -H 'Content-Type: application/json' -d '{"fix":"Restore checkout timeouts_ms.payment to 800","resolved_by":"priya"}'`.
   Lesson L-1 and detector D-1 are written.
8. **To the analyst:** "Write the post-incident note for <ID>."

### Restart (about 10 s)
- Run `docker compose restart api`.
- **Start fresh Band sessions for all four agents**, so none of them carries any memory of Act 1. Only the graph
  remembers.

### Act 2: the AI now knows (about 40 s, the money shot)
1. **To the coordinator:** "The shipping estimate is slow. Make shipping fail fast instead of waiting so long on its
   quote provider. Config change only."
2. **The engineer** opens a PR lowering `services.shipping.timeouts_ms.quote` from 600 to about 100.
3. **The reviewer** calls `check_change_risk` and gets **high risk**: lesson L-1 from Act 1's incident, safe value
   ≈ 450 (1.5 × quote's p99). It requests changes.
4. **The engineer** updates to 450 and cites L-1. The reviewer checks again, finds no known risk, and approves.
   PR Guard's comment flips to "Lesson L-1 applied". The coordinator merges, and nothing breaks.
5. **On screen:** the Memory tab, where L-1 shows `prevented: 1`. Then the A/B: the same change checked against the
   tenant that never learned returns `none`:
   `curl -s -X POST 'localhost:8000/api/guard/check?graph=whygraph_fresh' -H 'Content-Type: application/json' -d '{"changes":[{"service":"shipping","key":"timeouts_ms.quote","old":600,"new":100}]}'`

### Act 3 (optional): a human overrides the guard
- **You**, as a human, open and merge a PR setting `services.recommendation.timeouts_ms.product-catalog` from 400
  to 80, ignoring PR Guard's warning.
- The incident follows, and Memory flags it as the known mistake from Act 1 within seconds. The graph records
  `PR-[:IGNORED]->Lesson`.

### Close
- **To the analyst:** "Why is shipping→quote 450 ms?" The answer runs the chain decision → lesson → Act 1 incident →
  the original PR, with node ids.
- In the UI, click any claim to open the Cypher drawer, then **Run live**.

## 5. If something goes wrong on camera

| Problem | Fallback |
|---|---|
| The engineer picks an odd value | Ask it for the exact value from the act (200 / 100 / 450). The story only needs the direction |
| astro-mini didn't break, or there's no alert | `uv run python scenarios/inject.py act1` (or `act3`) replays the deploy and alerts |
| The reviewer skips the check | Remind it: "Run check_change_risk on this PR before deciding." Or show the PR Guard comment, which runs the same check |
| A Band agent can't reach MCP | Check the URL ends in `/mcp/` and the bearer token matches `.env`. For a cloud Band, the tunnel must be up |
| Live LLM agents are slow | Record each act separately. The Why-Graph side also runs graph-only (`GRAPH_ONLY=true`) |
