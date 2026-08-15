from __future__ import annotations

from devflow.config import PROJECT_ROOT, settings
from devflow.store import SQLiteStore
from devflow.tools import LocalToolRegistry, ToolRouter


def build_components() -> tuple[SQLiteStore, LocalToolRegistry, ToolRouter]:
    store = SQLiteStore(settings.db_path)
    registry = LocalToolRegistry(
        PROJECT_ROOT / "fixtures" / "payment_incident",
        settings.report_dir,
    )
    return store, registry, ToolRouter(registry, store)

