"""睡眠巩固：艾宾浩斯衰减 + 三联判据 A/B/C + 变式练习。

判据 B 与反装懂探针的语义校验走**纯回调**：``Verifier = Callable[[str, str], bool]``，
接入方自己传（可以用任意 LLM、规则引擎或人），核心库不内置任何客户端，
因此这里零第三方依赖。

用法::

    engine = ConsolidationEngine(verifier=my_judge, answerer=my_agent)
    run = engine.run_cycle(registry, at=now)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .ladder import Ladder, PromotionEvidence, Transition
from .models import (
    Answerer,
    AnswererFor,
    BlindTestResult,
    Clock,
    CogniSeedError,
    KnowledgeNode,
    PersonaDelta,
    SleepCycle,
    SleepScheduleConfig,
    Stage,
    Verifier,
    clamp01,
    now as _now,
    stable_id,
)

__all__ = [
    "retention_at",
    "refresh",
    "variation_drills",
    "blind_prompt",
    "evidence_for",
    "SleepRun",
    "ConsolidationEngine",
]


# --------------------------------------------------------------------------- #
# 衰减与再巩固
# --------------------------------------------------------------------------- #


def retention_at(node: KnowledgeNode, at: float, cfg: SleepScheduleConfig) -> float:
    """艾宾浩斯式留存估计：R(t) = R0 · exp(-Δt / S)。

    稳定性 S 随「盲测通过次数」和「已过睡眠周期数」增长——复习不是把数字
    加回去，而是让曲线变缓。``R0`` 是上次复核后的留存，``Δt`` 为小时数。
    """
    elapsed_h = max(0.0, (at - node.last_review_at) / 3600.0)
    stability = (
        cfg.base_stability_hours
        * (1.0 + cfg.stability_growth * node.blind_test_passes)
        * (1.0 + 0.25 * node.sleep_cycles)
    )
    if stability <= 0.0:
        return 0.0
    return clamp01(node.retention * math.exp(-elapsed_h / stability))


def refresh(node: KnowledgeNode, at: float, cfg: SleepScheduleConfig) -> float:
    """一次睡眠复核：先按曲线衰减，再按 ``review_gain`` 做再巩固增益。

    返回复核后的留存。``sleep_cycles`` 自增——它是判据 A 的一项。
    """
    decayed = retention_at(node, at, cfg)
    regained = decayed + cfg.review_gain * (1.0 - decayed)
    node.retention = clamp01(regained)
    node.last_review_at = at
    node.sleep_cycles += 1
    return node.retention


# --------------------------------------------------------------------------- #
# 变式练习与盲测
# --------------------------------------------------------------------------- #


def variation_drills(node: KnowledgeNode) -> list[str]:
    """由知识点确定性生成变式练习提示词（不调模型，纯模板）。

    三条分别治：只会背原句 / 无法举例 / 不知道边界。
    """
    s = node.statement
    return [
        f"换一种说法复述这条知识，不要用原句：{s}",
        f"举一个具体例子说明这条知识在实践中怎么用：{s}",
        f"什么情况下这条知识不成立或要打折？如果不能确定，直接说没有记录：{s}",
    ]


def blind_prompt(node: KnowledgeNode, delay_hours: float = 0.0) -> str:
    """延迟盲测提示词：不给原句，只给问题。"""
    tag = f"（距上次学习约 {delay_hours:.0f} 小时）" if delay_hours >= 1 else ""
    return f"{tag}不看笔记，说出「{node.domain}」里这条知识的关键要点。"


def evidence_for(node: KnowledgeNode, cfg: SleepScheduleConfig) -> PromotionEvidence:
    return PromotionEvidence(
        retention=node.retention,
        sleep_cycles=node.sleep_cycles,
        variations_passed=node.variations_passed,
        blind_test_passes=node.blind_test_passes,
        transfers=len(node.transfer_refs),
        retention_floor=cfg.retention_floor,
        min_sleep_cycles=cfg.min_sleep_cycles,
    )


# --------------------------------------------------------------------------- #
# 周期结果
# --------------------------------------------------------------------------- #


@dataclass
class SleepRun:
    """一次睡眠结算的完整账。"""

    cycle: SleepCycle
    transitions: list[Transition] = field(default_factory=list)
    deltas: list[PersonaDelta] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def promoted(self) -> list[str]:
        return list(self.cycle.promoted)

    @property
    def demoted(self) -> list[str]:
        return list(self.cycle.demoted)

    def report(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle.cycle_id,
            "reviewed": len(self.cycle.reviewed),
            "promoted": self.cycle.promoted,
            "demoted": self.cycle.demoted,
            "skipped": self.skipped,
            "deltas": [d.to_dict() for d in self.deltas],
            "notes": self.cycle.notes,
        }


# --------------------------------------------------------------------------- #
# 引擎
# --------------------------------------------------------------------------- #


class ConsolidationEngine:
    """跑一个睡眠周期：衰减 → 再巩固 → 变式 → 盲测 → 判据 → 迁移 → 投影。"""

    def __init__(
        self,
        cfg: Optional[SleepScheduleConfig] = None,
        *,
        verifier: Optional[Verifier] = None,
        answerer: Optional[Answerer] = None,
        answerer_for: Optional[AnswererFor] = None,
        ladder: Optional[Ladder] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self.cfg = cfg or SleepScheduleConfig.default()
        self.verifier = verifier
        self.answerer = answerer
        self.answerer_for = answerer_for
        self.ladder = ladder or Ladder(self.cfg)
        self.clock = clock or _now

    # -- 作答 -------------------------------------------------------------- #

    def _answer(self, node: KnowledgeNode, prompt: str) -> str:
        if self.answerer_for is not None:
            return self.answerer_for(node, prompt)
        if self.answerer is not None:
            return self.answerer(prompt)
        raise CogniSeedError("既没有 answerer 也没有 answerer_for")

    @property
    def _can_drill(self) -> bool:
        return self.verifier is not None and (
            self.answerer is not None or self.answerer_for is not None
        )

    # -- 单节点 ------------------------------------------------------------ #

    def _drill(self, node: KnowledgeNode, at: float, notes: list[str]) -> None:
        """S3 阶段的变式练习 + 延迟盲测。没有回调就什么都不做（不臆造成绩）。"""
        if not self._can_drill:
            notes.append(f"{node.node_id}: 未提供 verifier/answerer，S3 练习跳过")
            return

        if node.variations_passed < 1:
            prompt = variation_drills(node)[0]
            try:
                candidate = self._answer(node, prompt)
                ok = bool(self.verifier(node.statement, candidate))
            except Exception as exc:  # 回调是外部代码，失败按未通过处理
                ok = False
                notes.append(f"{node.node_id}: 变式回调异常 {type(exc).__name__}: {exc}")
            if ok:
                node.variations_passed += 1

        if node.s3_since is None:
            node.s3_since = at
        elapsed_h = (at - node.s3_since) / 3600.0
        if elapsed_h < self.cfg.blind_test_delay_hours:
            return
        if node.blind_test_passes >= 3:  # 已充分证明，不再消耗盲测
            return

        prompt = blind_prompt(node, elapsed_h)
        try:
            candidate = self._answer(node, prompt)
            passed = bool(self.verifier(node.statement, candidate))
        except Exception as exc:
            candidate, passed = "", False
            notes.append(f"{node.node_id}: 盲测回调异常 {type(exc).__name__}: {exc}")
        node.blind_test_passes += 1 if passed else 0
        node.blind_test_fails += 0 if passed else 1
        notes.append(
            f"{node.node_id}: 盲测{'通过' if passed else '未通过'}（延迟 {elapsed_h:.1f}h）"
        )

    # -- 整周期 ------------------------------------------------------------ #

    def run_cycle(self, registry: Any, at: Optional[float] = None) -> SleepRun:
        ts = float(at if at is not None else self.clock())
        cycle = SleepCycle(
            cycle_id=stable_id("cyc", str(ts), str(len(registry.cycles))),
            started_at=ts,
            ended_at=ts,
        )
        run = SleepRun(cycle=cycle)

        for node in registry.nodes():
            if node.frozen:
                cycle.skipped.append(node.node_id)
                run.skipped.append(node.node_id)
                continue

            entry_stage = node.stage
            # 先记下「复核前」的衰减值：回退判定看的是真实遗忘，不是再巩固后的成绩
            decayed = retention_at(node, ts, self.cfg)
            refresh(node, ts, self.cfg)
            cycle.reviewed.append(node.node_id)

            if entry_stage is Stage.S3_CONSOLIDATE:
                self._drill(node, ts, cycle.notes)

            # 晋升（一次最多一级）
            evidence = evidence_for(node, self.cfg) if node.stage is Stage.S3_CONSOLIDATE else None
            tr = self.ladder.transition(node, evidence, at=ts)
            run.transitions.append(tr)
            if tr.changed:
                cycle.promoted.append(node.node_id)
                cycle.notes.append(f"{node.node_id}: {tr.from_stage.code}→{tr.to_stage.code}")

            # S4 投影（同节点只投影一次）
            if node.stage is Stage.S4_MASTERED:
                if node.node_id not in registry._delta_emitted:
                    delta = self.ladder.persona_delta(node, at=ts)
                    if registry.emit_delta(delta):
                        run.deltas.append(delta)

            # 复核前已跌破地板 → 回退（再巩固救得回留存，救不回被证伪的掌握度）
            if decayed < self.cfg.demote_floor and node.stage is not Stage.S1_PERCEIVE:
                dem = self.ladder.demote(
                    node,
                    at=ts,
                    reason=(
                        f"复核前留存 {decayed:.3f} < 地板 {self.cfg.demote_floor:.2f}，"
                        "退回上一级重新巩固"
                    ),
                )
                if dem.changed:
                    cycle.demoted.append(node.node_id)
                    cycle.notes.append(f"{node.node_id}: {dem.from_stage.code}↓{dem.to_stage.code}")

        cycle.ended_at = float(at if at is not None else self.clock())
        registry.record_cycle(cycle)
        return run

    def catch_up(
        self, registry: Any, *, cycles: int, step_hours: float = 12.0, at: Optional[float] = None
    ) -> list[SleepRun]:
        """补跑 N 个周期（示例/演示用）。每个周期间隔 ``step_hours`` 小时。"""
        base = float(at if at is not None else self.clock())
        runs: list[SleepRun] = []
        for i in range(cycles):
            runs.append(self.run_cycle(registry, at=base + i * step_hours * 3600.0))
        return runs
