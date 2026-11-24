"""存储后端。

两个实现共享同一份最小接口，可直接互换：

    store.save(key: str, payload: Mapping[str, Any]) -> None
    store.load(key: str, default=None) -> dict | None
    store.delete(key: str) -> bool
    store.keys() -> Iterator[str]
    store.close() -> None

``JsonStore`` 教学/单机，``SqliteStore`` 生产/并发。
"""

from .json_store import JsonStore
from .sqlite_store import SqliteStore, ALLOWED_TABLES

__all__ = ["JsonStore", "SqliteStore", "ALLOWED_TABLES"]
