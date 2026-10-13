"""Music-to-light synchronization engine and rate-limited scheduler."""

from typing import TYPE_CHECKING, Any
from src.sync.state import LightingState, SyncStatus

if TYPE_CHECKING:
    from src.sync.engine import MusicSyncEngine
    from src.sync.scheduler import BulbCommandScheduler


def __getattr__(name: str) -> Any:
    if name == "MusicSyncEngine":
        from src.sync.engine import MusicSyncEngine
        return MusicSyncEngine
    if name == "BulbCommandScheduler":
        from src.sync.scheduler import BulbCommandScheduler
        return BulbCommandScheduler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MusicSyncEngine",
    "BulbCommandScheduler",
    "LightingState",
    "SyncStatus",
]
