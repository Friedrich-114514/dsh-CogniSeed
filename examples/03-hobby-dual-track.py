#!/usr/bin/env python3
"""03 · 双轨爱好：Solo 与 Shared 怎么汇流。

三个爱好，三条不同命运：

- 烹饪：自主内容 + 实践 + 试水 → 晋升 core
- 观影：只有共同场次 → 停在 TRIAL/ACTIVE，**纯共享不晋升**
- 陶艺：被兴趣刹车阀降权 → DOWNWEIGHTED
- 天文：长期不碰 → DORMANT

运行：python examples/03-hobby-dual-track.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from cogniseed import BiasEngine, HobbyConfig, HobbyLedger, HobbyStatus

T0 = 1_800_000_000.0
H = 3_600.0
DAY = 24 * H


def bar(value: float, width: int = 20) -> str:
    n = max(0, min(width, int(round(value * width / 2.0))))
    return "█" * n + "·" * (width - n)


def pad(text: str, width: int) -> str:
    """按东亚字符宽度对齐（CJK 记 2 列）。"""
    import unicodedata

    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - w)


def main() -> None:
    cfg = HobbyConfig()
    led = HobbyLedger(cfg=cfg, clock=lambda: T0)

    # —— 烹饪：Solo 轨走到底 ——
    led.observe_content(
        "基础烹饪", "c-01", ["低温慢煮靠温度稳定", "蛋白质变性区间决定口感"], at=T0
    )
    led.observe_content(
        "基础烹饪", "c-02", ["盐渍能改变蛋白质持水能力", "美拉德反应需要干表面"], at=T0 + 2 * H
    )
    led.observe_content(
        "基础烹饪", "c-03", ["油封是低温油浴传热", "静置让肉汁重新分布"], at=T0 + 3 * H
    )
    led.record_solo_session("基础烹饪", 5400, at=T0 + 4 * H)   # 动手练 1.5 小时
    led.record_shared_session("基础烹饪", initiated_by_agent=True, emotional_weight=1.5, at=T0 + 5 * H)
    led.record_trial("基础烹饪", passed=True, at=T0 + 6 * H)

    # —— 观影：只有共同场次 ——
    for i in range(6):
        led.record_shared_session(
            "观影", initiated_by_agent=(i % 2 == 0), emotional_weight=1.2, at=T0 + i * H
        )

    # —— 陶艺：有内容，但被刹车 ——
    led.observe_content("陶艺", "p-01", ["拉坯先定中心再开口", "素烧温度低于釉烧"], at=T0)
    led.brake("陶艺", "连续三次转移话题", at=T0 + H)

    # —— 天文：有内容，但长期不碰 ——
    led.observe_content("天文", "a-01", ["视星等是亮度不是距离"], at=T0)

    print("=" * 78)
    print("爱好双轨账本（T0）")
    print("=" * 78)
    print(
        pad("爱好", 10) + pad("状态", 14) + pad("等效手痒", 10) + pad("深度", 6)
        + pad("试水", 6) + pad("共同权重", 10) + "手痒"
    )
    print("-" * 78)
    for p in led.project(at=T0 + 6 * H):
        print(
            pad(p.name, 10)
            + pad(p.status.value, 14)
            + pad(f"{p.equivalent_itch:.3f}", 10)
            + pad(str(p.solo_depth), 6)
            + pad(str(p.solo_trials), 6)
            + pad(f"{p.shared_weight:.2f}", 10)
            + bar(p.equivalent_itch)
        )

    print()
    print(f"核心爱好：{led.core_hobbies(at=T0 + 6 * H)}")
    print()
    print("读法：")
    print("  · 烹饪 等效手痒过 core 门槛 + 深度够 + 试水过 → core")
    print("  · 观影 共同权重很高但深度为 0 → 不晋升（纯陪伴不制造能力）")
    print("  · 陶艺 penalty>0 → downweighted，只降权不清零，可恢复")
    print("  · 天文 手痒按时间冷却，久不碰落下")

    print()
    print("=" * 78)
    print("30 天后：时间做了什么")
    print("=" * 78)
    later = T0 + 30 * DAY
    for p in led.project(at=later):
        print(
            pad(p.name, 10)
            + pad(p.status.value, 14)
            + pad(f"{p.equivalent_itch:.3f}", 10)
            + pad(f"闲置 {p.days_idle:.1f} 天", 16)
            + bar(p.equivalent_itch)
        )

    print()
    print("=" * 78)
    print("解除刹车后能恢复吗")
    print("=" * 78)
    led.release("陶艺", at=later)
    row = [p for p in led.project(at=later) if p.hobby_id == "陶艺"][0]
    print(f"陶艺 → {row.status.value}（penalty 已清零，权重留在账上，不重新计分）")

    print()
    print("=" * 78)
    print("偏置引擎：软牵引，不做硬过滤")
    print("=" * 78)
    from cogniseed import LearningRegistry  # 延迟导入，保持示例自足

    reg = LearningRegistry(clock=lambda: T0)
    reg.add_node("基础烹饪", "低温慢煮靠温度稳定", "agent_note", at=T0)
    reg.add_node("基础园艺", "浇水看土壤干湿", "behavior_log", at=T0 + 1)
    for w in BiasEngine(clock=lambda: T0).weights(reg, led, at=T0 + 6 * H):
        print(f"  {pad(w.domain, 10)} 权重 {w.weight:.3f}  [{w.ring}] {w.reason}")
    print()
    print("所有权重都在 (0, 1]，没有一条被删掉——偏置只改采样概率。")


if __name__ == "__main__":
    main()
