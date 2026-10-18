"""astro-shop simulator: the deployer and watcher for the live demo, with no shop to run.

It watches `main` of the astro-shop repo. On every merge it:
  1. sends Why-Graph a real deploy: the merge sha, PR number, author and the real `config/services.yaml` diff;
  2. recomputes the shop from that config: each service's p99 is its own simulated latency plus its sync
     dependencies', and a call whose timeout is below the callee's p99 now fails;
  3. keeps posting per-edge telemetry, and after --alert-after seconds of failure posts error-rate alerts
     for the failing caller and the services that call it.

Everything Why-Graph receives is real except the traffic itself. Usage (with the API running):

    uv run python scenarios/astro_sim.py                      # watches redwing-381/astro-shop
    uv run python scenarios/astro_sim.py --api https://...    # or a remote Why-Graph
"""

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from whygraph.config import REPO_ROOT
from whygraph.integrations.github import config_diff

CONFIG = "config/services.yaml"
Z99 = 2.33  # p99 of a normal distribution, in standard deviations


@dataclass
class Shop:
    timeouts: dict[str, dict[str, float]]  # caller -> callee -> timeout ms
    latency: dict[str, tuple[float, float]]  # service -> (mean, sd) of its own work
    p99: dict[str, float] = field(default_factory=dict)  # service -> end-to-end p99 (own + sync deps)

    @classmethod
    def from_yaml(cls, text: str) -> "Shop":
        doc = yaml.safe_load(text or "") or {}
        timeouts = {
            svc: {callee: float(t) for callee, t in ((cfg or {}).get("timeouts_ms") or {}).items()}
            for svc, cfg in (doc.get("services") or {}).items()
        }
        latency = {svc: (float(m), float(sd)) for svc, (m, sd) in (doc.get("latency_ms") or {}).items()}
        shop = cls(timeouts, latency)
        for svc in set(latency) | set(timeouts):
            shop._e2e(svc, ())
        return shop

    def _e2e(self, svc: str, seen: tuple[str, ...]) -> float:
        if svc in self.p99:
            return self.p99[svc]
        mean, sd = self.latency.get(svc, (10.0, 3.0))
        deps = [] if svc in seen else self.timeouts.get(svc, {})
        total = mean + Z99 * sd + sum(self._e2e(d, (*seen, svc)) for d in deps)
        self.p99[svc] = round(total, 1)
        return self.p99[svc]

    def edges(self) -> list[dict]:
        """Telemetry for every call edge: the callee's p99 and the caller's error rate on that edge."""
        out = []
        for caller, deps in self.timeouts.items():
            for callee, timeout in deps.items():
                out.append(
                    {
                        "caller": caller,
                        "callee": callee,
                        "p99_ms": self.p99.get(callee, 0.0),
                        "error_rate": self.error_rate(timeout, callee),
                    }
                )
        return out

    def error_rate(self, timeout: float, callee: str) -> float:
        mean, _ = self.latency.get(callee, (10.0, 3.0))
        p99 = self.p99.get(callee, mean)
        if timeout < mean:
            return 0.62  # most calls time out
        if timeout < p99:
            return 0.24  # the slow tail times out
        return 0.0

    def failing(self) -> dict[str, float]:
        """Callers with a call that now fails, and the error rate they show."""
        bad: dict[str, float] = {}
        for caller, deps in self.timeouts.items():
            for callee, timeout in deps.items():
                rate = self.error_rate(timeout, callee)
                if rate:
                    bad[caller] = max(bad.get(caller, 0.0), rate)
        return bad

    def callers_of(self, svc: str) -> list[str]:
        return sorted(c for c, deps in self.timeouts.items() if svc in deps)


def alerts_for(shop: Shop, ts: int, tag: str) -> list[dict]:
    """The failing callers first (the root), then their callers, which fail from propagation."""
    out, seen = [], set()
    for svc, rate in sorted(shop.failing().items(), key=lambda kv: -kv[1]):
        out.append({"id": f"{tag}-{svc}", "service": svc, "value": rate})
        seen.add(svc)
    for svc, rate in list(shop.failing().items()):
        for up in shop.callers_of(svc):
            if up not in seen:
                out.append({"id": f"{tag}-{up}", "service": up, "value": round(rate * 0.66, 2)})
                seen.add(up)
    return [
        {
            **a,
            "signal": "error_rate",
            "threshold": 0.10,
            "severity": "sev2",
            "ts": ts + i * 4000,
            "source": "astro-sim",
        }
        for i, a in enumerate(out)
    ]


# --- git + GitHub ---------------------------------------------------------------------------


def git(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_dir, check=True, capture_output=True, text=True
    ).stdout.strip()


def file_at(repo_dir: Path, sha: str) -> str:
    try:
        return git(repo_dir, "show", f"{sha}:{CONFIG}")
    except subprocess.CalledProcessError:
        return ""


def merge_meta(repo: str, repo_dir: Path, sha: str, token: str | None) -> dict:
    """PR number, PR author and title for a merge commit (GitHub API), falling back to the commit itself."""
    subject, author = git(repo_dir, "log", "-1", "--format=%s%x00%an", sha).split("\0")
    pr = re.search(r"\(#(\d+)\)|Merge pull request #(\d+)", subject)
    meta = {
        "message": subject,
        "author": author,
        "pr_number": int(next(g for g in pr.groups() if g)) if pr else None,
    }
    headers = {
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    }
    for _ in range(4):  # GitHub links a fresh merge commit to its PR a few seconds after the merge
        try:
            r = httpx.get(
                f"https://api.github.com/repos/{repo}/commits/{sha}/pulls", headers=headers, timeout=10
            )
            if r.status_code == 200 and r.json():
                p = r.json()[0]
                meta.update(pr_number=p["number"], author=p["user"]["login"], message=p["title"])
                break
        except httpx.HTTPError:
            pass
        time.sleep(3)
    return meta


# --- the loop -------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--repo", default="redwing-381/astro-shop")
    ap.add_argument("--dir", default=str(REPO_ROOT / "data" / "astro-shop"))
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between git fetches")
    ap.add_argument("--alert-after", type=float, default=20.0, help="seconds of failure before alerting")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or None
    repo_dir = Path(args.dir)
    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", f"https://github.com/{args.repo}.git", str(repo_dir)], check=True
        )
    git(repo_dir, "fetch", "-q", "origin", "main")
    deployed = git(repo_dir, "rev-parse", "origin/main")
    shop = Shop.from_yaml(file_at(repo_dir, deployed))
    broken_since: float | None = time.time() if shop.failing() else None
    alerted = False
    http = httpx.Client(base_url=args.api, timeout=15)
    print(f"watching {args.repo} at {deployed[:7]} -> {args.api}", flush=True)

    last_telemetry = 0.0
    while True:
        now = time.time()
        try:
            git(repo_dir, "fetch", "-q", "origin", "main")
            head = git(repo_dir, "rev-parse", "origin/main")
            if head != deployed:
                changes = config_diff(file_at(repo_dir, deployed), file_at(repo_dir, head))
                meta = merge_meta(args.repo, repo_dir, head, token)
                shop = Shop.from_yaml(file_at(repo_dir, head))
                body = {
                    "sha": head,
                    "repo": args.repo,
                    "services": sorted({c.service for c in changes}) or ["frontend"],
                    "ts": int(now * 1000),
                    **meta,
                    "config_changes": [c.model_dump() for c in changes],
                }
                r = http.post("/api/deploys", json=body)
                print(
                    f"deploy {head[:7]} PR #{meta['pr_number']} by {meta['author']}: "
                    f"{[f'{c.service}.{c.key} {c.old}->{c.new}' for c in changes]} -> {r.status_code}",
                    flush=True,
                )
                deployed = head
                failing = shop.failing()
                broken_since, alerted = (now, False) if failing else (None, False)
                print(f"  {'FAILING: ' + str(failing) if failing else 'healthy'}", flush=True)
                last_telemetry = 0.0
            if now - last_telemetry >= 10:
                http.post("/api/telemetry", json={"ts": int(now * 1000), "edges": shop.edges()})
                last_telemetry = now
            if broken_since and not alerted and now - broken_since >= args.alert_after:
                for alert in alerts_for(shop, int(now * 1000), f"sim-{deployed[:7]}"):
                    r = http.post("/api/alerts", json=alert)
                    print(f"  alert {alert['service']} {alert['value']:.0%} -> {r.json()}", flush=True)
                alerted = True
        except (subprocess.CalledProcessError, httpx.HTTPError) as e:
            print(f"  (retrying: {e})", file=sys.stderr, flush=True)
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
