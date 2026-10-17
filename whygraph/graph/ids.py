"""Stable string ids for every node and relationship (docs/schema.md, "Identity rule")."""

PREFIX = {
    "Service": "svc",
    "Topic": "topic",
    "Team": "team",
    "Engineer": "eng",
    "PR": "pr",
    "Commit": "commit",
    "File": "file",
    "ConfigKey": "cfg",
    "Deploy": "deploy",
    "Alert": "alert",
    "Incident": "inc",
    "Feature": "feat",
    "Investigation": "inv",
    "AgentStep": "step",
    "Finding": "find",
    "Lesson": "lesson",
    "FailurePattern": "pat",
    "Detector": "det",
    "Decision": "dec",
    "Runbook": "rb",
    "ChatMessage": "msg",
}
LABELS = list(PREFIX)


def node_id(label: str, key: str | int) -> str:
    return f"{PREFIX[label]}:{key}"


def rel_id(src: str, rel_type: str, dst: str) -> str:
    return f"{src}|{rel_type}|{dst}"


def svc(name: str) -> str:
    return node_id("Service", name)


def cfg(service: str, key: str) -> str:
    return node_id("ConfigKey", f"{service}.{key}")


def commit(sha: str) -> str:
    return node_id("Commit", sha[:7])
