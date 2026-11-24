"""S1 感知 → S2 复述 → S3 巩固 → S4 掌握 的状态机。

设计上只有一条向上通道，且每一级都有明确闸门；不达标就停在原地——这是
「假成长」在本库里的物理不可能性来源。判据的**证据**由 ``consolidation``
算出来，装进 :class:`PromotionEvidence` 递进来；本模块只管状态迁移，
因此依赖方向单一（models ← ladder ← consolidation）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .models import (
    CogniSeedError,
    KnowledgeNode,
    PersonaDelta,
    SleepScheduleConfig,
    Stage,
)

__all__ = ["PromotionEvidence", "Transition", "Ladder", "STAGE_FLOW"]

#: 供 README / 文档引用的一条表，避免文档与代码各写一份。
STAGE_FLOW: tuple[tuple[str, str, str], ...] = (
    ("S1", "感知", "摄入一条原子知识点（来源仅 agent_note / behavior_log）"),
    ("S2", "复述", "自己复述通过：restatements ≥ 1 且 passed"),
    ("S3", "巩固", "进入睡眠巩固队列并被至少 1 个周期复核（sleep_cycles ≥ 1）"),
    ("S4", "掌握", "判据 A ∧ B ∧ C ∧ 变式练习，全部满足才允许"),
)


@dataclass(frozen=True)
class PromotionEvidence:
    """晋升 S4 所需的全部证据（由 consolidation 计算并传入）。"""

    retention: float
    sleep_cycles: int
    variations_passed: int
    blind_test_passes: int
    transfers: int
    retention_floor: float = 0.70
    min_sleep_cycles: int = 2

    # -- 三判据 ---------------------------------------------------------- #

    @property
    def criterion_a(self) -> bool:
        """A：留存 ≥ 0.70（阈值可配）且经过 ≥ 2 个睡眠周期。"""
        return (
            self.retention >= self.retention_floor
            and self.sleep_cycles >= self.min_sleep_cycles
        )

    @property
    def criterion_b(self) -> bool:
        """B：延迟盲测通过 ≥ 1 次（语义校验由调用方回调判定）。"""
        return self.blind_test_passes >= 1

    @property
    def criterion_c(self) -> bool:
        """C：行为日志里至少 1 条应用/迁移留痕。"""
        return self.transfers >= 1

    @property
    def variation_drill(self) -> bool:
        """变式练习：至少 1 次换表述复述通过，治「只会背原句」。"""
        return self.variations_passed >= 1

    @property
    def all_passed(self) -> bool:
        return self.criterion_a and self.criterion_b and self.criterion_c and self.variation_drill

    def blocked_reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.criterion_a:
            reasons.append(
                f"A 未过：留存 {self.retention:.3f} / 阈值 {self.retention_floor:.2f}，"
                f"睡眠周期 {self.sleep_cycles} / 需 {self.min_sleep_cycles}"
            )
        if not self.criterion_b:
            reasons.append(f"B 未过：延迟盲测通过 {self.blind_test_passes} 次，需 ≥ 1")
        if not self.criterion_c:
            reasons.append(f"C 未过：行为迁移留痕 {self.transfers} 条，需 ≥ 1")
        if not self.variation_drill:
            reasons.append(f"变式练习未过：{self.variations_passed} 次，需 ≥ 1")
        return reasons

    def to_dict(self) -> dict[str, object]:
        return {
            "retention": round(self.retention, 6),
            "sleep_cycles": self.sleep_cycles,
            "variations_passed": self.variations_passed,
            "blind_test_passes": self.blind_test_passes,
            "transfers": self.transfers,
            "criterion_a": self.criterion_a,
            "criterion_b": self.criterion_b,
            "criterion_c": self.criterion_c,
            "variation_drill": self.variation_drill,
            "all_passed": self.all_passed,
        }


@dataclass(frozen=True)
class Transition:
    """一次迁移判定结果。``changed`` 为 False 时表示原地不动。"""

    node_id: str
    from_stage: Stage
    to_stage: Stage
    changed: bool
    allowed: bool
    reasons: tuple[str, ...] = ()
    evidence: Optional[PromotionEvidence] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "from": self.from_stage.code,
            "to": self.to_stage.code,
            "changed": self.changed,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
        }


class Ladder:
    """阶段状态机。无状态服务，可复用于任意学籍表。"""

    def __init__(self, cfg: Optional[SleepScheduleConfig] = None) -> None:
        self.cfg = cfg or SleepScheduleConfig.default()

    # -- 闸门 -------------------------------------------------------------- #

    def next_requirement(self, node: KnowledgeNode) -> str:
        return {
            Stage.S1_PERCEIVE: "S1→S2：需要 1 次通过的复述",
            Stage.S2_RESTATE: "S2→S3：需要进入睡眠巩固队列并复核 ≥ 1 次",
            Stage.S3_CONSOLIDATE: "S3→S4：需要判据 A∧B∧C + 变式练习全部通过",
            Stage.S4_MASTERED: "已掌握；只做维持性复核，不再上移",
        }[node.stage]

    def can_advance(self, node: KnowledgeNode, evidence: Optional[PromotionEvidence] = None) -> tuple[bool, list[str]]:
        if node.frozen:
            return False, ["节点已冻结"]
        if node.stage is Stage.S1_PERCEIVE:
            ok = node.restatements >= 1 and node.restated_ok
            return ok, [] if ok else ["S1→S2：还没有通过的复述"]
        if node.stage is Stage.S2_RESTATE:
            ok = node.sleep_cycles >= 1
            return ok, [] if ok else ["S2→S3：还没有经历过睡眠周期"]
        if node.stage is Stage.S3_CONSOLIDATE:
            if evidence is None:
                return False, ["S3→S4：缺少判据证据"]
            return evidence.all_passed, evidence.blocked_reasons()
        return False, ["已在 S4"]

    # -- 迁移 -------------------------------------------------------------- #

    def transition(
        self,
        node: KnowledgeNode,
        evidence: Optional[PromotionEvidence],
        *,
        at: float,
    ) -> Transition:
        """尝试向上迁移一级。最多走一步——不跳级。"""
        before = node.stage
        ok, reasons = self.can_advance(node, evidence)
        if not ok:
            return Transition(
                node_id=node.node_id,
                from_stage=before,
                to_stage=before,
                changed=False,
                allowed=False,
                reasons=tuple(reasons),
                evidence=evidence,
            )
        target = Stage(int(before) + 1)
        node.stage = target
        if target is Stage.S3_CONSOLIDATE and node.s3_since is None:
            node.s3_since = at
        if target is Stage.S4_MASTERED:
            node.s4_at = at
            node.retention = min(1.0, node.retention)
        return Transition(
            node_id=node.node_id,
            from_stage=before,
            to_stage=target,
            changed=True,
            allowed=True,
            reasons=(),
            evidence=evidence,
        )

    def demote(self, node: KnowledgeNode, *, at: float, reason: str) -> Transition:
        """回退一级。留存跌破地板或反装懂纠偏时使用。"""
        before = node.stage
        if before is Stage.S1_PERCEIVE:
            return Transition(
                node_id=node.node_id,
                from_stage=before,
                to_stage=before,
                changed=False,
                allowed=False,
                reasons=(f"已在 S1，无法回退：{reason}",),
            )
        target = Stage(int(before) - 1)
        node.stage = target
        if target is Stage.S3_CONSOLIDATE and node.s3_since is None:
            node.s3_since = at
        if before is Stage.S4_MASTERED:
            node.s4_at = None
        return Transition(
            node_id=node.node_id,
            from_stage=before,
            to_stage=target,
            changed=True,
            allowed=True,
            reasons=(reason,),
        )

    # -- 人格投影 ---------------------------------------------------------- #

    def persona_delta(self, node: KnowledgeNode, *, at: float) -> PersonaDelta:
        """S4 节点 → 人格增量事件。非 S4 直接抛错（冻结空转漂移）。"""
        if node.stage is not Stage.S4_MASTERED:
            raise CogniSeedError(
                f"{node.node_id} 处于 {node.stage.code}，人格增量只由 S4 产出"
            )
        magnitude = 0.01 * (1 + node.blind_test_passes + len(node.transfer_refs))
        delta = round(min(0.05, magnitude) * node.retention, 6)
        return PersonaDelta(
            node_id=node.node_id,
            domain=node.domain,
            trait=node.domain,
            delta=delta,
            emitted_at=at,
            evidence=tuple(node.transfer_refs),
        )

    def describe(self) -> list[dict[str, str]]:
        return [{"stage": s, "name": n, "gate": g} for s, n, g in STAGE_FLOW]
