# SDE agent kit: connect our agent team to Why-Graph

The Band team for the demo (roles, prompts, act-by-act script) is in `scenarios/band-team.md`.

Our SDE agents reach Why-Graph's memory over **MCP**. The tools are defined in `whygraph/integrations/mcp_server.py`.

## Endpoint

| | |
|---|---|
| URL | `http://localhost:8000/mcp/` locally, `https://<vm-host>/mcp/` live (trailing slash included) |
| Transport | Streamable HTTP |
| Auth | Header `Authorization: Bearer $WHYGRAPH_API_TOKEN` (the value is in our shared `.env`) |

Any MCP client that speaks streamable HTTP works. Two common shapes:

```json
{
  "mcpServers": {
    "why-graph": {
      "type": "http",
      "url": "http://localhost:8000/mcp/",
      "headers": { "Authorization": "Bearer ${WHYGRAPH_API_TOKEN}" }
    }
  }
}
```

```bash
claude mcp add --transport http why-graph http://localhost:8000/mcp/ --header "Authorization: Bearer $WHYGRAPH_API_TOKEN"
```

## Tools

| Tool | Use it for |
|---|---|
| `check_change_risk(changes, title?, diff?, author?, pr_number?, graph?)` | **Before every PR that edits `config/services.yaml`.** Returns `risk` (none/low/medium/high), `warnings` (lesson, incident, `safe_min`, evidence path) and `advice` |
| `who_knows(service)` | Owner team, on-call engineer, and the people with commits or resolved incidents on that service |
| `why_is(service, key)` | The change → PR → decision → lesson → incident behind a config value |
| `get_service_context(service)` | Dependencies with current p99 latencies, plus owners |
| `incident_report(incident_id?)` | What broke and why: the latest open incident (or the one named), its root-cause finding, guilty commit, blast radius, Memory's recall, the status update, and every finding with node ids |

`changes` holds `services.yaml` edits:

```json
{"changes": [{"service": "shipping", "key": "timeouts_ms.quote", "old": 600, "new": 100}],
 "title": "Tune shipping→quote timeout", "author": "coder-bot", "pr_number": 15}
```

`graph` picks the tenant. Leave it out to use `whygraph_demo`; use `whygraph_fresh` for the A/B shot, a graph
that has learned nothing.

## Add this to the SDE agents' system prompt

> Before you open a pull request that changes `config/services.yaml` (timeouts, retries, pool sizes, flags) or
> how services call each other, call the `why-graph` tool `check_change_risk` with the exact changes. If it
> returns warnings, follow its advice (for example, use at least the `safe_min` value), and put the lesson id
> and a one-line reason in the PR description. Don't skip the check because a change looks small.

Keep the task prompts (`act1.md`–`act3.md`) free of any hint about past incidents. The point of the demo is
that the warning comes from the graph.

## Smoke test without an agent

```bash
curl -s -X POST localhost:8000/api/guard/check -H 'Content-Type: application/json' \
  -d '{"changes":[{"service":"shipping","key":"timeouts_ms.quote","old":600,"new":100}]}'
```

- **Before Act 1 is resolved:** `"risk": "none"`.
- **After it (once F-A3 has merged):** `"risk": "high"` with lesson L-1 and `safe_min` 453.
- **`?graph=whygraph_fresh`:** always `"risk": "none"`.
