#!/usr/bin/env python3
"""01 · 5 分钟 Quickstart。

演示：摄入知识点 → 看「最近在琢磨的事」只读投影 → 看人格增量为什么是空的。

运行：python examples/01-quickstart.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # Windows 控制台默认 GBK，这里显式转 UTF-8，避免中文乱码
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cogniseed import (
    ConsolidationEngine,
    LearningRegistry,
    SleepScheduleConfig,
    Verifier,
)


def keyword_verifier(expected: str, candidate: str) -> bool:
    """判据 B 的校验器：接入方自传。这里用最朴素的字面重合当替身。

    生产中把它换成你的 LLM 判定函数即可——签名不变，仍是
    ``Callable[[str, str], bool]``，核心库不需要知道模型是谁。
    """
    return len(set(expected) & set(candidate)) >= 8


def echo_answerer(prompt: str) -> str:
    """被校验方的答案生产函数（示例用固定答案）。"""
    return "把温度稳在蛋白质变性区间，不要追求更高温度"


def main() -> None:
    cfg = SleepScheduleConfig.default()  # 通用昼夜节律模板，不写死真实作息
    reg = LearningRegistry(cfg=cfg)

    # —— 三行核心用法 ——
    node = reg.add_node(
        "基础烹饪",
        "低温慢煮的核心是把温度稳定在蛋白质变性区间，而不是追求更高温度",
        "agent_note",
    )
    reg.restate(node.node_id, "温度稳在变性区间，别追高温", passed=True)
    reg.record_transfer(node.node_id, "practice: 65℃ 慢煮鸡胸 45 分钟")

    print("=" * 68)
    print("1) 摄入一条知识点后，S1 阶段")
    print("=" * 68)
    print(f"node_id  : {node.node_id}")
    print(f"阶段     : {node.stage.code} {node.stage.label}")
    print(f"留存     : {node.retention:.3f}")
    print(f"人格增量 : {reg.persona_projection() or '[]  ← 没有 S4，一个数都不涨'}")

    print()
    print("=" * 68)
    print("2)「最近在琢磨的事」——只读投影")
    print("=" * 68)
    for row in reg.recently_mulling():
        print(f"  [{row['stage']}] {row['domain']} · {row['statement']}")
        print(f"        留存 {row['retention']} / 已过 {row['sleep_cycles']} 个睡眠周期")

    print()
    print("=" * 68)
    print("3) 跑 3 个睡眠周期（S1 → S4）")
    print("=" * 68)
    engine = ConsolidationEngine(verifier=keyword_verifier, answerer=echo_answerer)
    t0 = time.time()
    for i, run in enumerate(engine.catch_up(reg, cycles=3, step_hours=12.0, at=t0), 1):
        r = run.report()
        print(
            f"  周期 {i}: 复核 {r['reviewed']} 条 · 晋升 {r['promoted'] or '—'} "
            f"· 回退 {r['demoted'] or '—'} · 新投影 {len(r['deltas'])} 条"
        )

    print()
    print("=" * 68)
    print("4) 结果")
    print("=" * 68)
    print(f"最终阶段 : {node.stage.code} {node.stage.label}")
    print(f"睡眠周期 : {node.sleep_cycles}")
    print(f"变式通过 : {node.variations_passed}")
    print(f"盲测通过 : {node.blind_test_passes}")
    print(f"人格投影 : {reg.persona_total}")
    print()
    print("注意最后一项：数字来自 S4 知识点的只读投影，不是定时加出来的。")
    print("把 record_transfer 那行注释掉再跑一次，它会永远停在 S3 —— 一分不涨。")


if __name__ == "__main__":
    main()
