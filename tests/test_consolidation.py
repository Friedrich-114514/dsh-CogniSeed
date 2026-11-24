"""睡眠巩固测试：艾宾浩斯衰减 · 三判据 · 变式练习 · 只读人格投影 · 回退。

判据 B 走纯回调钩子（``Callable[[str, str], bool]``），本文件用两个最朴素的
假实现验证协议本身，不依赖任何 LLM。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogniseed import (
    ConsolidationEngine,
    KnowledgeNode,
    LearningRegistry,
    PromotionEvidence,
    SleepScheduleConfig,
    Stage,
    evidence_for,
    refresh,
    retention_at,
    variation_drills,
)
from cogniseed.ladder import Ladder

T0 = 1_800_000_000.0
H = 3_600.0
DAY = 24 * H

STATEMENT = "低温慢煮的核心是把温度稳定在蛋白质变性区间，而不是追求更高温度"
COSINE_VERIFIER = None  # 占位，真实回调见下


def char_overlap_verifier(expected: str, candidate: str) -> bool:
    """朴素语义校验替身：候选答案与期望的重合字符数 ≥ 8 即算复现。"""
    return len(set(expected) & set(candidate)) >= 8


def echo_answerer(prompt: str) -> str:
    return STATEMENT


def _prepared(cfg=None, with_transfer=True, at=T0):
    reg = LearningRegistry(cfg=cfg or SleepScheduleConfig.default(), clock=lambda: T0)
    node = reg.add_node("基础烹饪", STATEMENT, at=at)
    reg.restate(node.node_id, "温度稳在变性区间，别追求高温", True, at=at + H)
    if with_transfer:
        reg.record_transfer(node.node_id, "practice: 65℃ 慢煮鸡胸 45 分钟", at=at + 2 * H)
    return reg, node


class TestDecay(unittest.TestCase):
    def setUp(self):
        self.cfg = SleepScheduleConfig.default()
        self.node = KnowledgeNode(
            node_id="kn-x",
            domain="基础烹饪",
            statement=STATEMENT,
            source="agent_note",
            created_at=T0,
            last_review_at=T0,
        )

    def test_retention_decays_monotonically(self):
        values = [retention_at(self.node, T0 + h * H, self.cfg) for h in (0, 6, 24, 72, 240)]
        self.assertAlmostEqual(values[0], 1.0, places=6)
        for a, b in zip(values, values[1:]):
            self.assertGreater(a, b)
        self.assertLess(values[-1], 0.05)

    def test_refresh_regains_and_counts_cycle(self):
        before = retention_at(self.node, T0 + 48 * H, self.cfg)
        after = refresh(self.node, T0 + 48 * H, self.cfg)
        self.assertGreater(after, before)
        self.assertEqual(self.node.sleep_cycles, 1)
        self.assertEqual(self.node.last_review_at, T0 + 48 * H)

    def test_stability_grows_with_blind_passes(self):
        plain = KnowledgeNode("kn-a", "d", "s", "agent_note", T0, last_review_at=T0)
        drilled = KnowledgeNode(
            "kn-b", "d", "s", "agent_note", T0, last_review_at=T0, blind_test_passes=3
        )
        t = T0 + 72 * H
        self.assertGreater(
            retention_at(drilled, t, self.cfg), retention_at(plain, t, self.cfg)
        )


class TestCriteria(unittest.TestCase):
    def test_a_needs_both_cycles_and_retention(self):
        ok = PromotionEvidence(0.8, 2, 1, 1, 1)
        self.assertTrue(ok.criterion_a)
        self.assertFalse(PromotionEvidence(0.69, 5, 1, 1, 1).criterion_a)
        self.assertFalse(PromotionEvidence(0.95, 1, 1, 1, 1).criterion_a)

    def test_blocked_reasons_are_specific(self):
        e = PromotionEvidence(0.5, 1, 0, 0, 0)
        text = " ".join(e.blocked_reasons())
        for token in ("A 未过", "B 未过", "C 未过", "变式练习未过"):
            self.assertIn(token, text)
        self.assertFalse(e.all_passed)

    def test_all_four_gates_required(self):
        self.assertTrue(PromotionEvidence(0.9, 3, 1, 1, 1).all_passed)
        self.assertFalse(PromotionEvidence(0.9, 3, 0, 1, 1).all_passed)  # 缺变式
        self.assertFalse(PromotionEvidence(0.9, 3, 1, 0, 1).all_passed)  # 缺盲测
        self.assertFalse(PromotionEvidence(0.9, 3, 1, 1, 0).all_passed)  # 缺迁移

    def test_variation_drills_are_three_and_deterministic(self):
        node = KnowledgeNode("kn-y", "d", STATEMENT, "agent_note", T0)
        drills = variation_drills(node)
        self.assertEqual(len(drills), 3)
        self.assertEqual(drills, variation_drills(node))
        self.assertTrue(all(STATEMENT in d for d in drills))


class TestLadder(unittest.TestCase):
    def test_no_restatement_no_move(self):
        reg, node = _prepared(with_transfer=False)
        node.restatements = 0
        node.restated_ok = False
        ladder = Ladder(reg.cfg)
        tr = ladder.transition(node, None, at=T0)
        self.assertFalse(tr.changed)
        self.assertEqual(node.stage, Stage.S1_PERCEIVE)

    def test_failed_restatement_does_not_open_gate(self):
        reg = LearningRegistry(clock=lambda: T0)
        node = reg.add_node("基础园艺", "浇水看土壤干湿", at=T0)
        reg.restate(node.node_id, "不记得了", False, at=T0 + H)
        ladder = Ladder(reg.cfg)
        tr = ladder.transition(node, None, at=T0 + 2 * H)
        self.assertFalse(tr.changed)
        self.assertIn("复述", tr.reasons[0])

    def test_no_skip_levels(self):
        reg, node = _prepared()
        ladder = Ladder(reg.cfg)
        tr = ladder.transition(node, PromotionEvidence(0.99, 9, 9, 9, 9), at=T0 + H)
        self.assertTrue(tr.changed)
        self.assertEqual(node.stage, Stage.S2_RESTATE)  # 一次只上一级

    def test_persona_delta_rejects_non_s4(self):
        reg, node = _prepared()
        with self.assertRaises(Exception):
            Ladder(reg.cfg).persona_delta(node, at=T0)


class TestEngine(unittest.TestCase):
    def test_full_path_to_s4(self):
        reg, node = _prepared()
        engine = ConsolidationEngine(
            verifier=char_overlap_verifier, answerer=echo_answerer, clock=lambda: T0
        )
        runs = engine.catch_up(reg, cycles=3, step_hours=12.0, at=T0 + 4 * H)
        self.assertEqual(node.stage, Stage.S4_MASTERED)
        self.assertEqual(len(runs), 3)
        self.assertEqual(node.variations_passed, 1)
        self.assertEqual(node.blind_test_passes, 1)
        self.assertEqual(reg.persona_projection()[0]["source_stage"], 4)
        self.assertEqual(node.sleep_cycles, 3)
        self.assertAlmostEqual(reg.persona_total["基础烹饪"], reg.persona_projection()[0]["delta"])

    def test_missing_transfer_blocks_promotion(self):
        reg, node = _prepared(with_transfer=False)
        engine = ConsolidationEngine(
            verifier=char_overlap_verifier, answerer=echo_answerer, clock=lambda: T0
        )
        engine.catch_up(reg, cycles=5, step_hours=12.0, at=T0 + 4 * H)
        self.assertEqual(node.stage, Stage.S3_CONSOLIDATE)
        self.assertEqual(reg.persona_projection(), [])
        self.assertTrue(evidence_for(node, reg.cfg).criterion_b)
        self.assertFalse(evidence_for(node, reg.cfg).criterion_c)

    def test_no_verifier_means_no_fake_score(self):
        reg, node = _prepared()
        engine = ConsolidationEngine(clock=lambda: T0)  # 不给回调
        engine.catch_up(reg, cycles=4, step_hours=12.0, at=T0 + 4 * H)
        self.assertEqual(node.variations_passed, 0)
        self.assertEqual(node.blind_test_passes, 0)
        self.assertLess(node.stage, Stage.S4_MASTERED)
        self.assertEqual(reg.persona_projection(), [])

    def test_failing_answerer_blocks_promotion(self):
        reg, node = _prepared()
        engine = ConsolidationEngine(
            verifier=char_overlap_verifier,
            answerer=lambda p: "完全无关的答案内容",
            clock=lambda: T0,
        )
        engine.catch_up(reg, cycles=4, step_hours=12.0, at=T0 + 4 * H)
        self.assertGreaterEqual(node.blind_test_fails, 1)
        self.assertNotEqual(node.stage, Stage.S4_MASTERED)

    def test_long_idle_demotes(self):
        reg, node = _prepared()
        engine = ConsolidationEngine(
            verifier=char_overlap_verifier, answerer=echo_answerer, clock=lambda: T0
        )
        engine.catch_up(reg, cycles=3, step_hours=12.0, at=T0 + 4 * H)
        self.assertEqual(node.stage, Stage.S4_MASTERED)
        run = engine.run_cycle(reg, at=T0 + 4 * H + 120 * DAY)
        self.assertEqual(node.stage, Stage.S3_CONSOLIDATE)
        self.assertIn(node.node_id, run.demoted)

    def test_frozen_node_is_skipped(self):
        reg, node = _prepared()
        node.frozen = True
        engine = ConsolidationEngine(clock=lambda: T0)
        run = engine.run_cycle(reg, at=T0 + 12 * H)
        self.assertIn(node.node_id, run.skipped)
        self.assertEqual(node.sleep_cycles, 0)

    def test_cycle_is_recorded(self):
        reg, _ = _prepared()
        ConsolidationEngine(clock=lambda: T0).run_cycle(reg, at=T0 + 12 * H)
        self.assertEqual(len(reg.cycles), 1)
        self.assertEqual(reg.cycles[0].started_at, T0 + 12 * H)


if __name__ == "__main__":
    unittest.main(verbosity=2)
