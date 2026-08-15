from pathlib import Path

import pytest

from devflow.config import Settings
from devflow.runtime import DevFlowRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> DevFlowRuntime:
    return DevFlowRuntime(
        Settings(
            db_path=tmp_path / "devflow.db",
            report_dir=tmp_path / "reports",
            tool_mode="mcp",
            max_steps=8,
            max_replans=2,
            cors_origins=("http://localhost:3000", "http://127.0.0.1:3000"),
        )
    )
