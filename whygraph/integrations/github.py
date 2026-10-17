"""PR Guard: watch astro-mini pull requests, check their config changes, and say so on the PR.

Every POLL_S seconds it lists recently updated PRs. For a new head commit touching config/services.yaml it:
  1. diffs services.yaml at the merge base vs the head (deterministic, no LLM) into ConfigChanges,
  2. runs the shared guard (whygraph/integrations/guard.py), which records PR-[:WARNED_WITH]->Lesson,
  3. posts or updates ONE comment on the PR (found again by a hidden marker, so restarts never duplicate).
When a PR merges, each lesson it was warned with or cites ("L-1" in the body) is recorded as `applied` if the
final values pass the check, or `ignored` if they still trip it.
"""

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import yaml

from whygraph.config import get_settings
from whygraph.graph import client
from whygraph.graph.ids import node_id
from whygraph.integrations.guard import MEMORY_PENDING, Memory, check_change_risk, default_memory
from whygraph.integrations.ingest import CONFIG_FILE, is_agent
from whygraph.models.events import ChangeRiskRequest, ChangeRiskResponse, ConfigChange

log = logging.getLogger(__name__)

POLL_S = 10
MARKER = "<!-- why-graph-pr-guard -->"
LESSON_REF = re.compile(r"\b(?:lesson:)?(L-\d+)\b")
API = "https://api.github.com"


# --- services.yaml diff ---------------------------------------------------------------------


def _leaves(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _leaves(f"{prefix}.{k}" if prefix else str(k), v, out)
    else:
        out[prefix] = value


def config_diff(base_yaml: str, head_yaml: str) -> list[ConfigChange]:
    """Changed or added leaves under `services:` as ConfigChanges (service + dotted key). The `latency_ms`
    section is the simulator's workload, not service config, so it is ignored."""

    def flat(text: str) -> dict[tuple[str, str], Any]:
        services = (yaml.safe_load(text or "") or {}).get("services") or {}
        out: dict[tuple[str, str], Any] = {}
        for service, cfg in services.items():
            leaves: dict[str, Any] = {}
            _leaves("", cfg, leaves)
            out.update({(str(service), key): v for key, v in leaves.items()})
        return out

    base, head = flat(base_yaml), flat(head_yaml)
    return [
        ConfigChange(service=service, key=key, old=base.get((service, key)), new=new)
        for (service, key), new in sorted(head.items())
        if base.get((service, key)) != new and isinstance(new, (int, float, str))
    ]


def cited_lessons(text: str | None) -> list[str]:
    return [f"lesson:{m}" for m in dict.fromkeys(LESSON_REF.findall(text or ""))]


# --- comment --------------------------------------------------------------------------------


def render_comment(res: ChangeRiskResponse, changes: list[ConfigChange], cited: list[str]) -> str:
    lines = [MARKER]
    if res.warnings:
        lines += [f"### ⚠️ Why-Graph PR Guard: {res.risk} risk", ""]
        lines += ["| Change | Proposed | Safe minimum | Lesson | Learned from |", "|---|---|---|---|---|"]
        for w in res.warnings:
            safe = f"≥ {math.ceil(w.safe_min)}" if w.safe_min is not None else "n/a"
            lesson = (w.lesson_id or "").removeprefix("lesson:") or "detector only"
            incident = (w.incident_id or "").removeprefix("inc:") or "n/a"
            lines.append(f"| `{w.service}.{w.key}` | {w.proposed} | {safe} | {lesson} | {incident} |")
        lines += ["", f"**Advice:** {res.advice}"]
        if any(w.lesson_text for w in res.warnings):
            lines += [""] + [f"> {w.lesson_text}" for w in res.warnings if w.lesson_text]
    elif cited:
        names = ", ".join(c.removeprefix("lesson:") for c in cited)
        lines += [f"### ✅ Why-Graph PR Guard: lesson {names} applied", "", "No known risk in this change."]
    else:
        lines += ["### ✅ Why-Graph PR Guard: no known risk", ""]
        lines.append(MEMORY_PENDING if res.advice == MEMORY_PENDING else "No lesson or detector matches.")
    changed = ", ".join(f"`{c.service}.{c.key}` {c.old} → {c.new}" for c in changes)
    lines += ["", f"<sub>Checked {changed} against the incident graph.</sub>"]
    return "\n".join(lines)


# --- ports (GitHub API + graph store), so the guard loop is testable offline ---------------


class GitHub(Protocol):
    def recent_pulls(self) -> list[dict]: ...
    def merge_base_and_files(self, base_ref: str, head_sha: str) -> tuple[str, list[str]]: ...
    def file_at(self, path: str, ref: str) -> str: ...
    def upsert_comment(self, number: int, body: str) -> None: ...


class GitHubAPI:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.http = httpx.Client(
            base_url=API,
            timeout=15,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _get(self, path: str, **kw) -> httpx.Response:
        r = self.http.get(f"/repos/{self.repo}{path}", **kw)
        r.raise_for_status()
        return r

    def recent_pulls(self) -> list[dict]:
        return self._get(
            "/pulls", params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 20}
        ).json()

    def merge_base_and_files(self, base_ref: str, head_sha: str) -> tuple[str, list[str]]:
        data = self._get(f"/compare/{base_ref}...{head_sha}").json()
        return data["merge_base_commit"]["sha"], [f["filename"] for f in data.get("files", [])]

    def file_at(self, path: str, ref: str) -> str:
        r = self.http.get(
            f"/repos/{self.repo}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        return r.text

    def upsert_comment(self, number: int, body: str) -> None:
        comments = self._get(f"/issues/{number}/comments", params={"per_page": 100}).json()
        mine = next((c for c in comments if MARKER in (c.get("body") or "")), None)
        if mine:
            r = self.http.patch(f"/repos/{self.repo}/issues/comments/{mine['id']}", json={"body": body})
        else:
            r = self.http.post(f"/repos/{self.repo}/issues/{number}/comments", json={"body": body})
        r.raise_for_status()


class GraphStore:
    """The PR facts PR Guard writes and reads back."""

    def __init__(self, graph: str | None = None) -> None:
        self.graph = graph

    def record_pr(self, pr: dict) -> None:
        author = (pr.get("user") or {}).get("login") or "unknown"
        client.run(
            "MERGE (p:PR {id: $id}) SET p.number = $number, p.name = $name, p.title = $title, p.url = $url, "
            "p.state = $state, p.opened_at = $opened "
            "MERGE (e:Engineer {id: $eng}) "
            "ON CREATE SET e.handle = $author, e.name = $author, e.kind = $kind "
            "MERGE (p)-[:OPENED_BY]->(e)",
            {
                "id": node_id("PR", pr["number"]),
                "number": pr["number"],
                "name": f"#{pr['number']} {pr.get('title') or ''}".strip(),
                "title": pr.get("title") or "",
                "url": pr.get("html_url") or "",
                "state": "merged" if pr.get("merged_at") else pr.get("state", "open"),
                "opened": pr.get("created_at") or "",
                "eng": node_id("Engineer", author),
                "author": author,
                "kind": "agent" if is_agent(author) else "human",
            },
            graph=self.graph,
            read_only=False,
        )

    def warned_lessons(self, number: int) -> list[str]:
        out = client.run(
            "MATCH (:PR {id: $id})-[:WARNED_WITH]->(l:Lesson) RETURN l.id AS id",
            {"id": node_id("PR", number)},
            graph=self.graph,
        )
        return [r["id"] for r in out.rows]


# --- the guard loop -------------------------------------------------------------------------


@dataclass
class PRGuard:
    gh: GitHub
    store: GraphStore
    memory: Memory = field(default_factory=default_memory)
    graph: str | None = None
    checked: dict[int, str] = field(default_factory=dict)  # PR number -> head sha already checked
    closed: set[int] = field(default_factory=set)  # merged PRs whose outcomes are recorded

    def _changes(self, pr: dict) -> list[ConfigChange] | None:
        base, files = self.gh.merge_base_and_files(pr["base"]["ref"], pr["head"]["sha"])
        if CONFIG_FILE not in files:
            return None
        return config_diff(
            self.gh.file_at(CONFIG_FILE, base), self.gh.file_at(CONFIG_FILE, pr["head"]["sha"])
        )

    def check(self, pr: dict) -> ChangeRiskResponse | None:
        changes = self._changes(pr)
        if not changes:
            return None
        self.store.record_pr(pr)
        req = ChangeRiskRequest(
            changes=changes,
            title=pr.get("title"),
            diff=None,
            author=(pr.get("user") or {}).get("login"),
            pr_number=pr["number"],
        )
        res = check_change_risk(req, graph=self.graph, memory=self.memory)
        self.gh.upsert_comment(pr["number"], render_comment(res, changes, cited_lessons(pr.get("body"))))
        return res

    def settle(self, pr: dict) -> dict[str, str]:
        """On merge: applied if the final values pass, ignored if a lesson still fires."""
        changes = self._changes(pr) or []
        self.store.record_pr(pr)
        still = {w.lesson_id for w in self.memory.check_changes(changes, self.graph) if w.lesson_id}
        lessons = dict.fromkeys(self.store.warned_lessons(pr["number"]) + cited_lessons(pr.get("body")))
        outcomes = {lesson: ("ignored" if lesson in still else "applied") for lesson in lessons}
        for lesson in still - set(outcomes):
            outcomes[lesson] = "ignored"  # merged with a warning nobody had seen before
        for lesson, outcome in outcomes.items():
            self.memory.record_guard_outcome(pr["number"], lesson, outcome, self.graph)
        return outcomes

    def tick(self) -> None:
        for pr in self.gh.recent_pulls():
            number = pr["number"]
            try:
                if pr.get("merged_at"):
                    if number not in self.closed:
                        self.settle(pr)
                        self.closed.add(number)
                elif pr.get("state") == "open" and self.checked.get(number) != pr["head"]["sha"]:
                    self.check(pr)
                    self.checked[number] = pr["head"]["sha"]
            except Exception:
                log.exception("PR Guard: PR #%s failed; will retry next poll", number)


async def run_forever(stop: asyncio.Event) -> None:
    s = get_settings()
    if not (s.github_token and s.github_repo):
        log.info("PR Guard off: set GITHUB_TOKEN and GITHUB_REPO to enable it")
        return
    guard = PRGuard(GitHubAPI(s.github_repo, s.github_token), GraphStore())
    # PRs already merged at startup were settled by an earlier run (or predate the demo): don't replay them.
    try:
        guard.closed = {
            p["number"] for p in await asyncio.to_thread(guard.gh.recent_pulls) if p.get("merged_at")
        }
    except Exception:
        log.exception("PR Guard: could not list PRs")
    log.info("PR Guard watching %s every %ss", s.github_repo, POLL_S)
    while not stop.is_set():
        await asyncio.to_thread(guard.tick)
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_S)
        except TimeoutError:
            pass
