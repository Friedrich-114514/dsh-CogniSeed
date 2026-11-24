"""JSON 文件后端（教学用）：一个文件装一张表，原子替换写入。

接口与 ``sqlite_store.SqliteStore`` 完全一致，可直接互换：

    save(key, payload) / load(key, default) / delete(key) / keys() / close()

写入策略：先写 ``<path>.tmp`` 再 ``os.replace``，避免半截文件。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

__all__ = ["JsonStore", "STORE_VERSION"]

STORE_VERSION = 1


class JsonStore:
    """把 ``key -> dict`` 存进单个 JSON 文件。

    文件结构::

        {"version": 1, "updated_at": 1699999999.0, "rows": {"<key>": {...}}}
    """

    def __init__(self, path: str | os.PathLike[str], *, indent: int = 2) -> None:
        self.path = Path(path)
        self.indent = indent
        self._rows: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._load()

    # -- 内部 -------------------------------------------------------------- #

    def _load(self) -> None:
        if self.path.exists():
            text = self.path.read_text(encoding="utf-8").strip()
            if text:
                data = json.loads(text)
                rows = data.get("rows", data)
                if not isinstance(rows, dict):
                    raise ValueError(f"{self.path} 结构不是 {{rows: {{...}}}}")
                self._rows = {str(k): dict(v) for k, v in rows.items()}
        self._loaded = True

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "rows": self._rows,
        }
        fd, tmp = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=self.indent, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _replace(tmp: str, target: Path, attempts: int = 6) -> None:
        """``os.replace`` 在 Windows 上会因杀毒/索引临时占用目标文件而失败。

        这不是逻辑错误，等 20~120ms 让占用方松手即可；重试用尽再原样抛出。
        """
        last: Exception | None = None
        for i in range(attempts):
            try:
                os.replace(tmp, target)
                return
            except PermissionError as exc:   # WinError 5 / 32：目标被占用
                last = exc
                time.sleep(0.02 * (i + 1))
        assert last is not None
        raise last

    # -- 公开接口 ---------------------------------------------------------- #

    def save(self, key: str, payload: Mapping[str, Any]) -> None:
        self._rows[str(key)] = dict(payload)
        self._flush()

    def load(self, key: str, default: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        row = self._rows.get(str(key))
        return dict(row) if row is not None else default

    def delete(self, key: str) -> bool:
        if str(key) in self._rows:
            del self._rows[str(key)]
            self._flush()
            return True
        return False

    def keys(self) -> Iterator[str]:
        return iter(sorted(self._rows))

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, key: object) -> bool:
        return str(key) in self._rows

    def close(self) -> None:
        """JsonStore 无句柄；保留方法以对齐 SqliteStore 接口。"""
        self._rows.clear()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"JsonStore(path={str(self.path)!r}, rows={len(self._rows)})"
