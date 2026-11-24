"""SQLite 后端（生产用）：标准库 sqlite3，同样零第三方依赖。

表名按设计稿抽象为 ``engram_traces``（记忆印迹）与 ``learning_registry``
（学籍表）。表名走白名单，不接受外部拼串。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

__all__ = ["SqliteStore", "ALLOWED_TABLES"]

ALLOWED_TABLES = frozenset({"engram_traces", "learning_registry"})
_DEFAULT_TABLE = "learning_registry"


class SqliteStore:
    """``key -> JSON`` 的 SQLite 实现，接口与 ``JsonStore`` 一致。"""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        table: str = _DEFAULT_TABLE,
        timeout: float = 5.0,
    ) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(
                f"表名只允许 {sorted(ALLOWED_TABLES)}，收到 {table!r}"
            )
        self.path = Path(path)
        self.table = table
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path), timeout=timeout, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} ("
            "  key TEXT PRIMARY KEY,"
            "  payload TEXT NOT NULL,"
            "  updated_at REAL NOT NULL"
            ")"
        )

    # -- 公开接口 ---------------------------------------------------------- #

    def save(self, key: str, payload: Mapping[str, Any]) -> None:
        body = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
        self._conn.execute(
            f"INSERT INTO {self.table} (key, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
            "updated_at=excluded.updated_at",
            (str(key), body, float(payload.get("_ts", 0.0)) if isinstance(payload, Mapping) else 0.0),
        )

    def save_many(self, rows: Mapping[str, Mapping[str, Any]], ts: float = 0.0) -> None:
        """批量写入，单事务。"""
        payloads = [
            (str(k), json.dumps(dict(v), ensure_ascii=False, sort_keys=True), ts)
            for k, v in rows.items()
        ]
        self._conn.execute("BEGIN")
        try:
            self._conn.executemany(
                f"INSERT INTO {self.table} (key, payload, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                payloads,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def load(self, key: str, default: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            f"SELECT payload FROM {self.table} WHERE key = ?", (str(key),)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def delete(self, key: str) -> bool:
        cur = self._conn.execute(
            f"DELETE FROM {self.table} WHERE key = ?", (str(key),)
        )
        return cur.rowcount > 0

    def keys(self) -> Iterator[str]:
        for (k,) in self._conn.execute(
            f"SELECT key FROM {self.table} ORDER BY key"
        ):
            yield k

    def __len__(self) -> int:
        (n,) = self._conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()
        return int(n)

    def __contains__(self, key: object) -> bool:
        row = self._conn.execute(
            f"SELECT 1 FROM {self.table} WHERE key = ?", (str(key),)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._conn.close()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"SqliteStore(path={str(self.path)!r}, table={self.table!r})"
