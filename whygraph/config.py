"""Runtime settings, read from environment / .env (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # FalkorDB
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: str | None = None
    whygraph_graph: str = "whygraph_demo"

    # LLM
    anthropic_api_key: str | None = None
    model_reasoning: str = "claude-sonnet-5-5"
    model_fast: str = "claude-haiku-5-5"
    graph_only: bool = False
    llm_fallbacks: bool = True  # server-side refusal fallback on the reasoning model
    agent_max_steps: int = 8  # tool calls per agent run
    llm_timeout_s: float = 60.0
    alert_grace_s: float = 5.0  # wait for sibling alerts before investigating

    # Embeddings
    voyage_api_key: str | None = None
    embed_model: str = "voyage-4-lite"
    embed_dim: int = 1024

    # GitHub
    github_token: str | None = None
    github_repo: str | None = None

    # API / MCP auth
    whygraph_api_token: str = "change-me"

    # Paths
    recordings_dir: Path = REPO_ROOT / "scenarios" / "recordings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
