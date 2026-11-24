#!/usr/bin/env python3
"""DSH 插件桥接 —— 核心侧 Runner。

协议见同目录 ``PROTOCOL.md``。这里只做四件事：

    ingest   消费 intake/ 里的事件，写进学籍表与爱好账本
    settle   跑一个睡眠周期（作答与校验器由 sleep.trigger 事件带进来）
    project  写 outbox/projection.json（只读投影）
    status   打印当前状态

零第三方依赖：只用 ``cogniseed`` 与标准库。

    python bridge.py demo --data ./tmp-bridge
    python bridge.py --data ./tmp-bridge ingest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cogniseed import (
    ConsolidationEngine,
    HobbyLedger,
    LearningRegistry,
    SleepScheduleConfig,
    Verifier,
)
from cogniseed.models import PrivacyViolation, QuotaExceeded
from cogniseed.storage import JsonStore

PROTOCOL = "cogniseed.bridge/1"
KINDS = frozenset(
    {
        "note",
        "restatement",
        "transfer",
        "hobby.observe",
        "hobby.solo",
        "hobby.shared",
        "hobby.brake",
        "sleep.trigger",
    }
)

# 演示替身：字符重合 ≥ 8 即算语义复现。生产请换成一次 LLM 判定调用。
def keyword_verifier(expected: str, candidate: str) -> bool:
    return len(set(expected) & set(candidate)) >= 8


VERIFIERS: dict[str, Verifier] = {"keyword": keyword_verifier}


# --------------------------------------------------------------------------- #
# 目录
# --------------------------------------------------------------------------- #


class Bridge:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.root = Path(data_dir).resolve()
        self.intake = self.root / "intake"
        self.archive = self.root / "archive"
        self.rejected = self.archive / "rejected"
        self.outbox = self.root / "outbox"
        self.state = self.root / "state"
        self.registry_path = self.state / "registry.json"
        self.pending_path = self.state / "pending_answers.json"

    def init(self) -> None:
        for d in (self.intake, self.archive, self.rejected, self.outbox, self.state):
            d.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            store = JsonStore(self.registry_path)
            LearningRegistry(store=store).persist()   # 写入空 registry:meta
            store.close()

    # -- 状态读写 ---------------------------------------------------------- #

    def open(self) -> tuple[LearningRegistry, HobbyLedger, JsonStore]:
        if not self.registry_path.exists():
            self.init()
        store = JsonStore(self.registry_path)
        if store.load("registry:meta") is None:
            reg = LearningRegistry(store=store)
            reg.persist()
        else:
            reg = LearningRegistry.load(store)
        ledger_state = store.load("hobby:ledger")
        ledger = HobbyLedger.from_state(ledger_state) if ledger_state else HobbyLedger()
        return reg, ledger, store

    def save(self, reg: LearningRegistry, ledger: HobbyLedger, store: JsonStore) -> None:
        reg.persist(store)
        ledger.persist(store)
        store.close()

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)

    # -- ingest ------------------------------------------------------------ #

    def _iter_events(self) -> list[Path]:
        return sorted(p for p in self.intake.glob("*.json") if not p.name.endswith(".tmp"))

    def ingest(self) -> dict[str, Any]:
        """消费全部待处理事件。返回计数，不抛异常（坏事件进 rejected/）。"""
        self.init()
        reg, ledger, store = self.open()
        stats = {"accepted": 0, "rejected": 0, "by_kind": {}}
        pending: dict[str, str] = {}
        if self.pending_path.exists():
            pending = json.loads(self.pending_path.read_text(encoding="utf-8"))

        for path in self._iter_events():
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                kind = self._apply(reg, ledger, envelope)
                stats["accepted"] += 1
                stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1
                if kind == "sleep.trigger":
                    pending.update(envelope.get("payload", {}).get("answers") or {})
                shutil.move(str(path), str(self.archive / path.name))
            except Exception as exc:  # 单条坏事件不阻断整批
                stats["rejected"] += 1
                self._atomic_write(
                    self.rejected / (path.stem + ".error.json"),
                    {"file": path.name, "error": f"{type(exc).__name__}: {exc}"},
                )
                shutil.move(str(path), str(self.rejected / path.name))

        self.save(reg, ledger, store)
        if pending:
            self._atomic_write(self.pending_path, pending)
        self._write_status(reg, stats)
        return stats

    def _apply(self, reg: LearningRegistry, ledger: HobbyLedger, env: dict[str, Any]) -> str:
        if env.get("protocol") != PROTOCOL:
            raise ValueError(f"协议版本不匹配：{env.get('protocol')!r}")
        kind = env.get("kind")
        if kind not in KINDS:
            raise ValueError(f"未知 kind：{kind!r}")
        at = float(env.get("at") or time.time())
        p = env.get("payload") or {}

        if kind == "note":
            reg.add_node(
                p["domain"],
                p["statement"],
                p.get("source", "agent_note"),
                tags=tuple(p.get("tags") or ()),
                at=at,
            )
        elif kind == "restatement":
            reg.restate(p["node_id"], p["text"], bool(p.get("passed", True)), at=at)
        elif kind == "transfer":
            reg.record_transfer(p["node_id"], p["context"], at=at)
        elif kind == "hobby.observe":
            ledger.observe_content(
                p["hobby_id"],
                p["content_id"],
                list(p.get("notes") or []),
                at=at,
                name=p.get("name"),
            )
        elif kind == "hobby.solo":
            ledger.record_solo_session(
                p["hobby_id"], float(p["seconds"]), at=at, notes=tuple(p.get("notes") or ())
            )
        elif kind == "hobby.shared":
            ledger.record_shared_session(
                p["hobby_id"],
                initiated_by_agent=bool(p.get("initiated_by_agent", True)),
                emotional_weight=float(p.get("emotional_weight", 1.0)),
                at=at,
                name=p.get("name"),
            )
        elif kind == "hobby.brake":
            ledger.brake(p["hobby_id"], p["reason"], factor=p.get("factor"), at=at)
        else:  # sleep.trigger —— 真正的结算在 settle()，这里只登记
            pass
        return str(kind)

    def _write_status(self, reg: LearningRegistry, stats: dict[str, Any]) -> None:
        self._atomic_write(
            self.outbox / "status.json",
            {
                "protocol": PROTOCOL,
                "generated_at": time.time(),
                "last_ingest": stats,
                "stats": reg.stats(),
            },
        )

    # -- settle ------------------------------------------------------------ #

    def settle(self, *, at: Optional[float] = None, cycles: int = 1) -> dict[str, Any]:
        """跑睡眠周期。作答来自 ``state/pending_answers.json``（由 sleep.trigger 落下）。"""
        reg, ledger, store = self.open()
        answers: dict[str, str] = {}
        if self.pending_path.exists():
            answers = json.loads(self.pending_path.read_text(encoding="utf-8"))

        engine = ConsolidationEngine(
            cfg=reg.cfg,
            verifier=keyword_verifier,
            answerer_for=lambda node, prompt: answers.get(node.node_id, ""),
        )
        base = float(at if at is not None else time.time())
        commits = []
        for i in range(max(1, cycles)):
            run = engine.run_cycle(reg, at=base + i * 12 * 3600.0)
            commits.append(run.report())

        self.save(reg, ledger, store)
        if self.pending_path.exists():
            self.pending_path.unlink()
        self._write_status(reg, {"settle_cycles": len(commits)})
        return {"cycles": commits, "persona": reg.persona_total}

    # -- project ----------------------------------------------------------- #

    def project(self, *, at: Optional[float] = None) -> dict[str, Any]:
        reg, ledger, store = self.open()
        ts = float(at if at is not None else time.time())
        payload = {
            "protocol": PROTOCOL,
            "generated_at": ts,
            "mulling": reg.recently_mulling(limit=5),
            "persona": reg.persona_total,
            "hobbies": [
                {
                    "hobby_id": p.hobby_id,
                    "name": p.name,
                    "status": p.status.value,
                    "equivalent_itch": round(p.equivalent_itch, 4),
                    "solo_depth": p.solo_depth,
                    "solo_trials": p.solo_trials,
                    "shared_weight": round(p.shared_weight, 4),
                }
                for p in ledger.project(ts)
            ],
            "stats": reg.stats(ts),
        }
        store.close()
        self._atomic_write(self.outbox / "projection.json", payload)
        return payload

    # -- 事件写入（演示与自测用） ------------------------------------------- #

    def emit(self, kind: str, payload: dict[str, Any], *, at: Optional[float] = None, seq: int = 0) -> Path:
        self.init()
        stamp = float(at if at is not None else time.time())
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(f"{kind}|{stamp}|{body}".encode("utf-8")).hexdigest()[:8]
        event_id = f"evt-{seq:06d}-{digest}"
        path = self.intake / f"{seq:06d}-{event_id}.json"
        self._atomic_write(
            path,
            {
                "protocol": PROTOCOL,
                "event_id": event_id,
                "kind": kind,
                "at": stamp,
                "payload": payload,
            },
        )
        return path

    def status(self) -> dict[str, Any]:
        reg, ledger, store = self.open()
        out = reg.stats()
        out["hobbies"] = [
            {"hobby_id": p.hobby_id, "status": p.status.value, "itch": round(p.equivalent_itch, 4)}
            for p in ledger.project()
        ]
        out["intake_pending"] = len(self._iter_events())
        out["archive"] = len(list(self.archive.glob("*.json")))
        out["rejected"] = len(list(self.rejected.glob("*.json")))
        store.close()
        return out


# --------------------------------------------------------------------------- #
# 演示：虚构数据，端到端跑一遍
# --------------------------------------------------------------------------- #

T0 = 1_800_000_000.0
H = 3600.0


def run_demo(data_dir: str) -> None:
    br = Bridge(data_dir)
    if br.root.exists():
        shutil.rmtree(br.root)
    br.init()

    print("=" * 70)
    print("DSH 桥接演示（虚构数据，固定时间戳）")
    print("=" * 70)
    print(f"data dir: {br.root}")

    br.emit(
        "note",
        {
            "domain": "基础园艺",
            "statement": "浇水要看土壤干湿而不是固定天数",
            "source": "agent_note",
        },
        at=T0,
        seq=1,
    )
    br.emit(
        "note",
        {
            "domain": "基础烹饪",
            "statement": "低温慢煮的核心是把温度稳定在蛋白质变性区间",
            "source": "agent_note",
        },
        at=T0,
        seq=2,
    )
    print(f"\n[1] 写入 2 条 note 事件 → {br.intake.name}/")
    print(f"    ingest: {br.ingest()}")

    reg, _, store = br.open()
    ids = {n.domain: n.node_id for n in reg.nodes()}
    store.close()
    for i, (domain, nid) in enumerate(ids.items(), start=3):
        br.emit("restatement", {"node_id": nid, "text": "自己复述了一遍", "passed": True}, at=T0 + H, seq=i)
    br.emit("transfer", {"node_id": ids["基础园艺"], "context": "practice: 换盆后按土干湿浇水"}, at=T0 + 2 * H, seq=10)
    br.emit("transfer", {"node_id": ids["基础烹饪"], "context": "practice: 65℃ 慢煮 45 分钟"}, at=T0 + 2 * H, seq=11)
    print(f"\n[2] 写入复述与迁移事件")
    print(f"    ingest: {br.ingest()}")

    answers = {
        ids["基础园艺"]: "浇水看土壤的干湿状态，不要按固定天数",
        ids["基础烹饪"]: "温度稳定在蛋白质变性区间，别追求更高温度",
    }

    print("\n[3] 睡眠结算（每次先投 sleep.trigger，再 ingest + settle）")
    for i, at in enumerate((T0 + 4 * H, T0 + 16 * H, T0 + 28 * H), start=1):
        br.emit(
            "sleep.trigger",
            {"answers": answers, "verifier": "keyword"},
            at=at,
            seq=20 + i,
        )
        br.ingest()
        out = br.settle(at=at)
        cyc = out["cycles"][0]
        print(
            f"    周期 {i}: 复核 {cyc['reviewed']} · 晋升 {cyc['promoted'] or '—'} "
            f"· 回退 {cyc['demoted'] or '—'} · 投影 {len(cyc['deltas'])}"
        )

    print("\n[4] 投影 → outbox/projection.json")
    proj = br.project(at=T0 + 30 * H)
    for row in proj["mulling"]:
        print(f"    [{row['stage']}] {row['domain']} · {row['statement']}")
    print(f"    人格: {proj['persona'] or '{} （还没有 S4）'}")
    print(f"    阶段分布: {proj['stats']['stages']}")

    print("\n[5] status")
    print(json.dumps(br.status(), ensure_ascii=False, indent=2))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CogniSeed ↔ DSH 插件文件桥接")
    ap.add_argument("command", choices=["init", "ingest", "settle", "project", "status", "demo"])
    ap.add_argument("--data", default="./tmp-bridge", help="数据目录")
    ap.add_argument("--at", type=float, default=None, help="结算时刻（Unix 秒）")
    ap.add_argument("--cycles", type=int, default=1, help="结算几个睡眠周期")
    args = ap.parse_args(argv)

    if args.command == "demo":
        run_demo(args.data)
        return 0

    br = Bridge(args.data)
    if args.command == "init":
        br.init()
        print(f"initialized: {br.root}")
    elif args.command == "ingest":
        print(json.dumps(br.ingest(), ensure_ascii=False, indent=2))
    elif args.command == "settle":
        print(json.dumps(br.settle(at=args.at, cycles=args.cycles), ensure_ascii=False, indent=2))
    elif args.command == "project":
        print(json.dumps(br.project(at=args.at), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(br.status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
