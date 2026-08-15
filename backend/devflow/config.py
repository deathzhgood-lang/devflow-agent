from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    report_dir: Path
    tool_mode: str
    max_steps: int
    max_replans: int
    cors_origins: tuple[str, ...]
    llm_enabled: bool = False
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_thinking: bool = False
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 4096
    llm_fallback_enabled: bool = True
    mcp_timeout_seconds: float = 10.0
    mcp_max_retries: int = 1
    knowledge_mode: str = "fixture"
    knowledge_api_base: str | None = None
    knowledge_api_token: str | None = None
    knowledge_timeout_seconds: float = 35.0
    knowledge_max_retries: int = 1
    knowledge_fixture_fallback: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=PROJECT_ROOT / os.getenv("DEVFLOW_DB_PATH", "runtime_data/devflow.db"),
            report_dir=PROJECT_ROOT / os.getenv("DEVFLOW_REPORT_DIR", "runtime_data/reports"),
            tool_mode=os.getenv("DEVFLOW_TOOL_MODE", "mcp"),
            max_steps=int(os.getenv("DEVFLOW_MAX_STEPS", "8")),
            max_replans=int(os.getenv("DEVFLOW_MAX_REPLANS", "2")),
            cors_origins=tuple(
                item.strip()
                for item in os.getenv(
                    "DEVFLOW_CORS_ORIGINS",
                    "http://localhost:3000,http://127.0.0.1:3000",
                ).split(",")
                if item.strip()
            ),
            llm_enabled=env_bool("DEVFLOW_LLM_ENABLED"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            deepseek_thinking=env_bool("DEEPSEEK_THINKING"),
            llm_timeout_seconds=float(os.getenv("DEVFLOW_LLM_TIMEOUT_SECONDS", "30")),
            llm_max_tokens=int(os.getenv("DEVFLOW_LLM_MAX_TOKENS", "4096")),
            llm_fallback_enabled=env_bool("DEVFLOW_LLM_FALLBACK_ENABLED", True),
            mcp_timeout_seconds=float(os.getenv("DEVFLOW_MCP_TIMEOUT_SECONDS", "10")),
            mcp_max_retries=int(os.getenv("DEVFLOW_MCP_MAX_RETRIES", "1")),
            knowledge_mode=os.getenv("DEVFLOW_KNOWLEDGE_MODE", "fixture").strip().lower(),
            knowledge_api_base=os.getenv("KNOWLEDGE_API_BASE") or None,
            knowledge_api_token=os.getenv("KNOWLEDGE_API_TOKEN") or None,
            knowledge_timeout_seconds=float(os.getenv("KNOWLEDGE_TIMEOUT_SECONDS", "35")),
            knowledge_max_retries=int(os.getenv("KNOWLEDGE_MAX_RETRIES", "1")),
            knowledge_fixture_fallback=env_bool("KNOWLEDGE_FIXTURE_FALLBACK", True),
        )


settings = Settings.from_env()
