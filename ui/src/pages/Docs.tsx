import { useEffect, useState, type ReactNode } from "react";

const REPO = "https://github.com/redwing-381/we-make-devs-hack";

const SECTIONS = [
  { id: "loop", title: "How it fits" },
  { id: "run", title: "Run Why-Graph" },
  { id: "model", title: "Describe your services" },
  { id: "config", title: "Keep config in one file" },
  { id: "deploys", title: "Send deploys" },
  { id: "signals", title: "Send telemetry and alerts" },
  { id: "mcp", title: "Connect your agents" },
  { id: "learn", title: "Close the loop" },
  { id: "limits", title: "What works today" },
] as const;

function Code({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="codeblock">
      <pre>{children}</pre>
      <button
        onClick={() =>
          navigator.clipboard?.writeText(children).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={`docs-${id}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

/** How a team attaches Why-Graph to its own repo, services and coding agents. */
export function DocsPage() {
  const [on, setOn] = useState<string>("loop");
  const origin = window.location.origin;

  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(`docs-${s.id}`)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setOn(top.target.id.replace("docs-", ""));
      },
      { rootMargin: "-80px 0px -60% 0px" },
    );
    els.forEach((el) => io.observe(el));
    // deep link: #docs/mcp
    const sub = window.location.hash.split("/")[1];
    if (sub) document.getElementById(`docs-${sub}`)?.scrollIntoView();
    return () => io.disconnect();
  }, []);

  return (
    <div className="docs">
      <nav className="toc" aria-label="On this page">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#docs/${s.id}`}
            className={on === s.id ? "on" : ""}
            onClick={(e) => {
              e.preventDefault();
              history.replaceState(null, "", `#docs/${s.id}`);
              document.getElementById(`docs-${s.id}`)?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            {s.title}
          </a>
        ))}
      </nav>

      <article className="doc">
        <h1>Attach Why‑Graph to your repo</h1>
        <p className="lede">
          Why-Graph needs four feeds from your system: who owns which service, what you deploy, what your services see
          at runtime, and the alerts you already have. Your coding agents then reach its memory over MCP.
        </p>
        <p className="muted">Plan on about half an hour for a first service. Everything below runs on your own machine.</p>

        <Section id="loop" title="How it fits">
          <p>
            Your repo stays where it is. Why-Graph sits next to it, keeps one FalkorDB graph per team, and listens.
          </p>
          <div className="loop">
            <div>
              <strong>You merge</strong>A PR changes a timeout in your config file.
            </div>
            <div>
              <strong>You deploy</strong>CI posts the deploy and the config diff.
            </div>
            <div>
              <strong>It breaks, it explains</strong>Alerts arrive; four agents trace the cause as a graph path.
            </div>
            <div>
              <strong>You confirm</strong>One click turns the fix into a lesson and a detector.
            </div>
            <div>
              <strong>Next PR is checked</strong>Agents call <code>check_change_risk</code> before they open a PR.
            </div>
          </div>
        </Section>

        <Section id="run" title="Run Why-Graph">
          <p>You need Docker, Python 3.12 with uv, and Node 22.</p>
          <Code>{`git clone ${REPO}
cd we-make-devs-hack
cp .env.example .env          # fill in the keys listed below
docker compose up -d falkordb
uv sync
uv run python -m seed.load --reset --no-act1
uv run uvicorn whygraph.api.main:app --port 8000

# in a second terminal
cd ui && npm install && npm run dev   # http://localhost:5173`}</Code>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Setting in .env</th>
                  <th>What it does</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>ANTHROPIC_API_KEY</code></td>
                  <td>Lets the agents write narrative with Claude. Leave it empty and set <code>GRAPH_ONLY=true</code> to run on graph queries alone.</td>
                </tr>
                <tr>
                  <td><code>VOYAGE_API_KEY</code></td>
                  <td>Embeddings for incident and runbook similarity. Optional: structural matching works without it (load with <code>--no-embed</code>).</td>
                </tr>
                <tr>
                  <td><code>WHYGRAPH_API_TOKEN</code></td>
                  <td>The bearer token your agents send to <code>/mcp/</code>. Use a long random value.</td>
                </tr>
                <tr>
                  <td><code>WHYGRAPH_GRAPH</code></td>
                  <td>Which graph (tenant) to use. One graph per team or environment.</td>
                </tr>
                <tr>
                  <td><code>GITHUB_TOKEN</code>, <code>GITHUB_REPO</code></td>
                  <td>Optional. Turns on PR Guard, which comments its verdict on your open PRs.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Section>

        <Section id="model" title="Describe your services">
          <p>
            The graph needs to know your services, teams and people before events can attach to them. Edit{" "}
            <code>seed/data/core.json</code> and reload with <code>seed.load --reset</code>. Calls between services
            come in later from telemetry, but list the ones you know so blast radius works from day one.
          </p>
          <Code>{`{
  "nodes": {
    "Team":     [{ "id": "team:payments", "name": "Payments" }],
    "Engineer": [{ "id": "eng:priya", "name": "Priya Raman", "handle": "priya",
                   "kind": "human", "on_call": true },
                 { "id": "eng:coder-bot", "name": "coder-bot", "handle": "coder-bot",
                   "kind": "agent", "on_call": false }],
    "Service":  [{ "id": "svc:checkout", "name": "checkout", "tier": "core" },
                 { "id": "svc:payment",  "name": "payment",  "tier": "core" }]
  },
  "rels": [
    { "type": "MEMBER_OF", "src": "eng:priya",     "dst": "team:payments", "props": {} },
    { "type": "OWNS",      "src": "team:payments", "dst": "svc:payment",   "props": {} },
    { "type": "CALLS",     "src": "svc:checkout",  "dst": "svc:payment",   "props": { "p99_ms": 450 } }
  ]
}`}</Code>
          <p>
            Mark coding agents with <code>"kind": "agent"</code>. Deploy authors whose handle ends in <code>bot</code>{" "}
            are stored as agents automatically.
          </p>
        </Section>

        <Section id="config" title="Keep config in one file">
          <p>
            Why-Graph reasons about changes it can see as data. Keep each service's timeouts to its dependencies in{" "}
            <code>config/services.yaml</code>. Each entry becomes a config key such as{" "}
            <code>checkout.timeouts_ms.payment</code>, linked to the caller and the callee.
          </p>
          <Code>{`services:
  checkout:
    timeouts_ms: {payment: 800, cart: 300, shipping: 1500}
  shipping:
    timeouts_ms: {quote: 600}`}</Code>
        </Section>

        <Section id="deploys" title="Send deploys">
          <p>
            After every deploy, post what shipped and how the config file changed between the old and new commit. Run
            this from CI on your main branch. <code>config_changes</code> is the diff of{" "}
            <code>services.yaml</code>; <code>config_diff()</code> in <code>scenarios/astro_sim.py</code> computes it if
            you want a reference.
          </p>
          <Code>{`curl -X POST ${origin}/api/deploys -H 'content-type: application/json' -d '{
  "sha": "9f2c1ab", "repo": "your-org/your-repo", "services": ["checkout"],
  "ts": 1792304820000, "pr_number": 12, "author": "coder-bot",
  "message": "Reduce checkout latency",
  "config_changes": [
    { "service": "checkout", "key": "timeouts_ms.payment", "old": 800, "new": 200 }
  ]
}'`}</Code>
          <p>
            Each change is stored as <code>(Commit)-[:CHANGES]→(ConfigKey)</code> together with the callee's p99 at that
            moment, so the evidence does not drift later.
          </p>
          <div className="callout">
            <p>
              Want to try it on a repo before wiring CI? <code>uv run python scenarios/astro_sim.py --repo
              your-org/your-repo</code> watches <code>main</code> and posts real deploys from real diffs. Its telemetry and
              alerts are simulated from a <code>latency_ms</code> block, so use it for demos, not production.
            </p>
          </div>
        </Section>

        <Section id="signals" title="Send telemetry and alerts">
          <h3>Telemetry: latency per call edge</h3>
          <p>
            Post each caller to callee edge with its p99 measured on the <strong>callee</strong> side, so a caller's own
            timeout can't clip the number. OpenTelemetry span metrics give you this directly.
          </p>
          <Code>{`curl -X POST ${origin}/api/telemetry -H 'content-type: application/json' -d '{
  "ts": 1792305010000,
  "edges": [{ "caller": "checkout", "callee": "payment", "p99_ms": 452.0, "error_rate": 0.61 }]
}'`}</Code>
          <h3>Alerts: from the monitoring you already run</h3>
          <p>
            Forward alerts with a small webhook transform (Alertmanager, Grafana and Datadog can all post JSON). Alerts
            within two minutes of each other join one incident, and the agents start five seconds after the first one.
          </p>
          <Code>{`curl -X POST ${origin}/api/alerts -H 'content-type: application/json' -d '{
  "id": "a-901", "service": "checkout", "signal": "error_rate", "value": 0.62,
  "threshold": 0.10, "severity": "sev2", "ts": 1792305000000, "source": "alertmanager"
}'`}</Code>
          <p>
            The incident then shows up in the Incident tab, and every finding links to the query that proves it.
          </p>
        </Section>

        <Section id="mcp" title="Connect your agents">
          <p>
            Any MCP client that speaks streamable HTTP can use Why-Graph. Keep the trailing slash on the URL.
          </p>
          <Code>{`{
  "mcpServers": {
    "why-graph": {
      "type": "http",
      "url": "${origin}/mcp/",
      "headers": { "Authorization": "Bearer <WHYGRAPH_API_TOKEN>" }
    }
  }
}`}</Code>
          <p>For Claude Code, one command does the same:</p>
          <Code>{`claude mcp add --transport http why-graph ${origin}/mcp/ \\
  --header "Authorization: Bearer $WHYGRAPH_API_TOKEN"`}</Code>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>When an agent should call it</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>check_change_risk</code></td>
                  <td>Before every PR that edits config. Returns the risk, the lesson it matched, a safe minimum and the evidence path.</td>
                </tr>
                <tr>
                  <td><code>incident_report</code></td>
                  <td>When something is broken: root cause, guilty commit, blast radius and who was paged.</td>
                </tr>
                <tr>
                  <td><code>why_is</code></td>
                  <td>Before changing a value: the change, PR, decision and incident behind it.</td>
                </tr>
                <tr>
                  <td><code>who_knows</code></td>
                  <td>To find the owner, the on-call engineer and the people with history on a service.</td>
                </tr>
                <tr>
                  <td><code>get_service_context</code></td>
                  <td>Dependencies with their current p99 latency, and owners.</td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3>Add this to your agents' instructions</h3>
          <Code>{`Before you open a pull request that changes config/services.yaml (timeouts, retries,
pool sizes, flags) or how services call each other, call the why-graph tool
check_change_risk with the exact changes. If it returns warnings, follow its advice
(for example, use at least the safe_min value) and put the lesson id and a one-line
reason in the PR description. Don't skip the check because a change looks small.`}</Code>
        </Section>

        <Section id="learn" title="Close the loop">
          <p>
            When the fix is in, open the incident and press <strong>Confirm the root cause and the fix</strong>. From a
            script, post the same thing:
          </p>
          <Code>{`curl -X POST ${origin}/api/incidents/INC-1031/resolve -H 'content-type: application/json' \\
  -d '{"fix": "Restore checkout timeouts_ms.payment to 800", "resolved_by": "priya"}'`}</Code>
          <p>Memory then writes three things to the graph:</p>
          <ul>
            <li>a <strong>lesson</strong> linked to the incident, the failure pattern and the evidence;</li>
            <li>a <strong>detector</strong>, stored Cypher that must fire on this incident before it is saved, then backtested on your history;</li>
            <li>a <strong>decision</strong> that <code>why_is</code> and the Brain can trace back later.</li>
          </ul>
          <p>
            The next <code>check_change_risk</code> that matches the pattern on any service returns the lesson and a safe
            value. When an agent follows it, the lesson's confidence rises and its prevented count goes up.
          </p>
        </Section>

        <Section id="limits" title="What works today">
          <ul>
            <li>Config diffs are read from <code>config/services.yaml</code>. Other formats need a small adapter that produces the same <code>config_changes</code> list.</li>
            <li>The shipped detector template covers a timeout set below the callee's p99. Lessons for other failure patterns are matched by shape and by text similarity.</li>
            <li>Each team or environment gets its own graph (<code>WHYGRAPH_GRAPH</code>), so what one learns never leaks into another.</li>
            <li>PR Guard comments on GitHub only. Other forges can call <code>check_change_risk</code> over MCP or HTTP.</li>
          </ul>
          <p>
            Source, schema and the full query catalog are in the <a href={REPO}>repository</a>.
          </p>
        </Section>
      </article>
    </div>
  );
}
