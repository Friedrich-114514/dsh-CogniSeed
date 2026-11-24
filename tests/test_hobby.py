"""双轨爱好测试：Solo 手痒/深度/试水 · Shared 折算与发起加权 · 刹车阀 · 休眠。

核心不变量：**纯共享不能晋升 core**——陪伴拉近距离，不制造能力。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogniseed import HobbyConfig, HobbyLedger, HobbyStatus, JsonStore

T0 = 1_800_000_000.0
H = 3_600.0
DAY = 24 * H


def make_ledger(**cfg) -> HobbyLedger:
    return HobbyLedger(cfg=HobbyConfig(**cfg) if cfg else HobbyConfig(), clock=lambda: T0)


class TestSoloTrack(unittest.TestCase):
    def test_content_accumulates_itch_and_depth(self):
        led = make_ledger()
        entry = led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3"], at=T0)
        self.assertEqual(entry.solo_depth, 3)
        self.assertAlmostEqual(entry.solo_itch, 0.75, places=6)

    def test_duplicate_notes_do_not_inflate_depth(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3"], at=T0)
        led.observe_content("基础烹饪", "c2", ["n3", "n1"], at=T0)
        entry = led.get("基础烹饪")
        self.assertEqual(entry.solo_depth, 3)
        self.assertEqual(entry.solo_notes, 3)

    def test_marginal_gain_shrinks_with_depth(self):
        """同一条轨道上，深了以后单条新知识的增益必须更小。"""
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2"], at=T0)
        first = led.get("基础烹饪").solo_itch / 2          # 深 0：0.25/条
        led.observe_content("基础烹饪", "c2", ["n3", "n4"], at=T0)
        second = (led.get("基础烹饪").solo_itch - first * 2) / 2  # 深 2：被打折
        self.assertLess(second, first)

    def test_solo_session_adds_time_weighted_itch(self):
        led = make_ledger()
        entry = led.record_solo_session("基础烹饪", 7200, at=T0)  # 2 小时
        self.assertAlmostEqual(entry.solo_itch, 0.10, places=6)
        self.assertEqual(entry.solo_seconds, 7200)


class TestPromotion(unittest.TestCase):
    def test_seed_cannot_trial(self):
        led = make_ledger()
        led.touch("陶艺")
        with self.assertRaises(Exception):
            led.record_trial("陶艺", passed=True, at=T0)

    def test_trial_needs_itch_and_depth(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3"], at=T0)
        self.assertEqual(led.project(at=T0)[0].status, HobbyStatus.TRIAL)
        led.record_trial("基础烹饪", passed=True, at=T0)
        self.assertEqual(led.get("基础烹饪").solo_trials, 1)

    def test_core_requires_itch_depth_and_trial(self):
        led = make_ledger()
        led.observe_content(
            "基础烹饪", "c1", ["n1", "n2", "n3", "n4", "n5"], at=T0
        )
        self.assertEqual(led.project(at=T0)[0].status, HobbyStatus.TRIAL)
        led.record_trial("基础烹饪", passed=True, at=T0)
        self.assertEqual(led.project(at=T0)[0].status, HobbyStatus.CORE)
        self.assertEqual(led.core_hobbies(at=T0), ["基础烹饪"])

    def test_failed_trial_does_not_count(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3", "n4", "n5"], at=T0)
        led.record_trial("基础烹饪", passed=False, at=T0)
        self.assertEqual(led.get("基础烹饪").solo_trials, 0)
        self.assertNotEqual(led.project(at=T0)[0].status, HobbyStatus.CORE)


class TestSharedTrack(unittest.TestCase):
    def test_initiated_weights_more_than_passive(self):
        led = make_ledger()
        a = led.record_shared_session(
            "基础烹饪", initiated_by_agent=True, emotional_weight=1.0, at=T0
        )
        b = led.record_shared_session(
            "观影", initiated_by_agent=False, emotional_weight=1.0, at=T0
        )
        self.assertGreater(a.shared_weight, b.shared_weight)
        self.assertAlmostEqual(a.shared_weight, 0.30, places=6)
        self.assertAlmostEqual(b.shared_weight, 0.165, places=6)

    def test_emotional_weight_scales(self):
        led = make_ledger()
        strong = led.record_shared_session(
            "基础烹饪", initiated_by_agent=True, emotional_weight=2.0, at=T0
        )
        led.record_shared_session("观影", initiated_by_agent=True, emotional_weight=1.0, at=T0)
        self.assertAlmostEqual(strong.shared_weight, 0.60, places=6)

    def test_shared_weight_is_capped(self):
        led = make_ledger()
        for _ in range(20):
            led.record_shared_session("基础烹饪", emotional_weight=3.0, at=T0)
        self.assertLessEqual(led.get("基础烹饪").shared_weight, led.cfg.shared_cap + 1e-9)

    def test_shared_folds_into_equivalent_itch(self):
        led = make_ledger()
        led.record_shared_session("基础烹饪", emotional_weight=1.0, at=T0)
        p = led.project(at=T0)[0]
        self.assertAlmostEqual(p.equivalent_itch, 0.30 * led.cfg.shared_fold, places=6)

    def test_pure_shared_never_becomes_core(self):
        led = make_ledger(shared_fold=1.0, shared_cap=5.0, shared_gain=1.0)
        for i in range(6):
            led.record_shared_session("观影", initiated_by_agent=True, at=T0 + i)
        p = led.project(at=T0 + 6)[0]
        self.assertGreater(p.equivalent_itch, led.cfg.core_itch)
        self.assertEqual(p.solo_depth, 0)
        self.assertNotEqual(p.status, HobbyStatus.CORE)
        self.assertEqual(led.core_hobbies(at=T0 + 6), [])


class TestBrakeAndDormancy(unittest.TestCase):
    def test_brake_downweights_then_release(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3", "n4", "n5"], at=T0)
        entry = led.brake("基础烹饪", "用户连续三次转移话题", at=T0)
        self.assertGreater(entry.penalty, 0)
        self.assertEqual(led.project(at=T0)[0].status, HobbyStatus.DOWNWEIGHTED)
        led.release("基础烹饪", at=T0)
        self.assertEqual(led.get("基础烹饪").penalty, 0.0)
        self.assertNotEqual(led.project(at=T0)[0].status, HobbyStatus.DOWNWEIGHTED)

    def test_brake_reduces_equivalent_itch(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3", "n4", "n5"], at=T0)
        before = led.project(at=T0)[0].equivalent_itch
        led.brake("基础烹饪", "负反馈", at=T0)
        after = led.project(at=T0)[0].equivalent_itch
        self.assertLess(after, before)

    def test_idle_turns_dormant(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2"], at=T0)
        self.assertNotEqual(led.project(at=T0)[0].status, HobbyStatus.DORMANT)
        p = led.project(at=T0 + 30 * DAY)[0]
        self.assertEqual(p.status, HobbyStatus.DORMANT)
        self.assertGreater(p.days_idle, led.cfg.dormant_days)

    def test_explicit_sleep_and_wake(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1", "n2"], at=T0)
        led.sleep("基础烹饪", at=T0)
        self.assertEqual(led.project(at=T0)[0].status, HobbyStatus.DORMANT)
        led.wake("基础烹饪", at=T0 + DAY)
        self.assertNotEqual(led.project(at=T0 + DAY)[0].status, HobbyStatus.DORMANT)

    def test_touch_revives_dormant(self):
        led = make_ledger()
        led.observe_content("基础烹饪", "c1", ["n1"], at=T0)
        self.assertEqual(led.project(at=T0 + 40 * DAY)[0].status, HobbyStatus.DORMANT)
        led.observe_content("基础烹饪", "c2", ["n2"], at=T0 + 40 * DAY)
        self.assertNotEqual(led.project(at=T0 + 40 * DAY)[0].status, HobbyStatus.DORMANT)


class TestLedgerPersistence(unittest.TestCase):
    def test_json_roundtrip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            store = JsonStore(Path(td) / "hobby.json")
            led = make_ledger()
            led.observe_content("基础烹饪", "c1", ["n1", "n2", "n3", "n4", "n5"], at=T0)
            led.record_trial("基础烹饪", passed=True, at=T0)
            led.record_shared_session("基础烹饪", emotional_weight=1.0, at=T0)
            led.persist(store)
            store.close()

            store2 = JsonStore(Path(td) / "hobby.json")
            state = store2.load("hobby:ledger")
            back = HobbyLedger.from_state(state)
            self.assertEqual(len(back), 1)
            self.assertEqual(back.get("基础烹饪").solo_depth, 5)
            self.assertEqual(back.get("基础烹饪").solo_trials, 1)
            self.assertEqual(
                back.project(at=T0)[0].status, led.project(at=T0)[0].status
            )
            store2.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
