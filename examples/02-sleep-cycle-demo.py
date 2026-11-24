#!/usr/bin/env python3
"""02 · 睡眠周期演算：三判据怎么卡人。

对照两组知识点：

- A 组：复述 + 行为迁移留痕齐全 → 3 个周期后升 S4，产出人格增量
- B 组：只有复述，没有迁移证据 → 卡在 S3，永远不产出增量

运行：python examples/02-sleep-cycle-demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cogniseed import (
    ConsolidationEngine,
    LearningRegistry,
    PromotionEvidence,
    SleepScheduleConfig,
    Stage,
    evidence_for,
)

T0 = 1_800_000_000.0          # 固定时间戳，输出可复现
H = 3_600.0


def pad(text: str, width: int) -> str:
    """按东亚字符宽度对齐（CJK 记 2 列）。"""
    import unicodedata

    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - w)


def overlap_verifier(expected: str, candidate: str) -> bool:
    return len(set(expected) & set(candidate)) >= 8


ANSWERS = {
    "A": "温度稳定在蛋白质变性区间，别追求更高温度",
    "B": "浇水要看土壤的干湿状态，不是按固定天数",
}


def answerer_for(tag: str):
    return lambda prompt: ANSWERS[tag]


def main() -> None:
    cfg = SleepScheduleConfig.default()
    reg = LearningRegistry(cfg=cfg, clock=lambda: T0)

    a = reg.add_node(
        "基础烹饪", "低温慢煮的核心是把温度稳定在蛋白质变性区间", "agent_note", at=T0
    )
    b = reg.add_node(
        "基础园艺", "浇水要看土壤干湿状态，不是按固定天数", "agent_note", at=T0
    )
    reg.restate(a.node_id, "稳温不追高温", True, at=T0 + H)
    reg.restate(b.node_id, "看土不看日历", True, at=T0 + H)

    # 只有 A 组有行为日志迁移证据（判据 C）
    reg.record_transfer(a.node_id, "practice: 65℃ / 45min", at=T0 + 2 * H)

    print("初始状态")
    print(f"  A {a.node_id}  {a.stage.code}  留存 {a.retention:.3f}")
    print(f"  B {b.node_id}  {b.stage.code}  留存 {b.retention:.3f}")
    print()

    engine = ConsolidationEngine(
        cfg=cfg, verifier=overlap_verifier, answerer=lambda p: _route(p), clock=lambda: T0
    )

    header = (
        pad("周期", 6) + pad("时刻+h", 9) + pad("A阶段", 8) + pad("A留存", 9)
        + pad("A判据", 26) + pad("B阶段", 8) + pad("B留存", 9) + "B判据"
    )
    print(header)
    print("-" * 84)

    for i in range(1, 5):
        at = T0 + (4 + 12 * (i - 1)) * H
        engine.run_cycle(reg, at=at)
        ea = evidence_for(a, cfg)
        eb = evidence_for(b, cfg)
        print(
            pad(str(i), 6)
            + pad(str(int((at - T0) / H)), 9)
            + pad(a.stage.code, 8)
            + pad(f"{a.retention:.3f}", 9)
            + pad(_flags(ea), 26)
            + pad(b.stage.code, 8)
            + pad(f"{b.retention:.3f}", 9)
            + _flags(eb)
        )

    print()
    print("最终")
    print(f"  A: {a.stage.code} {a.stage.label} · 人格投影 {reg.persona_total}")
    print(f"  B: {b.stage.code} {b.stage.label} · 卡住原因 {evidence_for(b, cfg).blocked_reasons()}")
    print()
    print("B 组即使在 S3 停留 4 个周期、留存 0.9+，只要没有判据 C 就不许升 S4。")
    print("这就是「聊三句露馅」在库里的物理阻断：没有应用证据，就没有掌握。")


def _route(prompt: str) -> str:
    """按提示词里的知识点关键词路由到对应假答案。

    注意：变式提示词里只嵌知识点原文、不含领域名，所以要按内容路由。
    """
    if "土壤" in prompt or "园艺" in prompt:
        return ANSWERS["B"]
    return ANSWERS["A"]


def _flags(e: PromotionEvidence) -> str:
    return f"A{'✓' if e.criterion_a else '✗'} B{'✓' if e.criterion_b else '✗'} C{'✓' if e.criterion_c else '✗'} 变式{'✓' if e.variation_drill else '✗'}"


if __name__ == "__main__":
    main()
