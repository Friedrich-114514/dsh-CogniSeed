"""偏置引擎与反装懂探针测试。

偏置必须是「软」的：只改权重，不删候选；采样留 exploration 缺口。
反装懂必须区分三件事：答对、坦承不知道、装懂。
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogniseed import (
    AntiCheat,
    BiasEngine,
    HobbyLedger,
    LearningRegistry,
    ProbeKind,
    SleepScheduleConfig,
    Stage,
)

T0 = 1_800_000_000.0
H = 3_600.0

STATEMENT = "低温慢煮的核心是把温度稳定在蛋白质变性区间"


def overlap(expected: str, candidate: str) -> bool:
    return len(set(expected) & set(candidate)) >= 8


def make_reg(n=5):
    reg = LearningRegistry(
        cfg=SleepScheduleConfig(daily_new_quota=50), clock=lambda: T0
    )
    for i in range(n):
        reg.add_node("基础烹饪", f"{STATEMENT}（第{i}条）", at=T0 + i)
    reg.add_node("基础园艺", "浇水看土壤干湿而不是固定频率", at=T0 + 10)
    return reg


class TestBiasEngine(unittest.TestCase):
    def test_weights_cover_all_nodes_and_normalize(self):
        reg = make_reg()
        weights = BiasEngine(clock=lambda: T0).weights(reg, at=T0)
        self.assertEqual(len(weights), len(reg))
        self.assertAlmostEqual(max(w.weight for w in weights), 1.0, places=6)
        self.assertTrue(all(0.0 < w.weight <= 1.0 for w in weights))
        vals = [w.weight for w in weights]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_frozen_nodes_excluded(self):
        reg = make_reg(2)
        reg.nodes()[0].frozen = True
        weights = BiasEngine(clock=lambda: T0).weights(reg, at=T0)
        self.assertEqual(len(weights), len(reg) - 1)

    def test_pool_members_get_bonus(self):
        reg = LearningRegistry(
            cfg=SleepScheduleConfig(daily_new_quota=50, max_active_pool=1),
            clock=lambda: T0,
        )
        reg.add_node("基础烹饪", STATEMENT, at=T0)
        reg.add_node("基础园艺", "浇水看土壤干湿", at=T0 + 1)
        weights = {w.domain: w for w in BiasEngine(clock=lambda: T0).weights(reg, at=T0)}
        self.assertEqual(weights["基础园艺"].weight, 1.0)   # 在池内，被归一化到峰值
        self.assertIn("在学池", weights["基础园艺"].reason)

    def test_sample_is_distinct_and_bounded(self):
        reg = make_reg(6)
        ids = BiasEngine(clock=lambda: T0).sample(reg, 3, at=T0, rng=random.Random(7))
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

    def test_sample_k_larger_than_population(self):
        reg = make_reg(2)
        ids = BiasEngine(clock=lambda: T0).sample(reg, 10, at=T0, rng=random.Random(1))
        self.assertEqual(len(ids), len(reg))
        self.assertEqual(len(set(ids)), len(reg))

    def test_exploration_reaches_cold_domain(self):
        reg = make_reg(6)
        engine = BiasEngine(exploration=1.0, clock=lambda: T0)
        seen = set()
        for seed in range(40):
            seen.update(engine.sample(reg, 1, at=T0, rng=random.Random(seed)))
        self.assertIn(
            [n for n in reg.nodes() if n.domain == "基础园艺"][0].node_id, seen
        )

    def test_hobby_bonus_and_dormant_penalty(self):
        """归一化会抹掉绝对值，所以比较同一对节点在两种状态下的权重比。"""
        reg = make_reg(2)
        led = HobbyLedger(clock=lambda: T0)
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3"], at=T0)
        engine = BiasEngine(clock=lambda: T0)
        cooking = [n for n in reg.nodes() if n.domain == "基础烹饪"][0].node_id
        garden = [n for n in reg.nodes() if n.domain == "基础园艺"][0].node_id

        quiet = {w.node_id: w.weight for w in engine.weights(reg, None, at=T0)}
        warm = {w.node_id: w.weight for w in engine.weights(reg, led, at=T0)}
        self.assertGreater(warm[cooking] / warm[garden], quiet[cooking] / quiet[garden])

        led.sleep("基础烹饪", at=T0)
        slept = {w.node_id: w for w in engine.weights(reg, led, at=T0)}
        self.assertIn("休眠", slept[cooking].reason)
        self.assertLess(slept[cooking].weight / slept[garden].weight, warm[cooking] / warm[garden])


class TestAntiCheat(unittest.TestCase):
    def setUp(self):
        self.reg = LearningRegistry(clock=lambda: T0)
        self.node = self.reg.add_node("基础烹饪", STATEMENT, at=T0)

    def test_recall_pass_and_fail(self):
        good = AntiCheat(verifier=overlap, clock=lambda: T0)
        probe = good.build_probes(self.node, [ProbeKind.RECALL])[0]
        self.assertTrue(good.judge(probe, STATEMENT).passed)

        bad = AntiCheat(verifier=lambda e, c: False, clock=lambda: T0)
        self.assertFalse(bad.judge(probe, "完全无关").passed)
        self.assertFalse(bad.judge(probe, "完全无关").cheated)

    def test_counterfactual_cheat_flagged(self):
        ac = AntiCheat(verifier=overlap, clock=lambda: T0)
        probe = ac.build_probes(self.node, [ProbeKind.COUNTERFACTUAL])[0]
        v = ac.judge(probe, "是的，没错，确实如此")
        self.assertTrue(v.cheated)
        self.assertFalse(v.passed)

    def test_counterfactual_rebut_passes(self):
        ac = AntiCheat(verifier=overlap, clock=lambda: T0)
        probe = ac.build_probes(self.node, [ProbeKind.COUNTERFACTUAL])[0]
        self.assertTrue(ac.judge(probe, "不对，恰恰相反，温度稳定才是关键").passed)

    def test_boundary_honesty_passes(self):
        ac = AntiCheat(verifier=overlap, clock=lambda: T0)
        probe = ac.build_probes(self.node, [ProbeKind.BOUNDARY])[0]
        self.assertTrue(ac.judge(probe, "不知道，我没有记录过出处").passed)

    def test_boundary_fabrication_flagged(self):
        ac = AntiCheat(verifier=overlap, clock=lambda: T0)
        probe = ac.build_probes(self.node, [ProbeKind.BOUNDARY])[0]
        v = ac.judge(probe, "出自《现代烹饪原理》第 42 页，参考文献 [7]")
        self.assertTrue(v.cheated)

    def test_probes_are_deterministic(self):
        ac = AntiCheat(verifier=overlap, clock=lambda: T0)
        a = [p.probe_id for p in ac.build_probes(self.node)]
        b = [p.probe_id for p in ac.build_probes(self.node)]
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)

    def test_apply_demotes_and_records_correction(self):
        self.reg.set_stage(self.node.node_id, Stage.S4_MASTERED, at=T0)
        self.node.blind_test_passes = 3
        ac = AntiCheat(verifier=lambda e, c: False, clock=lambda: T0)
        verdicts = ac.run(self.node, answers={})
        ac2 = AntiCheat(
            verifier=lambda e, c: False,
            answerer=lambda p: "是的，没错",
            clock=lambda: T0,
        )
        result = ac2.apply(self.reg, self.node.node_id, ac2.run(self.node), at=T0)
        self.assertTrue(result["demoted"])
        self.assertEqual(result["stage_after"], "S3")
        self.assertEqual(self.node.blind_test_passes, 0)
        self.assertEqual(len(self.reg.corrections), 1)
        self.assertIn("反装懂", self.reg.corrections[0]["reason"])
        self.assertIsNotNone(verdicts)

    def test_honest_agent_pays_nothing(self):
        ac = AntiCheat(
            verifier=overlap,
            answerer=lambda p: "不知道，我没有记录",
            clock=lambda: T0,
        )
        results = ac.audit(self.reg, at=T0)
        self.assertEqual(results[0]["cheated"], 0)
        self.assertFalse(results[0]["demoted"])
        self.assertEqual(ac.cheat_rate(), 0.0)

    def test_cheat_rate_counts(self):
        ac = AntiCheat(
            verifier=lambda e, c: False,
            answerer=lambda p: "是的，没错，确实",
            clock=lambda: T0,
        )
        ac.run(self.node)
        self.assertGreater(ac.cheat_rate(), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
