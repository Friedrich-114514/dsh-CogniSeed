"""学籍表：同心圆领域 · 活跃池（上限 5）· 每日新增配额（2）· 只读投影。

这里是**唯一**允许写入知识点的地方。所有写入都要过来源白名单——原始聊天记录
永远进不来（隐私硬线，见 ``docs/05-anti-hallucination.md``）。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Sequence

from .models import (
    ALLOWED_SOURCES,
    FORBIDDEN_SOURCES,
    BlindTestResult,
    Clock,
    CogniSeedError,
    DomainRing,
    KnowledgeNode,
    PersonaDelta,
    PoolFull,
    PrivacyViolation,
    QuotaExceeded,
    Restatement,
    SleepCycle,
    SleepScheduleConfig,
    SourceKind,
    Stage,
    TransferRecord,
    clamp01,
    day_key,
    now as _now,
    stable_id,
)

__all__ = ["LearningRegistry"]

_META_KEY = "registry:meta"
_NODE_PREFIX = "node:"
_CYCLE_PREFIX = "cycle:"


def normalize_source(source: str | SourceKind) -> str:
    """校验并规范化来源。

    - 命中禁止名单（原始聊天）→ :class:`PrivacyViolation`
    - 不在白名单 → :class:`PrivacyViolation`（默认拒绝，而不是默认放行）
    """
    value = source.value if isinstance(source, SourceKind) else str(source).strip().lower()
    if value in FORBIDDEN_SOURCES:
        raise PrivacyViolation(
            f"来源 {value!r} 属禁止回溯的用户原始聊天，拒绝入库；"
            f"只接受 {list(ALLOWED_SOURCES)}"
        )
    if value not in ALLOWED_SOURCES:
        raise PrivacyViolation(
            f"来源 {value!r} 不在白名单 {list(ALLOWED_SOURCES)}"
        )
    return value


class LearningRegistry:
    """一个 CompanionAgent 的学籍表。"""

    def __init__(
        self,
        cfg: Optional[SleepScheduleConfig] = None,
        *,
        store: Any = None,
        clock: Optional[Clock] = None,
        agent_name: str = "CompanionAgent",
    ) -> None:
        self.cfg = cfg or SleepScheduleConfig.default()
        self.store = store
        self.clock: Clock = clock or _now
        self.agent_name = agent_name

        self._nodes: dict[str, KnowledgeNode] = {}
        self._pool: list[str] = []                       # 最近活跃在前
        self._daily_new: dict[str, int] = {}             # day_key -> 新增计数
        self._restatements: list[Restatement] = []
        self._blind_tests: list[BlindTestResult] = []
        self._transfers: list[TransferRecord] = []
        self._corrections: list[dict[str, Any]] = []
        self._cycles: list[SleepCycle] = []
        self._deltas: list[PersonaDelta] = []
        self._pool_evictions: list[dict[str, Any]] = []
        self._delta_emitted: set[str] = set()

    # ------------------------------------------------------------------ #
    # 时钟与配额
    # ------------------------------------------------------------------ #

    def now(self) -> float:
        return float(self.clock())

    def quota_used(self, at: Optional[float] = None) -> int:
        return self._daily_new.get(day_key(at if at is not None else self.now()), 0)

    def quota_remaining(self, at: Optional[float] = None) -> int:
        return max(0, self.cfg.daily_new_quota - self.quota_used(at))

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #

    def add_node(
        self,
        domain: str,
        statement: str,
        source: str | SourceKind = SourceKind.AGENT_NOTE,
        *,
        tags: Sequence[str] = (),
        at: Optional[float] = None,
        node_id: Optional[str] = None,
    ) -> KnowledgeNode:
        """摄入一个原子知识点。

        约束顺序：来源白名单 → 同键去重 → 当日配额 → 活跃池入池。
        去重先于配额，因此重放同一条不会白白吃掉配额。
        """
        src = normalize_source(source)
        ts = at if at is not None else self.now()
        domain = domain.strip()
        statement = statement.strip()
        if not domain:
            raise CogniSeedError("domain 不能为空")
        if not statement:
            raise CogniSeedError("statement 不能为空")

        nid = node_id or stable_id("kn", domain, statement)
        if nid in self._nodes:
            return self._nodes[nid]

        if self.quota_remaining(ts) <= 0:
            raise QuotaExceeded(
                f"{day_key(ts)} 的新增配额 {self.cfg.daily_new_quota} 已用尽；"
                "配额按自然日（UTC）重置"
            )

        node = KnowledgeNode(
            node_id=nid,
            domain=domain,
            statement=statement,
            source=src,
            created_at=ts,
            last_review_at=ts,
            tags=list(tags),
        )
        self._nodes[nid] = node
        key = day_key(ts)
        self._daily_new[key] = self._daily_new.get(key, 0) + 1
        self._enter_pool(domain, ts)
        return node

    def restate(
        self, node_id: str, text: str, passed: bool, *, at: Optional[float] = None
    ) -> Restatement:
        """记录 S2 复述。判据层不在这里，这里只留痕 + 打标。"""
        node = self.get(node_id)
        ts = at if at is not None else self.now()
        rec = Restatement(node_id=node_id, text=text, at=ts, passed=bool(passed))
        self._restatements.append(rec)
        node.restatements += 1
        node.restated_ok = node.restated_ok or bool(passed)
        node.last_review_at = ts
        return rec

    def record_blind_test(self, result: BlindTestResult) -> None:
        self._blind_tests.append(result)
        node = self.get(result.node_id)
        if result.passed:
            node.blind_test_passes += 1
            node.restated_ok = True
        else:
            node.blind_test_fails += 1

    def record_transfer(
        self, node_id: str, context: str, *, at: Optional[float] = None
    ) -> TransferRecord:
        """判据 C：行为日志里的应用/迁移证据。"""
        node = self.get(node_id)
        ts = at if at is not None else self.now()
        rec = TransferRecord(node_id=node_id, context=context, at=ts)
        self._transfers.append(rec)
        if rec.context not in node.transfer_refs:
            node.transfer_refs.append(rec.context)
        node.last_review_at = max(node.last_review_at, ts)
        return rec

    def record_correction(
        self, node_id: str, reason: str, *, penalty: float = 0.85, at: Optional[float] = None
    ) -> dict[str, Any]:
        """反装懂纠偏留痕：降留存、计次。阶段回退由调用方（anti_cheat）决定。"""
        node = self.get(node_id)
        ts = at if at is not None else self.now()
        before = node.retention
        node.retention = clamp01(before * penalty)
        node.corrections += 1
        entry = {
            "node_id": node_id,
            "reason": reason,
            "at": ts,
            "retention_before": round(before, 6),
            "retention_after": round(node.retention, 6),
            "corrections": node.corrections,
        }
        self._corrections.append(entry)
        return entry

    def record_cycle(self, cycle: SleepCycle) -> None:
        self._cycles.append(cycle)

    def emit_delta(self, delta: PersonaDelta) -> bool:
        """接收人格增量事件。同一节点只投影一次，杜绝重复漂移。"""
        if delta.node_id in self._delta_emitted:
            return False
        self._delta_emitted.add(delta.node_id)
        self._deltas.append(delta)
        return True

    def set_stage(self, node_id: str, stage: Stage, *, at: Optional[float] = None) -> None:
        """底层阶段写入。业务代码请走 ``Ladder``。"""
        node = self.get(node_id)
        node.stage = Stage(int(stage))
        ts = at if at is not None else self.now()
        if node.stage is Stage.S3_CONSOLIDATE and node.s3_since is None:
            node.s3_since = ts
        if node.stage is Stage.S4_MASTERED and node.s4_at is None:
            node.s4_at = ts

    # ------------------------------------------------------------------ #
    # 活跃池与同心圆
    # ------------------------------------------------------------------ #

    def _enter_pool(self, domain: str, ts: float) -> None:
        if domain in self._pool:
            self._pool.remove(domain)
            self._pool.insert(0, domain)
            return
        if len(self._pool) >= self.cfg.max_active_pool:
            evicted = self._pool.pop()
            self._pool_evictions.append({"domain": evicted, "at": ts, "by": domain})
        self._pool.insert(0, domain)

    @property
    def active_pool(self) -> list[str]:
        """当前活跃领域，最近活跃在前，长度 ≤ ``max_active_pool``（默认 5）。"""
        return list(self._pool)

    @property
    def pool_evictions(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._pool_evictions]

    def rings(self) -> dict[str, DomainRing]:
        """同心圆分层：按该领域已掌握（S4）知识点数定圈。"""
        mastered: dict[str, int] = {}
        for node in self._nodes.values():
            if node.stage is Stage.S4_MASTERED:
                mastered[node.domain] = mastered.get(node.domain, 0) + 1
        out: dict[str, DomainRing] = {}
        for domain in self.domains():
            n = mastered.get(domain, 0)
            out[domain] = (
                DomainRing.INNER if n >= 3 else DomainRing.MIDDLE if n >= 1 else DomainRing.OUTER
            )
        return out

    def domains(self) -> list[str]:
        seen: list[str] = []
        for node in self._nodes.values():
            if node.domain not in seen:
                seen.append(node.domain)
        return sorted(seen)

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #

    def get(self, node_id: str) -> KnowledgeNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise CogniSeedError(f"学籍表里没有节点 {node_id!r}") from None

    def find(self, node_id: str) -> Optional[KnowledgeNode]:
        return self._nodes.get(node_id)

    def nodes(self, domain: Optional[str] = None, stage: Optional[Stage] = None) -> list[KnowledgeNode]:
        rows = list(self._nodes.values())
        if domain is not None:
            rows = [n for n in rows if n.domain == domain]
        if stage is not None:
            rows = [n for n in rows if n.stage is Stage(int(stage))]
        return sorted(rows, key=lambda n: (n.domain, n.created_at, n.node_id))

    def by_stage(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {s.code: [] for s in Stage}
        for node in self.nodes():
            out[node.stage.code].append(node.node_id)
        return out

    def recently_mulling(self, limit: int = 5) -> list[dict[str, Any]]:
        """「最近在琢磨的事」——只读投影。

        只投影活跃池内仍处于 S1–S3 的节点，按最近触碰时间倒序。调用方拿不到
        任何写句柄，因此这条投影不可能反过来污染学籍表。
        """
        pool = set(self._pool)
        rows = [
            n
            for n in self._nodes.values()
            if n.domain in pool and n.stage is not Stage.S4_MASTERED
        ]
        rows.sort(key=lambda n: (-n.last_review_at, -int(n.stage), n.node_id))
        return [
            {
                "node_id": n.node_id,
                "domain": n.domain,
                "statement": n.statement,
                "stage": n.stage.code,
                "stage_label": n.stage.label,
                "retention": round(n.retention, 4),
                "sleep_cycles": n.sleep_cycles,
            }
            for n in rows[: max(0, limit)]
        ]

    def persona_projection(self) -> list[dict[str, Any]]:
        """人格增量的只读视图。空列表 = 没有沉淀，一分不涨。"""
        return [d.to_dict() for d in self._deltas]

    @property
    def persona_total(self) -> dict[str, float]:
        total: dict[str, float] = {}
        for d in self._deltas:
            total[d.domain] = round(total.get(d.domain, 0.0) + d.delta, 6)
        return total

    @property
    def cycles(self) -> list[SleepCycle]:
        return list(self._cycles)

    @property
    def corrections(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._corrections]

    @property
    def transfers(self) -> list[TransferRecord]:
        return list(self._transfers)

    @property
    def blind_tests(self) -> list[BlindTestResult]:
        return list(self._blind_tests)

    def stats(self, at: Optional[float] = None) -> dict[str, Any]:
        ts = at if at is not None else self.now()
        stages = {s.code: 0 for s in Stage}
        for node in self._nodes.values():
            stages[node.stage.code] += 1
        return {
            "agent": self.agent_name,
            "nodes": len(self._nodes),
            "stages": stages,
            "domains": len(self.domains()),
            "active_pool": self.active_pool,
            "pool_capacity": self.cfg.max_active_pool,
            "quota_used_today": self.quota_used(ts),
            "quota_remaining_today": self.quota_remaining(ts),
            "sleep_cycles": len(self._cycles),
            "deltas": len(self._deltas),
            "corrections": len(self._corrections),
            "rings": {d: r.label for d, r in self.rings().items()},
        }

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[KnowledgeNode]:
        return iter(self.nodes())

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def to_state(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "cfg": self.cfg.to_dict(),
            "nodes": {k: v.to_dict() for k, v in self._nodes.items()},
            "pool": list(self._pool),
            "daily_new": dict(self._daily_new),
            "cycles": [c.to_dict() for c in self._cycles],
            "deltas": [d.to_dict() for d in self._deltas],
            "pool_evictions": [dict(e) for e in self._pool_evictions],
            "delta_emitted": sorted(self._delta_emitted),
            "corrections": [dict(c) for c in self._corrections],
        }

    def persist(self, store: Any = None) -> int:
        """把学籍表写进后端。返回写入行数。"""
        # 不能用 `store or self.store`——空后端 __len__ 为 0，会被当成假值
        st = store if store is not None else self.store
        if st is None:
            raise CogniSeedError("没有可用 store；构造时传入或 persist(store=...)")
        st.save(_META_KEY, self.to_state())
        for node in self._nodes.values():
            st.save(_NODE_PREFIX + node.node_id, node.to_dict())
        for cycle in self._cycles:
            st.save(_CYCLE_PREFIX + cycle.cycle_id, cycle.to_dict())
        return 1 + len(self._nodes) + len(self._cycles)

    @classmethod
    def load(cls, store: Any, *, clock: Optional[Clock] = None) -> "LearningRegistry":
        """从后端恢复。节点表以 ``node:`` 前缀行重建，meta 行提供池与配额。"""
        meta = store.load(_META_KEY)
        if meta is None:
            raise CogniSeedError("store 里没有 registry:meta，无法恢复")
        cfg = SleepScheduleConfig(**meta["cfg"])
        reg = cls(cfg=cfg, store=store, clock=clock, agent_name=meta.get("agent_name", "CompanionAgent"))
        for key in store.keys():
            k = str(key)
            if k.startswith(_NODE_PREFIX):
                payload = store.load(k)
                if payload:
                    node = KnowledgeNode.from_dict(payload)
                    reg._nodes[node.node_id] = node
            elif k.startswith(_CYCLE_PREFIX):
                payload = store.load(k)
                if payload:
                    reg._cycles.append(SleepCycle(**payload))
        reg._pool = list(meta.get("pool", []))
        reg._daily_new = dict(meta.get("daily_new", {}))
        reg._pool_evictions = [dict(e) for e in meta.get("pool_evictions", [])]
        reg._delta_emitted = set(meta.get("delta_emitted", []))
        reg._corrections = [dict(c) for c in meta.get("corrections", [])]
        reg._cycles.sort(key=lambda c: (c.started_at, c.cycle_id))
        for payload in meta.get("deltas", []):
            reg._deltas.append(
                PersonaDelta(
                    node_id=payload["node_id"],
                    domain=payload["domain"],
                    trait=payload["trait"],
                    delta=float(payload["delta"]),
                    emitted_at=float(payload["emitted_at"]),
                    evidence=tuple(payload.get("evidence", ())),
                )
            )
        return reg
