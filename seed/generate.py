"""Deterministic synthetic company for Why-Graph (F-A1).

    uv run python -m seed.generate        # rewrites seed/data/{core,act1,history}.json

Everything is template-generated from `random.Random(42)` (no LLM-written text), so every run writes
byte-identical files. `seed/load.py` loads them into FalkorDB.

    core.json     the 9 OTel-demo services + the orders topic and its consumers, the services.yaml ConfigKeys,
                  6 teams, 20 engineers and our agent engineers
    act1.json     the Act 1 slice: PR #12 by coder-bot, commit 9f2c1ab, deploy d-311, alerts a-901/a-902,
                  incident INC-1031, plus two decoy deploys in the suspect window
    history.json  19 more services, 30 days of commits/PRs/deploys, 20 resolved incidents over 6 patterns
                  (deliberately no timeout pattern), their lessons, decoy detectors, decisions, runbooks, chat
"""

import json
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whygraph.graph import ids
from whygraph.memory.templates import TEMPLATES

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED = 42

# --- time ----------------------------------------------------------------------------------------

T0 = 1_792_297_800_000  # a-901 fires: Sun 18 Oct 2026, 10:00 IST (same instant as the replay fixture)
MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR
IST_MIDNIGHT = T0 - 10 * HOUR  # 00:00 IST on demo day
HISTORY_END = T0 - 45 * MIN  # nothing in the history lands inside Act 1's 30-minute suspect window

# --- shared demo constants (docs/work-split.md §2) -------------------------------------------------

SDE_BOT = "coder-bot"  # our SDE agent's GitHub login; change here if the bot account uses another name
INCIDENT = "INC-1031"
ACT1_SHA = "9f2c1ab"
ACT1_PR = 12
ACT1_DEPLOY = "d-311"

# name: (tier, lang, owning team)
CORE_SERVICES: dict[str, tuple[str, str, str]] = {
    "frontend": ("edge", "typescript", "checkout"),
    "checkout": ("core", "go", "payments"),
    "payment": ("core", "javascript", "payments"),
    "cart": ("core", "csharp", "checkout"),
    "currency": ("core", "cpp", "checkout"),
    "product-catalog": ("core", "go", "catalog"),
    "recommendation": ("core", "python", "catalog"),
    "shipping": ("core", "rust", "checkout"),
    "quote": ("core", "php", "checkout"),
    "accounting": ("core", "dotnet", "data"),
    "fraud-detection": ("core", "kotlin", "payments"),
}
SYNTHETIC_SERVICES: dict[str, tuple[str, str, str]] = {
    "auth": ("core", "go", "platform"),
    "sessions": ("core", "go", "platform"),
    "search": ("core", "java", "catalog"),
    "inventory": ("core", "java", "data"),
    "user-profile": ("core", "go", "growth"),
    "ads": ("core", "java", "growth"),
    "email": ("core", "ruby", "growth"),
    "notifications": ("core", "python", "growth"),
    "reviews": ("core", "python", "catalog"),
    "image-resizer": ("edge", "rust", "catalog"),
    "feature-flags": ("core", "go", "platform"),
    "tax": ("core", "go", "payments"),
    "loyalty": ("core", "kotlin", "growth"),
    "analytics": ("data", "python", "data"),
    "orders-db": ("data", "postgres", "platform"),
    "catalog-db": ("data", "postgres", "platform"),
    "inventory-db": ("data", "postgres", "platform"),
    "ledger-db": ("data", "postgres", "data"),
    "cache": ("data", "redis", "platform"),
}
ALL_SERVICES = {**CORE_SERVICES, **SYNTHETIC_SERVICES}

CORE_CALLS = {
    "frontend": ["cart", "currency", "checkout", "shipping", "product-catalog", "recommendation"],
    "checkout": ["cart", "currency", "payment", "product-catalog", "shipping"],
    "shipping": ["quote"],
    "recommendation": ["product-catalog"],
}
SYNTHETIC_CALLS = {
    "frontend": [
        "auth",
        "search",
        "ads",
        "user-profile",
        "reviews",
        "image-resizer",
        "feature-flags",
        "loyalty",
    ],
    "auth": ["sessions", "cache"],
    "sessions": ["cache"],
    "search": ["catalog-db", "cache", "inventory"],
    "inventory": ["inventory-db"],
    "user-profile": ["orders-db", "cache"],
    "ads": ["user-profile"],
    "reviews": ["catalog-db", "cache"],
    "notifications": ["email", "user-profile"],
    "loyalty": ["orders-db"],
    "accounting": ["ledger-db", "tax"],
    "fraud-detection": ["orders-db"],
    "product-catalog": ["catalog-db", "cache"],
    "cart": ["cache"],
}
# callee-side p99 (ms); every CALLS edge into a service carries that service's p99
P99 = {
    "payment": 450,
    "quote": 300,
    "product-catalog": 150,
    "cart": 25,
    "currency": 17,
    "shipping": 340,
    "recommendation": 200,
    "checkout": 480,
    "auth": 40,
    "sessions": 12,
    "search": 180,
    "inventory": 120,
    "user-profile": 60,
    "ads": 90,
    "email": 250,
    "reviews": 70,
    "image-resizer": 160,
    "feature-flags": 8,
    "tax": 45,
    "loyalty": 50,
    "orders-db": 30,
    "catalog-db": 25,
    "inventory-db": 20,
    "ledger-db": 35,
    "cache": 3,
}
CORE_TOPICS = {"orders": ("checkout", ["accounting", "fraud-detection"])}
SYNTHETIC_TOPICS = {
    "inventory-events": ("inventory", ["search", "analytics"]),
    "user-events": ("user-profile", ["notifications", "analytics"]),
}

# the canonical astro-mini/config/services.yaml timeouts (work-split §2)
SERVICES_YAML = {
    "frontend": {
        "cart": 300,
        "currency": 300,
        "checkout": 2500,
        "shipping": 1500,
        "product-catalog": 500,
        "recommendation": 1000,
    },
    "checkout": {"cart": 300, "currency": 300, "payment": 800, "product-catalog": 500, "shipping": 1500},
    "shipping": {"quote": 600},
    "recommendation": {"product-catalog": 400},
}
# graph-only keys of the synthetic services: (service, key) -> current value. Keys that a "safe" history
# change touches start from that change's old value (HistoryGen.safe_config_changes).
SYNTHETIC_CONFIG: dict[tuple[str, str], Any] = {
    ("search", "timeouts_ms.inventory"): 400,
    ("search", "timeouts_ms.catalog-db"): 150,
    ("ads", "timeouts_ms.user-profile"): 200,
    ("notifications", "timeouts_ms.email"): 1000,
    ("auth", "timeouts_ms.sessions"): 100,
    ("reviews", "timeouts_ms.catalog-db"): 150,
    ("user-profile", "timeouts_ms.orders-db"): 200,
    ("search", "retries.inventory"): 1,
    ("ads", "retries.user-profile"): 1,
    ("notifications", "retries.email"): 2,
    ("auth", "retries.sessions"): 1,
    ("search", "retries.catalog-db"): 3,
    ("user-profile", "retries.orders-db"): 2,
    ("inventory", "pool.inventory-db"): 40,
    ("user-profile", "pool.orders-db"): 25,
    ("accounting", "pool.ledger-db"): 20,
    ("fraud-detection", "pool.orders-db"): 16,
    ("reviews", "pool.catalog-db"): 10,
    ("loyalty", "pool.orders-db"): 8,
    ("search", "flags.cache_enabled"): True,
    ("reviews", "flags.cache_enabled"): True,
    ("user-profile", "flags.new_profile_api"): False,
    ("ads", "flags.personalization"): True,
    ("notifications", "flags.batch_send"): False,
    ("reviews", "flags.show_photos"): True,
}
PEAK_CONCURRENCY = {
    "inventory": 30,
    "user-profile": 20,
    "accounting": 16,
    "fraud-detection": 12,
    "reviews": 8,
    "loyalty": 6,
}
KEY_KIND = {"timeouts_ms": "timeout", "retries": "retries", "pool": "pool", "flags": "flag"}

TEAMS = {
    "payments": "Payments",
    "checkout": "Checkout",
    "catalog": "Catalog",
    "platform": "Platform",
    "data": "Data",
    "growth": "Growth",
}
# handle, full name, team, on call
ENGINEERS = [
    ("priya", "Priya Raman", "payments", True),
    ("arjun", "Arjun Mehta", "payments", False),
    ("meera", "Meera Iyer", "payments", False),
    ("karthik", "Karthik Subramanian", "checkout", True),
    ("divya", "Divya Nair", "checkout", False),
    ("rahul", "Rahul Verma", "checkout", False),
    ("sneha", "Sneha Kulkarni", "checkout", False),
    ("vikram", "Vikram Rao", "catalog", True),
    ("ananya", "Ananya Das", "catalog", False),
    ("rohan", "Rohan Gupta", "catalog", False),
    ("lakshmi", "Lakshmi Krishnan", "platform", True),
    ("siddharth", "Siddharth Jain", "platform", False),
    ("kavya", "Kavya Reddy", "platform", False),
    ("aditya", "Aditya Bose", "platform", False),
    ("nisha", "Nisha Pillai", "data", True),
    ("farhan", "Farhan Sheikh", "data", False),
    ("deepa", "Deepa Menon", "data", False),
    ("tom", "Tom Becker", "growth", True),
    ("maria", "Maria Lopez", "growth", False),
    ("li", "Li Wei", "growth", False),
]
AGENTS = [(SDE_BOT, "coder-bot (SDE agent)"), ("deps-bot", "deps-bot (dependency agent)")]

LANG_FILES = {
    "go": ["main.go", "handler.go", "client.go", "go.mod"],
    "python": ["app.py", "handlers.py", "models.py", "requirements.txt"],
    "java": ["src/main/java/App.java", "src/main/java/Handler.java", "src/main/java/Repo.java", "pom.xml"],
    "kotlin": ["src/main/kotlin/App.kt", "src/main/kotlin/Consumer.kt", "build.gradle.kts"],
    "typescript": ["src/app.tsx", "src/pages/checkout.tsx", "src/api.ts", "package.json"],
    "javascript": ["index.js", "charge.js", "package.json"],
    "csharp": ["CartService.cs", "CartStore.cs", "cart.csproj"],
    "cpp": ["server.cpp", "convert.cpp", "CMakeLists.txt"],
    "rust": ["src/main.rs", "src/handlers.rs", "Cargo.toml"],
    "php": ["app/routes.php", "app/Quote.php", "composer.json"],
    "dotnet": ["Consumer.cs", "Ledger.cs", "accounting.csproj"],
    "ruby": ["email_server.rb", "templates.rb", "Gemfile"],
    "postgres": ["migrations/0042_indexes.sql", "postgresql.conf"],
    "redis": ["redis.conf"],
}
DEP_FILES = {
    "go.mod",
    "requirements.txt",
    "pom.xml",
    "package.json",
    "Cargo.toml",
    "composer.json",
    "Gemfile",
    "build.gradle.kts",
    "cart.csproj",
    "accounting.csproj",
    "CMakeLists.txt",
}
CONFIG_FILE = "config/services.yaml"


def key_kind(key: str) -> str:
    return KEY_KIND[key.split(".", 1)[0]]


def key_target(key: str) -> str | None:
    """The callee a key is about (timeouts/retries/pools), or None for flags."""
    prefix, _, rest = key.partition(".")
    return None if prefix == "flags" else rest


def file_id(service: str, path: str) -> str:
    return ids.node_id("File", path if service == "" else f"services/{service}/{path}")


def ist(ts: int) -> str:
    """'14:05' in IST, for chat lines and summaries."""
    m = ((ts // MIN) + 330) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


# --- graph builder ---------------------------------------------------------------------------------


class Graph:
    """Collects nodes (by label, keyed on stable id) and relationships, and dumps them as JSON."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.rels: dict[tuple[str, str, str], dict[str, Any]] = {}

    def node(self, label: str, id_: str, **props: Any) -> str:
        assert id_.startswith(ids.PREFIX[label] + ":"), (label, id_)
        clean = {k: v for k, v in props.items() if v is not None}
        self.nodes.setdefault(label, {}).setdefault(id_, {}).update(clean)
        return id_

    def rel(self, src: str, type_: str, dst: str, **props: Any) -> None:
        clean = {k: v for k, v in props.items() if v is not None}
        self.rels.setdefault((src, type_, dst), {}).update(clean)

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": {label: [{"id": i, **p} for i, p in rows.items()] for label, rows in self.nodes.items()},
            "rels": [{"type": t, "src": s, "dst": d, "props": p} for (s, t, d), p in self.rels.items()],
        }


def add_services(g: Graph, services: dict[str, tuple[str, str, str]]) -> None:
    for name, (tier, lang, team) in services.items():
        g.node(
            "Service",
            ids.svc(name),
            name=name,
            tier=tier,
            lang=lang,
            peak_concurrency=PEAK_CONCURRENCY.get(name),
        )
        g.rel(ids.node_id("Team", team), "OWNS", ids.svc(name))


def add_calls(g: Graph, calls: dict[str, list[str]], updated_at: int) -> None:
    for caller, callees in calls.items():
        for callee in callees:
            g.rel(
                ids.svc(caller),
                "CALLS",
                ids.svc(callee),
                p99_ms=P99[callee],
                error_rate=0.002,
                updated_at=updated_at,
            )


def add_topics(g: Graph, topics: dict[str, tuple[str, list[str]]]) -> None:
    for topic, (producer, consumers) in topics.items():
        tid = g.node("Topic", ids.node_id("Topic", topic), name=topic)
        g.rel(ids.svc(producer), "PUBLISHES", tid)
        for c in consumers:
            g.rel(ids.svc(c), "CONSUMES", tid)


def add_config_key(g: Graph, service: str, key: str, value: Any) -> str:
    cid = g.node(
        "ConfigKey",
        ids.cfg(service, key),
        name=f"{service} {key}",
        service=service,
        key=key,
        kind=key_kind(key),
        value=value,
    )
    g.rel(cid, "CONFIGURES", ids.svc(service))
    if target := key_target(key):
        g.rel(cid, "TARGETS", ids.svc(target))
    return cid


# --- core.json ---------------------------------------------------------------------------------------


def build_core() -> Graph:
    g = Graph()
    for slug, name in TEAMS.items():
        g.node("Team", ids.node_id("Team", slug), name=name)
    for handle, name, team, on_call in ENGINEERS:
        eid = g.node(
            "Engineer",
            ids.node_id("Engineer", handle),
            name=name,
            handle=handle,
            kind="human",
            on_call=on_call,
        )
        g.rel(eid, "MEMBER_OF", ids.node_id("Team", team))
    for handle, name in AGENTS:
        g.node(
            "Engineer", ids.node_id("Engineer", handle), name=name, handle=handle, kind="agent", on_call=False
        )
    add_services(g, CORE_SERVICES)
    add_calls(g, CORE_CALLS, updated_at=T0 - 10 * MIN)
    add_topics(g, CORE_TOPICS)
    g.node("File", file_id("", CONFIG_FILE), name=CONFIG_FILE, path=CONFIG_FILE)
    for service, timeouts in SERVICES_YAML.items():
        for callee, ms in timeouts.items():
            add_config_key(g, service, f"timeouts_ms.{callee}", ms)
    return g


# --- history.json ------------------------------------------------------------------------------------


@dataclass
class Commit:
    service: str
    author: str
    ts: int
    message: str
    files: list[str]  # file ids
    changes: list[tuple[str, str, Any]] = field(default_factory=list)  # (service, key, new value)
    sha: str = ""


@dataclass
class PR:
    title: str
    commits: list[Commit]
    opened_at: int
    merged_at: int
    number: int = 0


@dataclass
class Deploy:
    service: str
    ts: int
    commits: list[Commit]
    id: str = ""


@dataclass
class Incident:
    scenario: dict[str, Any]
    started_at: int
    resolved_at: int
    num: int = 0
    cause: Commit | None = None
    cause_pr: PR | None = None
    fix: Commit | None = None
    fix_pr: PR | None = None
    resolver: str = ""
    features: list[str] = field(default_factory=list)
    old_value: Any = None

    @property
    def id(self) -> str:
        return f"INC-{self.num}"

    @property
    def pattern(self) -> str:
        return self.scenario["pattern"]


# 20 past incidents over 6 patterns. Deliberately NO timeout pattern: Act 1 must be genuinely new.
SCENARIOS: list[dict[str, Any]] = [
    # db_pool_exhaustion: pool shrunk below peak concurrency -> slow service, 5xx upstream
    {
        "pattern": "db_pool_exhaustion",
        "change": ("inventory", "pool.inventory-db", 15),
        "gap": 6,
        "alerts": [("inventory", "latency_p99", 2400, 800), ("search", "error_rate", 0.34, 0.1)],
    },
    {
        "pattern": "db_pool_exhaustion",
        "change": ("user-profile", "pool.orders-db", 10),
        "gap": 24,
        "alerts": [
            ("user-profile", "latency_p99", 1900, 500),
            ("ads", "error_rate", 0.22, 0.1),
            ("frontend", "error_rate", 0.12, 0.1),
        ],
    },
    {
        "pattern": "db_pool_exhaustion",
        "change": ("accounting", "pool.ledger-db", 8),
        "gap": 14,
        "alerts": [("accounting", "latency_p99", 3100, 1000)],
    },
    {
        "pattern": "db_pool_exhaustion",
        "change": ("fraud-detection", "pool.orders-db", 6),
        "gap": 8,
        "alerts": [("fraud-detection", "latency_p99", 2700, 900)],
    },
    # retry_storm: retries raised, a slow callee gets hammered
    {
        "pattern": "retry_storm",
        "change": ("search", "retries.inventory", 5),
        "gap": 18,
        "alerts": [
            ("inventory", "latency_p99", 1600, 500),
            ("search", "error_rate", 0.41, 0.1),
            ("frontend", "error_rate", 0.17, 0.1),
        ],
    },
    {
        "pattern": "retry_storm",
        "change": ("ads", "retries.user-profile", 5),
        "gap": 9,
        "alerts": [("user-profile", "latency_p99", 900, 300), ("ads", "error_rate", 0.29, 0.1)],
    },
    {
        "pattern": "retry_storm",
        "change": ("notifications", "retries.email", 6),
        "gap": 26,
        "alerts": [("email", "latency_p99", 4200, 1500), ("notifications", "error_rate", 0.52, 0.1)],
    },
    {
        "pattern": "retry_storm",
        "change": ("auth", "retries.sessions", 4),
        "gap": 7,
        "alerts": [
            ("sessions", "latency_p99", 650, 100),
            ("auth", "error_rate", 0.38, 0.1),
            ("frontend", "error_rate", 0.21, 0.1),
        ],
    },
    # cert_expiry: nothing changed; the caller fails TLS handshakes against a healthy callee
    {
        "pattern": "cert_expiry",
        "caller": "auth",
        "callee": "sessions",
        "alerts": [("auth", "error_rate", 0.97, 0.1), ("frontend", "error_rate", 0.44, 0.1)],
    },
    {
        "pattern": "cert_expiry",
        "caller": "frontend",
        "callee": "image-resizer",
        "alerts": [("frontend", "error_rate", 0.13, 0.1)],
    },
    {
        "pattern": "cert_expiry",
        "caller": "reviews",
        "callee": "catalog-db",
        "alerts": [("reviews", "error_rate", 1.0, 0.1)],
    },
    # bad_dependency_bump: a library upgrade breaks the service itself
    {
        "pattern": "bad_dependency_bump",
        "service": "search",
        "lib": ("elasticsearch-java", "8.13.4", "9.0.1"),
        "gap": 5,
        "breakage": "the 9.x client rejects our index mapping so every query 500s",
        "alerts": [("search", "error_rate", 0.88, 0.1), ("frontend", "error_rate", 0.19, 0.1)],
    },
    {
        "pattern": "bad_dependency_bump",
        "service": "user-profile",
        "lib": ("google.golang.org/protobuf", "v1.33.0", "v1.34.0"),
        "gap": 8,
        "breakage": "unknown enum values now fail to unmarshal, profiles with the new tier field 500",
        "alerts": [("user-profile", "error_rate", 0.63, 0.1), ("ads", "error_rate", 0.31, 0.1)],
    },
    {
        "pattern": "bad_dependency_bump",
        "service": "auth",
        "lib": ("github.com/golang-jwt/jwt", "v4.5.0", "v5.2.1"),
        "gap": 4,
        "breakage": "v5 validates the nbf claim strictly and our mobile tokens have clock skew",
        "alerts": [("auth", "error_rate", 0.71, 0.1), ("frontend", "error_rate", 0.36, 0.1)],
    },
    # flag_misconfig: a flag flipped in prod
    {
        "pattern": "flag_misconfig",
        "change": ("search", "flags.cache_enabled", False),
        "gap": 12,
        "reason": "debugging stale results",
        "alerts": [
            ("catalog-db", "latency_p99", 410, 100),
            ("search", "latency_p99", 2300, 800),
            ("frontend", "error_rate", 0.15, 0.1),
        ],
    },
    {
        "pattern": "flag_misconfig",
        "change": ("reviews", "flags.cache_enabled", False),
        "gap": 5,
        "reason": "cache showing deleted reviews",
        "alerts": [("catalog-db", "latency_p99", 380, 100), ("reviews", "error_rate", 0.27, 0.1)],
    },
    {
        "pattern": "flag_misconfig",
        "change": ("user-profile", "flags.new_profile_api", True),
        "gap": 9,
        "reason": "rollout to 100%",
        "alerts": [("user-profile", "error_rate", 0.45, 0.1), ("ads", "error_rate", 0.18, 0.1)],
    },
    # kafka_lag: an async consumer falls behind (orders still flow, effects are delayed)
    {
        "pattern": "kafka_lag",
        "consumer": "accounting",
        "topic": "orders",
        "lag": 184_000,
        "alerts": [("accounting", "saturation", 184000, 10000), ("accounting", "latency_p99", 95000, 30000)],
    },
    {
        "pattern": "kafka_lag",
        "consumer": "analytics",
        "topic": "inventory-events",
        "lag": 520_000,
        "alerts": [("analytics", "saturation", 520000, 50000), ("analytics", "latency_p99", 240000, 60000)],
    },
    {
        "pattern": "kafka_lag",
        "consumer": "notifications",
        "topic": "user-events",
        "lag": 61_000,
        "gap": 15,
        "code_change": "switch consumer to manual batch commit",
        "alerts": [
            ("notifications", "saturation", 61000, 10000),
            ("notifications", "latency_p99", 48000, 15000),
        ],
    },
]

PATTERN_INFO = {
    "db_pool_exhaustion": "Connection pool smaller than the service's peak concurrency; requests queue for a "
    "connection, latency climbs and callers time out.",
    "retry_storm": "Aggressive retries against a slow dependency multiply its load until it falls over.",
    "cert_expiry": "An expired TLS certificate breaks handshakes; the callee is healthy but unreachable.",
    "bad_dependency_bump": "A library upgrade changes behaviour and breaks the service that shipped it.",
    "flag_misconfig": "A feature flag flipped in production changes load or behaviour in an unexpected way.",
    "kafka_lag": "A consumer group falls behind its topic; downstream effects (ledger, emails) are delayed.",
}
PATTERN_DETECTOR = {t.pattern: t for t in TEMPLATES.values() if t.pattern != "timeout_below_p99"}
DECISIONS = {
    "db_pool_exhaustion": (
        "db-pool-floor",
        "DB pools stay at or above peak concurrency",
        "Every service sizes its DB pool to at least its measured peak concurrency. Pool "
        "changes go through the platform team.",
    ),
    "retry_storm": (
        "retry-budget",
        "Max 2 retries with jittered backoff",
        "Sync calls retry at most twice, with exponential backoff and jitter. Anything more needs a "
        "retry budget on the callee side.",
    ),
    "cert_expiry": (
        "cert-expiry-alerting",
        "Alert 14 days before any cert expires",
        "All internal certs are issued by cert-manager with 30-day rotation and an expiry alert at 14 days.",
    ),
    "bad_dependency_bump": (
        "canary-dependency-bumps",
        "Major dependency bumps ship behind a canary",
        "Major-version bumps are canaried on 5% of traffic for 30 minutes before full rollout.",
    ),
    "flag_misconfig": (
        "cache-flags-are-config",
        "Cache flags are reviewed like config",
        "Flags that change load (caches, new code paths) need a load check and a second reviewer.",
    ),
    "kafka_lag": (
        "lag-based-autoscaling",
        "Consumers autoscale on partition lag",
        "Consumer groups scale on lag via KEDA; alert when lag > 10k messages for 5 minutes.",
    ),
}

FILLER_TEMPLATES = [
    "feat({s}): add {thing}",
    "fix({s}): handle empty {thing}",
    "fix({s}): nil check on {thing}",
    "refactor({s}): split {thing} handler",
    "chore({s}): bump log level for {thing}",
    "feat({s}): expose {thing} metric",
    "fix({s}): off by one in {thing} pagination",
    "perf({s}): cache {thing} lookups",
    "test({s}): cover {thing} edge cases",
    "{s}: address review comments",
    "{s}: wip {thing}",
    "fix({s}): recieve {thing} in the right order",
    "docs({s}): update README for {thing}",
]
THINGS = [
    "currency codes",
    "cart items",
    "promo codes",
    "order totals",
    "session ttl",
    "product images",
    "shipping zones",
    "tax rules",
    "retry metrics",
    "health check",
    "user prefs",
    "search facets",
    "email templates",
    "ledger entries",
    "inventory counts",
    "ad slots",
    "review scores",
]
DEP_BUMPS = {
    "go": ("github.com/prometheus/client_golang", "v1.19.1", "v1.20.0"),
    "python": ("httpx", "0.27.0", "0.27.2"),
    "java": ("jackson-databind", "2.17.1", "2.17.2"),
    "typescript": ("react-query", "5.45.0", "5.51.1"),
    "javascript": ("express", "4.19.2", "4.21.0"),
    "rust": ("tokio", "1.38.0", "1.39.2"),
    "kotlin": ("kotlinx-coroutines", "1.8.0", "1.8.1"),
    "ruby": ("rack", "3.0.11", "3.1.7"),
}


class HistoryGen:
    def __init__(self) -> None:
        self.rng = random.Random(SEED)
        self.commits: list[Commit] = []
        self.prs: list[PR] = []
        self.deploys: list[Deploy] = []
        self.incidents: list[Incident] = []
        self.members: dict[str, list[str]] = {}
        for handle, _, team, _ in ENGINEERS:
            self.members.setdefault(team, []).append(handle)
        self.on_call = {team: h for h, _, team, oc in ENGINEERS if oc}
        self.calls: dict[str, set[str]] = {}
        for calls in (CORE_CALLS, SYNTHETIC_CALLS):
            for caller, callees in calls.items():
                self.calls.setdefault(caller, set()).update(callees)
        self.consumers = {c for _, (_, cs) in {**CORE_TOPICS, **SYNTHETIC_TOPICS}.items() for c in cs}

    # -- helpers --

    def sha(self) -> str:
        return f"{self.rng.getrandbits(160):040x}"

    def at(self, day: float, hour: float) -> int:
        """Timestamp `int(day)` days before demo day at `hour` o'clock IST."""
        return IST_MIDNIGHT - int(day) * DAY + int(hour * HOUR)

    def work_time(self, lo_day: float = 0.6, hi_day: float = 30.0) -> int:
        while True:
            ts = self.at(self.rng.uniform(lo_day, hi_day), self.rng.uniform(9.5, 21.5))
            if ts < HISTORY_END and ts > T0 - 30 * DAY:
                return ts

    def team_of(self, service: str) -> str:
        return ALL_SERVICES[service][2]

    def author_for(self, service: str) -> str:
        r = self.rng.random()
        if r < 0.06:
            return SDE_BOT
        if r < 0.18:
            team = self.rng.choice(list(TEAMS))
        else:
            team = self.team_of(service)
        return self.rng.choice(self.members[team])

    def files(self, service: str, k: int, deps: bool = False) -> list[str]:
        names = LANG_FILES[ALL_SERVICES[service][1]]
        pool = [n for n in names if (n.split("/")[-1] in DEP_FILES) == deps] or names
        return [file_id(service, n) for n in self.rng.sample(pool, min(k, len(pool)))]

    def ship(self, service: str, ts: int, commits: list[Commit], title: str | None = None) -> Deploy:
        """One PR per commit group, merged a few minutes before the deploy."""
        merged = ts - self.rng.randint(2, 9) * MIN
        pr = PR(
            title=title or commits[0].message,
            commits=commits,
            opened_at=min(c.ts for c in commits) + 4 * MIN,
            merged_at=merged,
        )
        pr.opened_at = min(pr.opened_at, merged - MIN)
        self.prs.append(pr)
        self.commits.extend(commits)
        d = Deploy(service=service, ts=ts, commits=commits)
        self.deploys.append(d)
        return d

    def commit(
        self,
        service: str,
        author: str,
        ts: int,
        message: str,
        files: list[str],
        changes: list[tuple[str, str, Any]] | None = None,
    ) -> Commit:
        return Commit(
            service=service, author=author, ts=ts, message=message, files=files, changes=changes or []
        )

    # -- incidents --

    def root_of(self, alerting: list[str]) -> str:
        """Deepest alerting service: alerting, with nothing alerting reachable below it (Q0)."""
        for s in alerting:
            seen, todo, deeper = {s}, deque([s]), False
            while todo:
                cur = todo.popleft()
                for nxt in self.calls.get(cur, ()):
                    if nxt in alerting and nxt != s:
                        deeper = True
                    if nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            if not deeper:
                return s
        raise ValueError(alerting)

    def features(self, inc: Incident) -> list[str]:
        """Same rules as whygraph.graph.features.extract_features, applied to the scenario."""
        sc = inc.scenario
        alerts = sc["alerts"]
        alerting = list(dict.fromkeys(a[0] for a in alerts))
        root = self.root_of(alerting)
        f: list[str] = []
        root_errors = any(a[0] == root and a[1] == "error_rate" for a in alerts)
        if root_errors and any(c not in alerting for c in self.calls.get(root, ())):
            f.append("symptom:caller_5xx_callee_healthy")
        if any(a[1] == "latency_p99" for a in alerts):
            f.append("symptom:latency_p99")
        if inc.cause is not None:
            for service, key, new in inc.cause.changes:
                kind, old = key_kind(key), inc.old_value
                if kind == "timeout" and new < old:
                    f.append("change:timeout_decrease")
                if kind == "retries" and new > old:
                    f.append("change:retries_increase")
                if kind == "pool" and new < old:
                    f.append("change:pool_decrease")
                if kind == "flag" and new != old:
                    f.append("change:flag_flip")
                target = key_target(key)
                if target and target in self.calls.get(service, ()):
                    f.append("topology:sync_call")
            if any(fid.split("/")[-1] in DEP_FILES for fid in inc.cause.files):
                f.append("change:dependency_bump")
            f.append("author:agent" if inc.cause.author in {a for a, _ in AGENTS} else "author:human")
            if sc.get("gap", 99) < 10:
                f.append("trigger:deploy_lt_10m")
        if root in self.consumers:
            f.append("topology:async_consumer")
        return list(dict.fromkeys(f))

    def plan_incidents(self) -> None:
        order = list(range(len(SCENARIOS)))
        self.rng.shuffle(order)
        days = sorted((self.rng.uniform(1.2, 29.0) for _ in order), reverse=True)  # oldest first
        for day, idx in zip(days, order, strict=True):
            start = self.at(day, self.rng.uniform(10, 20))
            self.incidents.append(Incident(SCENARIOS[idx], start, start + self.rng.randint(40, 150) * MIN))
        self.incidents.sort(key=lambda i: i.started_at)
        for n, inc in enumerate(self.incidents, start=1001):
            inc.num = n

    def build_incident_changes(self, values: dict[str, Any]) -> None:
        for inc in self.incidents:
            sc = inc.scenario
            gap = sc.get("gap")
            deploy_ts = inc.started_at - gap * MIN if gap is not None else None
            if "change" in sc:
                service, key, new = sc["change"]
                inc.old_value = values[ids.cfg(service, key)]
                author = self.rng.choice(self.members[self.team_of(service)])
                verb = {
                    "pool": f"lower {key_target(key)} pool size to {new} (too many idle conns)",
                    "retries": f"bump retries to {key_target(key)} to {new} for flaky timeouts",
                    "flag": f"set {key.split('.', 1)[1]}={str(new).lower()} ({sc.get('reason', '')})",
                }[key_kind(key)]
                inc.cause = self.commit(
                    service,
                    author,
                    deploy_ts - self.rng.randint(15, 70) * MIN,
                    f"{service}: {verb}",
                    [file_id("", CONFIG_FILE)],
                    [(service, key, new)],
                )
                self.ship(service, deploy_ts, [inc.cause])
                fix_ts = inc.resolved_at - self.rng.randint(4, 12) * MIN
                restore = inc.old_value
                inc.fix = self.commit(
                    service,
                    author if self.rng.random() < 0.5 else self.on_call[self.team_of(service)],
                    fix_ts - self.rng.randint(12, 25) * MIN,
                    f"revert: restore {service} {key} to {str(restore).lower()}",
                    [file_id("", CONFIG_FILE)],
                    [(service, key, restore)],
                )
                self.ship(service, fix_ts, [inc.fix])
            elif sc["pattern"] == "bad_dependency_bump":
                service = sc["service"]
                lib, v1, v2 = sc["lib"]
                author = self.rng.choice(self.members[self.team_of(service)])
                inc.cause = self.commit(
                    service,
                    author,
                    deploy_ts - self.rng.randint(20, 90) * MIN,
                    f"deps({service}): bump {lib} {v1} -> {v2}",
                    self.files(service, 1, deps=True),
                )
                self.ship(service, deploy_ts, [inc.cause])
                fix_ts = inc.resolved_at - self.rng.randint(4, 12) * MIN
                inc.fix = self.commit(
                    service,
                    self.on_call[self.team_of(service)],
                    fix_ts - 15 * MIN,
                    f"deps({service}): pin {lib} back to {v1}",
                    inc.cause.files,
                )
                self.ship(service, fix_ts, [inc.fix])
            elif sc.get("code_change"):
                service = sc["consumer"]
                author = self.rng.choice(self.members[self.team_of(service)])
                inc.cause = self.commit(
                    service,
                    author,
                    deploy_ts - 40 * MIN,
                    f"{service}: {sc['code_change']}",
                    self.files(service, 2),
                )
                self.ship(service, deploy_ts, [inc.cause])
                fix_ts = inc.resolved_at - 6 * MIN
                inc.fix = self.commit(
                    service, author, fix_ts - 15 * MIN, f"revert: {sc['code_change']}", inc.cause.files
                )
                self.ship(service, fix_ts, [inc.fix])
            if inc.cause is not None:
                for svc, key, new in inc.cause.changes:
                    values[ids.cfg(svc, key)] = new  # (restored by the fix right after)
                for svc, key, new in inc.fix.changes if inc.fix else []:
                    values[ids.cfg(svc, key)] = new
            root = self.root_of(list(dict.fromkeys(a[0] for a in sc["alerts"])))
            owner = self.team_of(inc.cause.service if inc.cause else root)
            inc.resolver = inc.fix.author if inc.fix else self.on_call[owner]
            inc.features = self.features(inc)

    # -- other history --

    def safe_config_changes(self) -> None:
        """Config changes that did NOT cause incidents (detector backtests must stay quiet on these)."""
        planned = [
            ("checkout", "timeouts_ms.payment", 1000, 800, 21.3, "karthik"),
            ("frontend", "timeouts_ms.recommendation", 800, 1000, 17.4, "divya"),
            ("shipping", "timeouts_ms.quote", 500, 600, 12.2, "rahul"),
            ("checkout", "timeouts_ms.shipping", 1200, 1500, 9.1, "sneha"),
            ("search", "timeouts_ms.catalog-db", 200, 150, 26.6, "ananya"),
            ("ads", "timeouts_ms.user-profile", 300, 200, 19.8, "maria"),
            ("notifications", "timeouts_ms.email", 1500, 1000, 14.5, "li"),
            ("user-profile", "timeouts_ms.orders-db", 250, 200, 6.3, "tom"),
            ("reviews", "timeouts_ms.catalog-db", 150, 120, 3.7, "rohan"),
            ("search", "retries.catalog-db", 3, 2, 8.8, "vikram"),
            ("user-profile", "retries.orders-db", 2, 1, 22.9, "maria"),
            ("reviews", "pool.catalog-db", 10, 14, 11.6, "ananya"),
            ("loyalty", "pool.orders-db", 8, 12, 4.4, "li"),
            ("ads", "flags.personalization", True, False, 16.2, "tom"),
            ("notifications", "flags.batch_send", False, True, 2.8, "maria"),
            ("reviews", "flags.show_photos", True, False, 27.5, "rohan"),
        ]
        self.initial: dict[str, Any] = {}
        for service, key, old, new, day, author in planned:
            self.initial[ids.cfg(service, key)] = old
            ts = self.at(day, self.rng.uniform(11, 19))
            c = self.commit(
                service,
                author,
                ts - self.rng.randint(20, 90) * MIN,
                f"{service}: set {key} to {str(new).lower()}",
                [file_id("", CONFIG_FILE)],
                [(service, key, new)],
            )
            self.ship(service, ts, [c])

    def dependency_bot(self) -> None:
        candidates = [s for s, (_, lang, _) in ALL_SERVICES.items() if lang in DEP_BUMPS]
        for service in self.rng.sample(candidates, 8):
            lib, v1, v2 = DEP_BUMPS[ALL_SERVICES[service][1]]
            ts = self.work_time()
            c = self.commit(
                service,
                "deps-bot",
                ts - self.rng.randint(60, 300) * MIN,
                f"chore(deps): bump {lib} from {v1} to {v2}",
                self.files(service, 1, deps=True),
            )
            self.ship(service, ts, [c])

    def filler(self, target_commits: int, target_deploys: int) -> None:
        weights = {
            s: (3 if s in CORE_SERVICES else 1)
            for s in ALL_SERVICES
            if ALL_SERVICES[s][1] not in ("postgres", "redis")
        }
        services, w = list(weights), list(weights.values())
        n_deploys = target_deploys - len(self.deploys)
        sizes = [1] * n_deploys  # random partition of the remaining commits over the remaining deploys
        for _ in range(target_commits - len(self.commits) - n_deploys):
            sizes[self.rng.randrange(n_deploys)] += 1
        for k in sizes:
            service = self.rng.choices(services, w)[0]
            ts = self.work_time()
            commits = []
            for _ in range(k):
                author = self.author_for(service)
                msg = self.rng.choice(FILLER_TEMPLATES).format(s=service, thing=self.rng.choice(THINGS))
                commits.append(
                    self.commit(
                        service,
                        author,
                        ts - self.rng.randint(15, 600) * MIN,
                        msg,
                        self.files(service, self.rng.randint(1, 3)),
                    )
                )
            self.ship(service, ts, sorted(commits, key=lambda c: c.ts))

    # -- assemble --

    def run(self) -> Graph:
        values: dict[str, Any] = {}
        for service, timeouts in SERVICES_YAML.items():
            for callee, ms in timeouts.items():
                values[ids.cfg(service, f"timeouts_ms.{callee}")] = ms
        for (service, key), v in SYNTHETIC_CONFIG.items():
            values[ids.cfg(service, key)] = v
        self.plan_incidents()
        self.safe_config_changes()
        # safe changes start from an older value; incidents read the value current at their time
        initial = {**values, **self.initial}
        self.build_incident_changes(dict(initial))
        self.dependency_bot()
        self.filler(target_commits=297, target_deploys=117)  # + Act 1's 3 commits / 3 deploys = 300 / 120
        return self.emit(initial)

    def emit(self, initial: dict[str, Any]) -> Graph:
        g = Graph()
        rng = self.rng
        add_services(g, SYNTHETIC_SERVICES)
        add_calls(g, SYNTHETIC_CALLS, updated_at=T0 - 10 * MIN)
        add_topics(g, SYNTHETIC_TOPICS)
        for service, (_, lang, _) in ALL_SERVICES.items():
            for name in LANG_FILES[lang]:
                fid = g.node(
                    "File",
                    file_id(service, name),
                    name=f"{service}/{name}",
                    path=f"services/{service}/{name}",
                )
                g.rel(fid, "BELONGS_TO", ids.svc(service))

        # stable, chronological numbering: deploys d-191..d-307, PRs #1101..
        for c in sorted(self.commits, key=lambda c: c.ts):
            c.sha = self.sha()
        for n, d in enumerate(sorted(self.deploys, key=lambda d: d.ts), start=191):
            d.id = f"d-{n}"
        for n, pr in enumerate(sorted(self.prs, key=lambda p: p.opened_at), start=1101):
            pr.number = n
        pr_of = {id(c): pr for pr in self.prs for c in pr.commits}
        for inc in self.incidents:
            inc.cause_pr = pr_of[id(inc.cause)] if inc.cause else None
            inc.fix_pr = pr_of[id(inc.fix)] if inc.fix else None

        for (service, key), _ in SYNTHETIC_CONFIG.items():
            add_config_key(g, service, key, None)  # value set below, after replaying changes
        for c in self.commits:
            cid = g.node(
                "Commit",
                ids.commit(c.sha),
                name=f"{c.sha[:7]} {c.message[:48]}",
                sha=c.sha,
                message=c.message,
                ts=c.ts,
            )
            g.rel(cid, "AUTHORED_BY", ids.node_id("Engineer", c.author))
            for fid in c.files:
                g.rel(cid, "TOUCHES", fid)
        for pr in self.prs:
            author = pr.commits[0].author
            pid = g.node(
                "PR",
                ids.node_id("PR", pr.number),
                name=f"#{pr.number} {pr.title[:60]}",
                number=pr.number,
                title=pr.title,
                state="merged",
                opened_at=pr.opened_at,
                merged_at=pr.merged_at,
                author=author,
            )
            for c in pr.commits:
                g.rel(pid, "CONTAINS", ids.commit(c.sha))
        for d in self.deploys:
            did = g.node(
                "Deploy",
                ids.node_id("Deploy", d.id),
                name=d.id,
                ts=d.ts,
                sha=d.commits[-1].sha,
                status="succeeded",
            )
            g.rel(did, "OF", ids.svc(d.service))
            for c in d.commits:
                g.rel(did, "SHIPS", ids.commit(c.sha))

        # replay every config change in time order: CHANGES{old,new,ts,callee_p99_at_change}, final values
        values = dict(initial)
        for c in sorted((c for c in self.commits if c.changes), key=lambda c: c.ts):
            for service, key, new in c.changes:
                cfg_id = ids.cfg(service, key)
                target = key_target(key)
                p99 = None
                if key_kind(key) == "timeout" and target:
                    p99 = round(P99[target] * rng.uniform(0.93, 1.04))
                g.rel(
                    ids.commit(c.sha),
                    "CHANGES",
                    cfg_id,
                    old=values[cfg_id],
                    new=new,
                    ts=c.ts,
                    callee_p99_at_change=p99,
                )
                values[cfg_id] = new
        for (service, key), _ in SYNTHETIC_CONFIG.items():
            g.node("ConfigKey", ids.cfg(service, key), value=values[ids.cfg(service, key)])
        for service, timeouts in SERVICES_YAML.items():  # history must end on the canonical services.yaml
            for callee, ms in timeouts.items():
                assert values[ids.cfg(service, f"timeouts_ms.{callee}")] == ms, (service, callee)

        self.emit_incidents(g)
        self.emit_memory(g)
        return g

    def emit_incidents(self, g: Graph) -> None:
        rng = self.rng
        for inc in self.incidents:
            sc = inc.scenario
            iid = ids.node_id("Incident", inc.id)
            alerting = list(dict.fromkeys(a[0] for a in sc["alerts"]))
            root = self.root_of(alerting)
            title, summary, fix = self.incident_text(inc, root, alerting)
            severity = (
                "sev1"
                if "frontend" in alerting and len(alerting) > 2
                else ("sev3" if sc["pattern"] == "kafka_lag" else "sev2")
            )
            g.node(
                "Incident",
                iid,
                name=inc.id,
                title=title,
                summary=summary,
                status="resolved",
                severity=severity,
                started_at=inc.started_at,
                resolved_at=inc.resolved_at,
                fix=fix,
            )
            for n, (service, signal, value, threshold) in enumerate(sc["alerts"], start=1):
                aid = g.node(
                    "Alert",
                    ids.node_id("Alert", f"a-{inc.num}-{n}"),
                    name=f"a-{inc.num}-{n} {service} {signal}",
                    ts=inc.started_at + (n - 1) * 40_000,
                    signal=signal,
                    value=value,
                    threshold=threshold,
                    severity=severity,
                    incident_id=inc.id,
                    source="watcher",
                )
                g.rel(aid, "FIRED_ON", ids.svc(service))
                g.rel(iid, "TRIGGERED_BY", aid)
            for service in alerting:
                g.rel(iid, "IMPACTED", ids.svc(service))
            if inc.cause:
                g.rel(iid, "CAUSED_BY", ids.commit(inc.cause.sha))
            if inc.fix_pr:
                g.rel(iid, "RESOLVED_BY", ids.node_id("PR", inc.fix_pr.number))
            g.rel(ids.node_id("Engineer", inc.resolver), "RESOLVED", iid)
            for name in inc.features:
                fid = g.node("Feature", ids.node_id("Feature", name), name=name, kind=name.split(":", 1)[0])
                g.rel(iid, "HAS_FEATURE", fid)
            # 3-5 chat lines in the incident channel
            team = self.members[self.team_of(inc.cause.service if inc.cause else root)]
            people = [inc.resolver] + [h for h in rng.sample(team, min(3, len(team))) if h != inc.resolver]
            lines = self.chat_lines(inc, root, alerting, fix)
            span = inc.resolved_at - inc.started_at
            for n, text in enumerate(lines, start=1):
                ts = inc.started_at + int(span * (n - 0.7) / len(lines))
                g.node(
                    "ChatMessage",
                    ids.node_id("ChatMessage", f"{inc.id}-{n}"),
                    name=f"{inc.id} chat {n}",
                    channel=f"#inc-{inc.num}",
                    author=people[(n - 1) % len(people)],
                    ts=ts,
                    text=text.format(t=ist(ts)),
                )

    def incident_text(self, inc: Incident, root: str, alerting: list[str]) -> tuple[str, str, str]:
        sc, p = inc.scenario, inc.pattern
        up = [s for s in alerting if s != root]
        upstream = f" and {', '.join(up)} started returning 5xx" if up else ""
        pr = f"PR #{inc.cause_pr.number}" if inc.cause_pr else ""
        if p == "db_pool_exhaustion":
            service, key, new = sc["change"]
            db = key_target(key)
            return (
                f"{root} latency spike, {db} pool exhausted",
                f"{root} p99 went to {sc['alerts'][0][2]}ms{upstream}. The {db} connection pool was "
                "exhausted "
                f"after {pr} lowered {key} from {inc.old_value} to {new}; peak concurrency is "
                f"~{PEAK_CONCURRENCY[service]}.",
                f"restored {key} to {inc.old_value}",
            )
        if p == "retry_storm":
            service, key, new = sc["change"]
            callee = key_target(key)
            return (
                f"{callee} overloaded by retries from {service}",
                f"{callee} p99 jumped to {sc['alerts'][0][2]}ms{upstream}. {pr} raised {key} on {service} "
                "from "
                f"{inc.old_value} to {new}; every slow call was retried and {callee} load went up ~{new}x.",
                f"set {key} back to {inc.old_value} and added jittered backoff",
            )
        if p == "cert_expiry":
            return (
                f"{sc['caller']} TLS errors to {sc['callee']}",
                f"{sc['caller']} failed TLS handshakes to {sc['callee']} (cert expired at 00:00 "
                f"UTC){upstream}. "
                f"{sc['callee']} itself was healthy, nothing was deployed.",
                f"rotated the {sc['callee']} cert and added an expiry alert",
            )
        if p == "bad_dependency_bump":
            lib, v1, v2 = sc["lib"]
            return (
                f"{sc['service']} 5xx after {lib} upgrade",
                f"{sc['service']} started returning 5xx right after {pr} bumped {lib} {v1} -> "
                f"{v2}{upstream}: "
                f"{sc['breakage']}.",
                f"pinned {lib} back to {v1}",
            )
        if p == "flag_misconfig":
            service, key, new = sc["change"]
            flag = key.split(".", 1)[1]
            if "cache" in flag:
                return (
                    f"catalog-db overloaded, {service} cache disabled",
                    f"catalog-db p99 hit {sc['alerts'][0][2]}ms{upstream} after {pr} set "
                    f"{flag}={str(new).lower()} "
                    f"on {service} ({sc['reason']}); every read went to the database.",
                    f"turned {flag} back on",
                )
            return (
                f"{service} 5xx after {flag} rollout",
                f"{service} returned 5xx for ~45% of requests{upstream} once {pr} flipped {flag} to "
                f"{str(new).lower()} for everyone ({sc['reason']}).",
                f"rolled {flag} back to {str(inc.old_value).lower()}",
            )
        # kafka_lag
        lag = f"{sc['lag']:,}"
        cause = f" after {pr} ({sc['code_change']})" if inc.cause_pr else " during the evening order peak"
        return (
            f"{sc['consumer']} consumer lag on {sc['topic']}",
            f"{sc['consumer']} fell {lag} messages behind on topic {sc['topic']}{cause}. Nothing customer "
            "facing "
            f"failed, downstream work was delayed by ~{sc['alerts'][1][2] // 60000} min.",
            "reverted the consumer change"
            if inc.cause_pr
            else "scaled the consumer group from 3 to 8 replicas",
        )

    def chat_lines(self, inc: Incident, root: str, alerting: list[str], fix: str) -> list[str]:
        sc = inc.scenario
        first = sc["alerts"][0]
        what = "p99" if first[1] == "latency_p99" else ("lag" if first[1] == "saturation" else "5xx")
        lines = [f"seeing {what} alerts on {root} since ~{{t}}, looking"]
        if inc.cause_pr:
            lines.append(f"only thing that shipped recently is #{inc.cause_pr.number} ({inc.cause_pr.title})")
        elif sc["pattern"] == "cert_expiry":
            lines.append(f"handshake failures to {sc['callee']}... cert expired?? who owns rotation for this")
        else:
            lines.append(f"no deploys near this, {sc.get('topic', 'the topic')} traffic is 2x normal")
        if self.rng.random() < 0.6:
            lines.append(
                self.rng.choice(
                    [
                        "paging the owners",
                        "status page updated",
                        "can someone check grafana",
                        "customers reporting it on twitter too",
                    ]
                )
            )
        lines.append(f"{fix}, recovering")
        if self.rng.random() < 0.5:
            lines.append("will write the postmortem tmrw")
        return lines

    def emit_memory(self, g: Graph) -> None:
        by_pattern: dict[str, list[Incident]] = {}
        for inc in self.incidents:
            by_pattern.setdefault(inc.pattern, []).append(inc)
        for pattern, incs in by_pattern.items():
            pat = g.node(
                "FailurePattern",
                ids.node_id("FailurePattern", pattern),
                name=pattern,
                description=PATTERN_INFO[pattern],
            )
            prev = None
            for i, inc in enumerate(incs):
                latest = i == len(incs) - 1
                lid = g.node(
                    "Lesson",
                    ids.node_id("Lesson", f"L-{inc.num}"),
                    name=f"L-{inc.num}",
                    text=self.lesson_text(inc),
                    confidence=round(0.55 + 0.1 * i, 2) if latest else 0.5,
                    uses=len(incs) - 1 - i + (1 if latest else 0),
                    prevented=(i if latest else 0),
                    status="active" if latest else "superseded",
                    created_at=inc.resolved_at + 2 * HOUR,
                    source="seed",
                )
                g.rel(lid, "LEARNED_FROM", ids.node_id("Incident", inc.id))
                g.rel(lid, "ABOUT", pat)
                if prev:
                    g.rel(lid, "SUPERSEDES", prev)
                prev = lid
            last = incs[-1]
            slug, title, text = DECISIONS[pattern]
            did = g.node(
                "Decision",
                ids.node_id("Decision", slug),
                name=title,
                title=title,
                text=text,
                created_at=last.resolved_at + 3 * HOUR,
            )
            g.rel(did, "FROM", ids.node_id("Lesson", f"L-{last.num}"))
            if last.fix_pr:
                g.rel(ids.node_id("PR", last.fix_pr.number), "IMPLEMENTS", did)
            if t := PATTERN_DETECTOR.get(pattern):
                # minted from the latest incident this template really fires on (self-validation)
                origin = [
                    i
                    for i in incs
                    if i.cause
                    and any(
                        key_kind(k) == t.change_kind and (t.change_kind != "flag" or "cache" in k)
                        for _, k, _ in i.cause.changes
                    )
                ][-1]
                det = g.node(
                    "Detector",
                    ids.node_id("Detector", f"D-{origin.num}"),
                    name=f"D-{origin.num} {t.name}",
                    template=t.name,
                    cypher=t.cypher,
                    params=json.dumps(t.params),
                    status="active",
                    created_at=origin.resolved_at + 3 * HOUR,
                    source="seed",
                    learned_from=origin.id,
                )
                g.rel(det, "DETECTS", pat)
        self.emit_runbooks(g, by_pattern)

    def lesson_text(self, inc: Incident) -> str:
        sc, p = inc.scenario, inc.pattern
        if p == "db_pool_exhaustion":
            service, key, new = sc["change"]
            return (
                f"Keep {service}'s {key} at or above its peak concurrency (~{PEAK_CONCURRENCY[service]}). In "
                f"{inc.id} it was cut {inc.old_value}->{new} and requests queued waiting for a connection."
            )
        if p == "retry_storm":
            service, key, new = sc["change"]
            return (
                f"Cap retries at 2 with jittered backoff. In {inc.id}, {service} raised {key} "
                f"{inc.old_value}->{new}"
                f" and the retries multiplied load on an already slow {key_target(key)}."
            )
        if p == "cert_expiry":
            return (
                f"Alert 14 days before a cert expires and rotate with cert-manager. In {inc.id} the "
                f"{sc['callee']} cert expired; {sc['caller']} saw TLS errors while {sc['callee']} was "
                "healthy."
            )
        if p == "bad_dependency_bump":
            lib, v1, v2 = sc["lib"]
            return (
                f"Canary major dependency bumps and read the changelog. In {inc.id}, {lib} {v1}->{v2} in "
                f"{sc['service']}: {sc['breakage']}."
            )
        if p == "flag_misconfig":
            service, key, new = sc["change"]
            return (
                f"Flags that change load need a load check before they flip in prod. In {inc.id}, "
                f"{service} {key}={str(new).lower()} changed behaviour for all traffic at once."
            )
        return (
            f"Autoscale {sc['consumer']} on partition lag and alert at 10k. In {inc.id} it fell "
            f"{sc['lag']:,} messages behind on {sc['topic']}."
        )

    def emit_runbooks(self, g: Graph, by_pattern: dict[str, list[Incident]]) -> None:
        def first(pattern: str) -> Incident:
            return by_pattern[pattern][0]

        def last(pattern: str) -> Incident:
            return by_pattern[pattern][-1]

        books = [
            (
                "payment-latency",
                "Payment latency",
                self.at(19.2, 15.5),
                None,
                ["svc:payment", "svc:checkout", "cfg:checkout.timeouts_ms.payment"],
                "Owner: payments team (#payments-oncall).\n"
                "If checkout throws 5xx and payment dashboards look fine, check the checkout->payment "
                "timeout first.\n"
                "Current setting: timeouts_ms.payment = 800ms. payment p99 is ~450ms on a normal day, higher "
                "during "
                "sales. Dont go below ~700ms without a load test.\n"
                "Payment itself rarely fails, usually its the caller giving up too early.",
            ),
            (
                "shipping-quotes",
                "Shipping quotes",
                self.at(10.4, 12.0),
                None,
                ["svc:shipping", "svc:quote", "cfg:shipping.timeouts_ms.quote"],
                "quote is slow by design (it calls the carrier APIs), p99 ~300ms.\n"
                "shipping->quote timeout is 600ms (raised from 500 after the carrier latency bump).\n"
                "If quotes fail check the carrier status page before touching config.",
            ),
            (
                "checkout-oncall",
                "Checkout on-call",
                self.at(15.1, 17.0),
                None,
                ["svc:checkout", "svc:frontend", "cfg:checkout.timeouts_ms.shipping"],
                "Checkout on-call cheat sheet.\n"
                "1. Check frontend + checkout 5xx in grafana.\n"
                "2. Timeouts: shipping 1200ms, payment 800ms, cart/currency 300ms.\n"
                "3. Roll back the last deploy if it is < 30 min old, ask questions later.",
            ),
            (
                "db-pool-exhaustion",
                "DB pool exhaustion",
                last("db_pool_exhaustion").resolved_at + DAY,
                "db_pool_exhaustion",
                ["cfg:inventory.pool.inventory-db", "cfg:user-profile.pool.orders-db", "svc:orders-db"],
                "Symptom: p99 climbs on one service, DB itself looks idle.\n"
                "Check pool wait time metric. Pool size must be >= peak concurrency (see the service "
                "README).\n"
                "Fix: restore pool size, do NOT restart the db.",
            ),
            (
                "retry-storms",
                "Retry storms",
                first("retry_storm").resolved_at + DAY,
                "retry_storm",
                ["cfg:search.retries.inventory", "cfg:auth.retries.sessions", "svc:inventory"],
                "If a callee is slow and its callers are erroring, look at retry counts first.\n"
                "We allow max 2 retries w/ jittered backoff. More than that = storm.\n"
                "search->inventory retries: 1. auth->sessions retries: 1.",
            ),
            (
                "cert-rotation",
                "Cert rotation",
                last("cert_expiry").resolved_at + DAY,
                "cert_expiry",
                ["svc:sessions", "svc:image-resizer", "svc:catalog-db"],
                "Certs are issued by cert-manager. If you see handshake errors, run kubectl get certificates "
                "-A and "
                "check NotAfter. Expiry alert fires 14d before.",
            ),
            (
                "dependency-upgrades",
                "Dependency upgrades",
                last("bad_dependency_bump").resolved_at + DAY,
                "bad_dependency_bump",
                ["svc:search", "svc:auth", "svc:user-profile"],
                "Minor/patch bumps from deps-bot can merge on green CI.\n"
                "Major bumps: canary 5% for 30min, read the changelog, get a second reviewer.",
            ),
            (
                "feature-flags",
                "Feature flags",
                first("flag_misconfig").started_at - 2 * DAY,
                "flag_misconfig",
                [
                    "cfg:search.flags.cache_enabled",
                    "cfg:reviews.flags.cache_enabled",
                    "cfg:user-profile.flags.new_profile_api",
                ],
                "Flags live in config/services.yaml under flags.*\n"
                "cache_enabled should always be true in prod. new_profile_api is at 10% rollout.\n"
                "Flip flags in the evening, not during the lunch peak.",
            ),
            (
                "kafka-consumer-lag",
                "Kafka consumer lag",
                last("kafka_lag").resolved_at + DAY,
                "kafka_lag",
                ["svc:accounting", "svc:analytics", "svc:notifications"],
                "Lag alert = consumer group behind its topic. Customer flows keep working, ledger/emails are "
                "delayed.\n"
                "Scale the consumer group (KEDA) before restarting anything; restarts trigger a rebalance.",
            ),
        ]
        for slug, title, updated_at, pattern, mentions, text in books:
            rid = g.node(
                "Runbook",
                ids.node_id("Runbook", slug),
                name=title,
                title=title,
                text=text,
                updated_at=updated_at,
            )
            for m in mentions:
                g.rel(rid, "MENTIONS", m)
            if pattern:
                g.rel(rid, "FOR", ids.node_id("FailurePattern", pattern))


# --- act1.json ---------------------------------------------------------------------------------------


def build_act1() -> Graph:
    """Exactly the replay-fixture ids: PR #12 by coder-bot lowers checkout->payment 800 -> 200 ms."""
    g = Graph()
    cfg_id = ids.cfg("checkout", "timeouts_ms.payment")
    commit_ts, merged, deploy_ts = T0 - 9 * MIN, T0 - 5 * MIN, T0 - 3 * MIN
    cid = g.node(
        "Commit",
        ids.commit(ACT1_SHA),
        name=f"{ACT1_SHA} lower payment timeout",
        sha=ACT1_SHA,
        message="perf(checkout): lower payment timeout to 200ms to cut checkout latency",
        ts=commit_ts,
    )
    g.rel(cid, "AUTHORED_BY", ids.node_id("Engineer", SDE_BOT))
    g.rel(cid, "TOUCHES", file_id("", CONFIG_FILE))
    g.rel(cid, "CHANGES", cfg_id, old=800, new=200, ts=commit_ts, callee_p99_at_change=450)
    g.node("ConfigKey", cfg_id, value=200)
    pid = g.node(
        "PR",
        ids.node_id("PR", ACT1_PR),
        name=f"#{ACT1_PR} Reduce checkout latency",
        number=ACT1_PR,
        title="Reduce checkout latency",
        state="merged",
        opened_at=commit_ts + MIN,
        merged_at=merged,
        author=SDE_BOT,
        url=f"https://github.com/redwing-381/astro-mini/pull/{ACT1_PR}",
    )
    g.rel(pid, "CONTAINS", cid)
    did = g.node(
        "Deploy",
        ids.node_id("Deploy", ACT1_DEPLOY),
        name=ACT1_DEPLOY,
        ts=deploy_ts,
        sha=ACT1_SHA,
        status="succeeded",
    )
    g.rel(did, "SHIPS", cid)
    g.rel(did, "OF", ids.svc("checkout"))

    # two innocent deploys inside the 30-minute suspect window, so suspect_changes has to rank
    decoys = [
        ("d-309", "cart", "divya", "3e81d07", 1298, "cart: show saved-for-later count", 25),
        (
            "d-310",
            "product-catalog",
            "vikram",
            "c47a9e2",
            1299,
            "product-catalog: add index hint for category query",
            12,
        ),
    ]
    for dep, service, author, sha, pr_no, msg, minutes in decoys:
        ts = T0 - minutes * MIN
        c = g.node(
            "Commit", ids.commit(sha), name=f"{sha} {msg[:40]}", sha=sha, message=msg, ts=ts - 30 * MIN
        )
        g.rel(c, "AUTHORED_BY", ids.node_id("Engineer", author))
        p = g.node(
            "PR",
            ids.node_id("PR", pr_no),
            name=f"#{pr_no} {msg}",
            number=pr_no,
            title=msg,
            state="merged",
            opened_at=ts - 25 * MIN,
            merged_at=ts - 4 * MIN,
            author=author,
        )
        g.rel(p, "CONTAINS", c)
        d = g.node("Deploy", ids.node_id("Deploy", dep), name=dep, ts=ts, sha=sha, status="succeeded")
        g.rel(d, "SHIPS", c)
        g.rel(d, "OF", ids.svc(service))

    iid = g.node(
        "Incident",
        ids.node_id("Incident", INCIDENT),
        name=INCIDENT,
        title="checkout 5xx spike",
        summary="checkout returning 5xx for 62% of requests since 10:00 IST, frontend 41%. payment, cart "
        "and currency look healthy.",
        status="open",
        severity="sev2",
        started_at=T0,
    )
    for aid, service, value, ts in (("a-901", "checkout", 0.62, T0), ("a-902", "frontend", 0.41, T0 + 4000)):
        a = g.node(
            "Alert",
            ids.node_id("Alert", aid),
            name=f"{aid} {service} error_rate {round(value * 100)}%",
            ts=ts,
            signal="error_rate",
            value=value,
            threshold=0.10,
            severity="sev2",
            incident_id=INCIDENT,
            source="watcher",
        )
        g.rel(a, "FIRED_ON", ids.svc(service))
        g.rel(iid, "TRIGGERED_BY", a)
        g.rel(iid, "IMPACTED", ids.svc(service))
    return g


def build_all() -> dict[str, dict[str, Any]]:
    return {
        "core": build_core().to_json(),
        "act1": build_act1().to_json(),
        "history": HistoryGen().run().to_json(),
    }


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in build_all().items():
        path = DATA_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        n_nodes = sum(len(v) for v in data["nodes"].values())
        print(f"wrote {path.relative_to(DATA_DIR.parent.parent)}: {n_nodes} nodes, {len(data['rels'])} rels")


if __name__ == "__main__":
    main()
