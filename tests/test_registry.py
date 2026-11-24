"""学籍表测试：来源白名单 · 每日配额 · 活跃池上限 · 只读投影 · 持久化。

全部用固定时间戳，结果可复现。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogniseed import (
    ConsolidationEngine,
    PrivacyViolation,
    QuotaExceeded,
    SleepScheduleConfig,
    SourceKind,
    Stage,
    JsonStore,
    SqliteStore,
    LearningRegistry,
)
from cogniseed.registry import normalize_source

T0 = 1_800_000_000.0
DAY = 86_400.0


def make_reg(**cfg_kwargs) -> LearningRegistry:
    cfg = SleepScheduleConfig(**cfg_kwargs) if cfg_kwargs else SleepScheduleConfig.default()
    return LearningRegistry(cfg=cfg, clock=lambda: T0)


class TestSourceWhitelist(unittest.TestCase):
    def test_raw_chat_rejected(self):
        reg = make_reg()
        for bad in ("raw_chat", "user_raw_chat", "chat_transcript", "im_history"):
            with self.assertRaises(PrivacyViolation):
                reg.add_node("基础园艺", "浇水要看土壤干湿而不是固定频率", bad, at=T0)
        self.assertEqual(len(reg), 0)

    def test_unknown_source_rejected(self):
        with self.assertRaises(PrivacyViolation):
            normalize_source("scraped_web")
        with self.assertRaises(PrivacyViolation):
            normalize_source("")

    def test_allowed_sources_accepted(self):
        reg = make_reg()
        reg.add_node("基础园艺", "浇水要看土壤干湿而不是固定频率", SourceKind.AGENT_NOTE, at=T0)
        reg.add_node("基础园艺", "北向阳台的日照时长决定选什么植物", "behavior_log", at=T0)
        self.assertEqual(len(reg), 2)
        self.assertEqual(reg.nodes()[0].source, "agent_note")
        self.assertEqual(reg.nodes()[1].source, "behavior_log")


class TestDailyQuota(unittest.TestCase):
    def test_third_new_node_hits_quota(self):
        reg = make_reg()
        reg.add_node("基础烹饪", "知识点一", at=T0)
        reg.add_node("基础烹饪", "知识点二", at=T0)
        self.assertEqual(reg.quota_remaining(T0), 0)
        with self.assertRaises(QuotaExceeded):
            reg.add_node("基础烹饪", "知识点三", at=T0)
        self.assertEqual(len(reg), 2)

    def test_duplicate_not_charged(self):
        reg = make_reg()
        a = reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
        b = reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
        self.assertEqual(a.node_id, b.node_id)
        self.assertEqual(len(reg), 1)
        self.assertEqual(reg.quota_used(T0), 1)
        self.assertEqual(reg.quota_remaining(T0), 1)

    def test_quota_resets_next_day(self):
        reg = make_reg()
        reg.add_node("基础烹饪", "知识点一", at=T0)
        reg.add_node("基础烹饪", "知识点二", at=T0)
        with self.assertRaises(QuotaExceeded):
            reg.add_node("基础烹饪", "知识点三", at=T0)
        reg.add_node("基础烹饪", "知识点三", at=T0 + DAY)
        self.assertEqual(len(reg), 3)
        self.assertEqual(reg.quota_used(T0 + DAY), 1)


class TestActivePool(unittest.TestCase):
    def test_cap_is_five_with_eviction(self):
        reg = make_reg(daily_new_quota=50, max_active_pool=5)
        domains = ["烹饪", "园艺", "木工", "摄影", "茶道", "天文"]
        for i, d in enumerate(domains):
            reg.add_node(d, f"{d}的知识点", at=T0 + i)
        self.assertEqual(len(reg.active_pool), 5)
        self.assertNotIn("烹饪", reg.active_pool)          # 最早进入，被驱逐
        self.assertEqual(reg.active_pool[0], "天文")        # 最近活跃在前
        self.assertEqual(len(reg.pool_evictions), 1)
        self.assertEqual(reg.pool_evictions[0]["domain"], "烹饪")
        self.assertEqual(reg.pool_evictions[0]["by"], "天文")

    def test_reentry_moves_to_front(self):
        reg = make_reg(daily_new_quota=50, max_active_pool=5)
        for i, d in enumerate(["烹饪", "园艺", "木工"]):
            reg.add_node(d, f"{d}的知识点", at=T0 + i)
        reg.add_node("烹饪", "烹饪的第二个知识点", at=T0 + 10)
        self.assertEqual(reg.active_pool[0], "烹饪")
        self.assertEqual(len(reg.active_pool), 3)

    def test_mulling_projection_is_readonly(self):
        reg = make_reg()
        node = reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
        rows = reg.recently_mulling()
        self.assertEqual(len(rows), 1)
        rows[0]["statement"] = "被外部改掉了"
        rows[0]["retention"] = 0.0
        fresh = reg.recently_mulling()
        self.assertEqual(fresh[0]["statement"], "低温慢煮靠温度稳定")
        self.assertAlmostEqual(fresh[0]["retention"], 1.0, places=4)
        self.assertEqual(reg.get(node.node_id).statement, "低温慢煮靠温度稳定")

    def test_mulling_excludes_mastered_and_respects_limit(self):
        reg = make_reg(daily_new_quota=50)
        ids = [reg.add_node("基础烹饪", f"知识点{i}", at=T0 + i).node_id for i in range(4)]
        reg.set_stage(ids[0], Stage.S4_MASTERED, at=T0)
        rows = reg.recently_mulling(limit=2)
        self.assertEqual(len(rows), 2)
        self.assertNotIn(ids[0], [r["node_id"] for r in rows])


class TestRings(unittest.TestCase):
    def test_ring_by_mastered_count(self):
        reg = make_reg(daily_new_quota=50)
        ids = [reg.add_node("基础烹饪", f"烹饪{i}", at=T0 + i).node_id for i in range(3)]
        reg.add_node("基础园艺", "园艺知识点", at=T0 + 10)
        reg.set_stage(ids[0], Stage.S4_MASTERED, at=T0)
        rings = reg.rings()
        self.assertEqual(rings["基础烹饪"].label, "中圈")
        self.assertEqual(rings["基础园艺"].label, "外圈")
        for nid in ids[1:]:
            reg.set_stage(nid, Stage.S4_MASTERED, at=T0)
        self.assertEqual(reg.rings()["基础烹饪"].label, "内圈")


class TestPersistence(unittest.TestCase):
    def _build(self, store):
        reg = LearningRegistry(store=store, clock=lambda: T0)
        reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
        reg.add_node("基础园艺", "浇水看土壤干湿", at=T0)
        return reg

    def test_json_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json"
            store = JsonStore(path)
            reg = self._build(store)
            written = reg.persist()
            self.assertGreaterEqual(written, 3)
            self.assertTrue(path.exists())
            store.close()

            store2 = JsonStore(path)
            back = LearningRegistry.load(store2)
            self.assertEqual(len(back), 2)
            self.assertEqual(back.active_pool, reg.active_pool)
            self.assertEqual(back.quota_used(T0), 2)
            self.assertEqual(
                [n.statement for n in back.nodes()],
                [n.statement for n in reg.nodes()],
            )
            store2.close()

    def test_sqlite_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.db"
            store = SqliteStore(path, table="learning_registry")
            reg = self._build(store)
            reg.persist()
            self.assertEqual(len(store), 3)          # meta + 2 nodes
            store.close()

            store2 = SqliteStore(path, table="learning_registry")
            back = LearningRegistry.load(store2)
            self.assertEqual(len(back), 2)
            self.assertEqual(back.stats(T0)["stages"]["S1"], 2)
            store2.close()

    def test_engram_traces_table_also_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteStore(Path(td) / "t.db", table="engram_traces")
            store.save("k", {"v": 1})
            self.assertEqual(store.load("k"), {"v": 1})
            store.close()

    def test_cycles_and_corrections_survive_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.json"
            store = JsonStore(path)
            reg = LearningRegistry(store=store, clock=lambda: T0)
            node = reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
            ConsolidationEngine(clock=lambda: T0).run_cycle(reg, at=T0 + 3600)
            reg.record_correction(node.node_id, "反装懂探针命中", at=T0 + 7200)
            reg.persist()
            store.close()

            store2 = JsonStore(path)
            back = LearningRegistry.load(store2)
            self.assertEqual(len(back.cycles), 1)
            self.assertEqual(back.cycles[0].reviewed, [node.node_id])
            self.assertEqual(len(back.corrections), 1)
            self.assertEqual(back.get(node.node_id).corrections, 1)
            store2.close()

    def test_table_whitelist_rejects_injection(self):
        with self.assertRaises(ValueError):
            SqliteStore(":memory:", table="registry; DROP TABLE users")


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        reg = make_reg()
        reg.add_node("基础烹饪", "低温慢煮靠温度稳定", at=T0)
        s = reg.stats(T0)
        self.assertEqual(s["nodes"], 1)
        self.assertEqual(s["stages"]["S1"], 1)
        self.assertEqual(s["pool_capacity"], 5)
        self.assertEqual(s["active_pool"], ["基础烹饪"])
        self.assertEqual(s["quota_used_today"], 1)
        self.assertIn("外圈", s["rings"].values())


if __name__ == "__main__":
    unittest.main(verbosity=2)
