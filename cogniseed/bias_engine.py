"""偏置引擎：在学池软牵引。

「软」是硬性设计约束：本模块只产出**权重**，不删除、不过滤任何候选。采样带
exploration 比例，所以再热的领域也不会把冷门彻底饿死——否则人格会越走越窄，
最后只会聊那五件事。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from .models import (
    Clock,
    CogniSeedError,
    DomainRing,
    HobbyStatus,
    KnowledgeNode,
    SleepScheduleConfig,
    Stage,
    now as _now,
)

__all__ = ["BiasWeight", "BiasEngine"]

_RING_BONUS = {DomainRing.INNER: 1.15, DomainRing.MIDDLE: 1.05, DomainRing.OUTER: 1.00}
_STAGE_BONUS = {
    Stage.S1_PERCEIVE: 1.00,
    Stage.S2_RESTATE: 1.10,
    Stage.S3_CONSOLIDATE: 1.20,
    Stage.S4_MASTERED: 0.85,
}


@dataclass(frozen=True)
class BiasWeight:
    node_id: str
    domain: str
    stage: str
    retention: float
    weight: float
    ring: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "domain": self.domain,
            "stage": self.stage,
            "retention": round(self.retention, 4),
            "weight": round(self.weight, 4),
            "ring": self.ring,
            "reason": self.reason,
        }


class BiasEngine:
    """把学籍表 + 爱好账本折算成一组采样权重。"""

    def __init__(
        self,
        cfg: Optional[SleepScheduleConfig] = None,
        *,
        exploration: float = 0.15,
        pool_bonus: float = 1.25,
        idle_half_life_days: float = 10.0,
        clock: Optional[Clock] = None,
    ) -> None:
        self.cfg = cfg or SleepScheduleConfig.default()
        self.exploration = max(0.0, min(1.0, exploration))
        self.pool_bonus = pool_bonus
        self.idle_half_life_days = max(0.5, idle_half_life_days)
        self.clock = clock or _now

    def _hobby_bonus(self, node: KnowledgeNode, ledger: Any, at: float) -> tuple[float, str]:
        """领域名与爱好同名（或包含）时，按等效手痒给一个温和加成。"""
        if ledger is None:
            return 1.0, ""
        try:
            projections = ledger.project(at)
        except Exception:
            return 1.0, ""
        for p in projections:
            key = p.name or p.hobby_id
            if key == node.domain or key in node.domain or node.domain in key:
                if p.status is HobbyStatus.DORMANT:
                    return 0.6, f"爱好 {p.hobby_id} 休眠中"
                if p.status is HobbyStatus.DOWNWEIGHTED:
                    return 0.75, f"爱好 {p.hobby_id} 已降权"
                bonus = 1.0 + min(1.0, p.equivalent_itch)
                return bonus, f"爱好 {p.hobby_id} 手痒 {p.equivalent_itch:.2f}"
        return 1.0, ""

    def weights(self, registry: Any, ledger: Any = None, at: Optional[float] = None) -> list[BiasWeight]:
        ts = float(at if at is not None else self.clock())
        rings = registry.rings()
        pool = set(registry.active_pool)
        raw: list[tuple[KnowledgeNode, float, str]] = []

        for node in registry.nodes():
            if node.frozen:
                continue
            ring = rings.get(node.domain, DomainRing.OUTER)
            idle_days = max(0.0, (ts - node.last_review_at) / 86400.0)
            recency = 1.0 / (1.0 + idle_days / self.idle_half_life_days)
            resolved = 0.5 + node.retention
            hobby_bonus, hobby_note = self._hobby_bonus(node, ledger, ts)
            pool_note = "在学池" if node.domain in pool else "池外"
            w = (
                _RING_BONUS[ring]
                * _STAGE_BONUS[node.stage]
                * recency
                * resolved
                * hobby_bonus
                * (self.pool_bonus if node.domain in pool else 1.0)
            )
            reason = "·".join(
                x for x in (pool_note, f"{ring.label}", hobby_note) if x
            )
            raw.append((node, w, reason))

        if not raw:
            return []
        peak = max(w for _, w, _ in raw) or 1.0
        return [
            BiasWeight(
                node_id=n.node_id,
                domain=n.domain,
                stage=n.stage.code,
                retention=n.retention,
                weight=w / peak,
                ring=rings.get(n.domain, DomainRing.OUTER).label,
                reason=reason,
            )
            for n, w, reason in sorted(raw, key=lambda t: (-t[1], t[0].node_id))
        ]

    def sample(
        self,
        registry: Any,
        k: int,
        *,
        ledger: Any = None,
        at: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> list[str]:
        """按权重不放回采样 k 个节点 ID。

        ``exploration`` 比例的槽位走均匀随机，保证冷门领域不被饿死（软牵引，
        不是硬过滤）。
        """
        if k <= 0:
            return []
        rand = rng or random.Random()
        pool = [w for w in self.weights(registry, ledger, at)]
        if not pool:
            return []
        picked: list[str] = []
        remaining = list(pool)
        while remaining and len(picked) < k:
            if rand.random() < self.exploration:
                chosen = rand.choice(remaining)
            else:
                total = sum(w.weight for w in remaining) or 1.0
                point = rand.random() * total
                acc = 0.0
                chosen = remaining[-1]
                for w in remaining:
                    acc += w.weight
                    if point <= acc:
                        chosen = w
                        break
            picked.append(chosen.node_id)
            remaining = [w for w in remaining if w.node_id != chosen.node_id]
        return picked

    def explain(self, registry: Any, node_id: str, ledger: Any = None, at: Optional[float] = None) -> dict[str, Any]:
        for w in self.weights(registry, ledger, at):
            if w.node_id == node_id:
                return w.to_dict()
        raise CogniSeedError(f"节点 {node_id!r} 不在偏置候选里（可能已冻结或不存在）")
