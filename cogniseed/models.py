"""CogniSeed 数据模型。

零第三方依赖：仅标准库 dataclasses / enum / hashlib / math / datetime / time。
所有时间戳为 Unix 秒（float），一律由调用方注入；库内除 ``models.now()`` 这个
显式默认时钟外不读系统时钟，因此测试可完全复现。

命名约定：平台与角色只出现抽象词
``CompanionAgent`` / ``User`` / ``ContentFeedProvider`` / ``VideoSource``。
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum, IntEnum
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

__all__ = [
    "Stage",
    "SourceKind",
    "DomainRing",
    "HobbyTrack",
    "HobbyStatus",
    "CogniSeedError",
    "PrivacyViolation",
    "QuotaExceeded",
    "PoolFull",
    "KnowledgeNode",
    "Restatement",
    "BlindTestResult",
    "TransferRecord",
    "SleepCycle",
    "PersonaDelta",
    "HobbyEntry",
    "SleepScheduleConfig",
    "ALLOWED_SOURCES",
    "FORBIDDEN_SOURCES",
    "Verifier",
    "Answerer",
    "AnswererFor",
    "Clock",
    "now",
    "clamp01",
]

# 判据 B / 反装懂探针的校验器接口：纯回调钩子，接入方自传 LLM 函数。
#     verifier(expected: str, candidate: str) -> bool
#         语义等价判定：candidate 是否在语义上复现了 expected。
# 核心库不内置任何 LLM 客户端，保持零依赖。
Verifier = Callable[[str, str], bool]

# 被校验方的答案生产函数（示例夹具或接入方自传）。
#     answerer(prompt: str) -> str
Answerer = Callable[[str], str]

# 需要按节点作答时的变体（桥接场景：宿主只知道「哪个节点被问到」）。
#     answerer_for(node: KnowledgeNode, prompt: str) -> str
AnswererFor = Callable[["KnowledgeNode", str], str]

# 可注入时钟。
Clock = Callable[[], float]

# 只有这两类来源允许进入学籍表。用户原始聊天记录严禁回溯（隐私硬线）。
ALLOWED_SOURCES: Tuple[str, ...] = ("agent_note", "behavior_log")
FORBIDDEN_SOURCES = frozenset(
    {
        "raw_chat",
        "user_raw_chat",
        "chat_log",
        "chat_transcript",
        "im_history",
        "raw_message",
        "user_message",
    }
)


def now() -> float:
    """默认时钟。生产用系统时间，测试注入固定时间。"""
    return time.time()


def clamp01(x: float) -> float:
    """把浮点夹到 [0.0, 1.0]，同时抹掉 -0.0 与 NaN。"""
    if x != x:  # NaN
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def stable_id(prefix: str, *parts: str, size: int = 10) -> str:
    """确定性 ID：同样输入永远同样 ID（去重靠它，不靠随机数）。"""
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(raw).hexdigest()[:size]}"


def _utc_date(ts: float) -> date:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class CogniSeedError(Exception):
    """本库所有异常的基类。"""


class PrivacyViolation(CogniSeedError):
    """来源不在白名单，或命中禁止的原始聊天来源。"""


class QuotaExceeded(CogniSeedError):
    """当日新增知识点配额已用尽。"""


class PoolFull(CogniSeedError):
    """活跃池已满且无法驱逐（正常情况下不会抛出，仅作显式接口）。"""


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class Stage(IntEnum):
    """S1 感知 → S2 复述 → S3 巩固 → S4 掌握。

    IntEnum 使排序、比较、序列化都无需额外代码。
    """

    S1_PERCEIVE = 1
    S2_RESTATE = 2
    S3_CONSOLIDATE = 3
    S4_MASTERED = 4

    @property
    def code(self) -> str:
        return f"S{int(self)}"

    @property
    def label(self) -> str:
        return {
            Stage.S1_PERCEIVE: "感知",
            Stage.S2_RESTATE: "复述",
            Stage.S3_CONSOLIDATE: "巩固",
            Stage.S4_MASTERED: "掌握",
        }[self]


class SourceKind(str, Enum):
    AGENT_NOTE = "agent_note"
    BEHAVIOR_LOG = "behavior_log"


class DomainRing(IntEnum):
    """同心圆：领域按已掌握（S4）知识点数量排布到外/中/内圈。"""

    OUTER = 0
    MIDDLE = 1
    INNER = 2

    @property
    def label(self) -> str:
        return {0: "外圈", 1: "中圈", 2: "内圈"}[int(self)]


class HobbyTrack(str, Enum):
    SOLO = "solo"
    SHARED = "shared"


class HobbyStatus(str, Enum):
    SEED = "seed"
    TRIAL = "trial"
    ACTIVE = "active"
    CORE = "core"
    DOWNWEIGHTED = "downweighted"
    DORMANT = "dormant"


# --------------------------------------------------------------------------- #
# 知识点
# --------------------------------------------------------------------------- #


@dataclass
class KnowledgeNode:
    """一个原子知识点。学籍表的最小单位。"""

    node_id: str
    domain: str
    statement: str
    source: str
    created_at: float
    stage: Stage = Stage.S1_PERCEIVE
    retention: float = 1.0
    sleep_cycles: int = 0
    last_review_at: float = 0.0
    restatements: int = 0
    restated_ok: bool = False
    variations_passed: int = 0
    blind_test_passes: int = 0
    blind_test_fails: int = 0
    transfer_refs: list[str] = field(default_factory=list)
    corrections: int = 0
    s3_since: Optional[float] = None
    s4_at: Optional[float] = None
    frozen: bool = False
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.stage, Stage):
            self.stage = Stage(int(self.stage))
        if self.last_review_at <= 0.0:
            self.last_review_at = self.created_at
        self.retention = clamp01(self.retention)

    # -- 派生量 ------------------------------------------------------------ #

    @property
    def is_mastered(self) -> bool:
        return self.stage is Stage.S4_MASTERED

    @property
    def stage_code(self) -> str:
        return self.stage.code

    def fork(self, **changes: Any) -> "KnowledgeNode":
        """返回一份改动后的副本（默认不可变的用法）。"""
        return replace(self, **changes)

    # -- 序列化 ------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "domain": self.domain,
            "statement": self.statement,
            "source": self.source,
            "created_at": self.created_at,
            "stage": int(self.stage),
            "retention": self.retention,
            "sleep_cycles": self.sleep_cycles,
            "last_review_at": self.last_review_at,
            "restatements": self.restatements,
            "restated_ok": self.restated_ok,
            "variations_passed": self.variations_passed,
            "blind_test_passes": self.blind_test_passes,
            "blind_test_fails": self.blind_test_fails,
            "transfer_refs": list(self.transfer_refs),
            "corrections": self.corrections,
            "s3_since": self.s3_since,
            "s4_at": self.s4_at,
            "frozen": self.frozen,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeNode":
        payload = dict(data)
        payload["stage"] = Stage(int(payload["stage"]))
        return cls(**payload)


@dataclass(frozen=True)
class Restatement:
    """S1→S2 的一次复述留痕。"""

    node_id: str
    text: str
    at: float
    passed: bool


@dataclass(frozen=True)
class BlindTestResult:
    """判据 B：延迟盲测结果。"""

    node_id: str
    prompt: str
    candidate: str
    passed: bool
    at: float
    delay_hours: float


@dataclass(frozen=True)
class TransferRecord:
    """判据 C：行为日志里的应用/迁移留痕。仅接受 behavior_log 来源。"""

    node_id: str
    context: str
    at: float
    source: str = SourceKind.BEHAVIOR_LOG.value

    def __post_init__(self) -> None:
        if self.source != SourceKind.BEHAVIOR_LOG.value:
            raise PrivacyViolation(
                f"判据 C 只接受 behavior_log 留痕，收到 {self.source!r}"
            )


# --------------------------------------------------------------------------- #
# 睡眠周期与人格投影
# --------------------------------------------------------------------------- #


@dataclass
class SleepCycle:
    """一次睡眠巩固周期的结果快照。"""

    cycle_id: str
    started_at: float
    ended_at: float
    reviewed: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    demoted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def duration_hours(self) -> float:
        return max(0.0, (self.ended_at - self.started_at) / 3600.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "reviewed": list(self.reviewed),
            "promoted": list(self.promoted),
            "demoted": list(self.demoted),
            "skipped": list(self.skipped),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class PersonaDelta:
    """人格增量事件。

    只读投影：**仅** 由 S4（已掌握）节点产生。没有认知沉淀就一分不涨——
    这个类没有任何可写入口，也没有“定时微漂移”的分支。
    """

    node_id: str
    domain: str
    trait: str
    delta: float
    emitted_at: float
    source_stage: Stage = Stage.S4_MASTERED
    evidence: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source_stage is not Stage.S4_MASTERED:
            raise CogniSeedError("人格增量只能由 S4 节点产生")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "domain": self.domain,
            "trait": self.trait,
            "delta": self.delta,
            "emitted_at": self.emitted_at,
            "source_stage": int(self.source_stage),
            "evidence": list(self.evidence),
        }


# --------------------------------------------------------------------------- #
# 爱好
# --------------------------------------------------------------------------- #


@dataclass
class HobbyEntry:
    """双轨爱好账本的一行。

    Solo 轨（自主内容 → 原子知识点 → 手痒值 / 深度 → 试水）与
    Shared 轨（共同场次折算 + 发起加权）双向汇流。
    """

    hobby_id: str
    name: str
    solo_itch: float = 0.0
    solo_itch_at: float = 0.0
    solo_depth: int = 0
    solo_notes: int = 0
    solo_trials: int = 0
    solo_seconds: float = 0.0
    shared_sessions: int = 0
    shared_initiated: int = 0
    shared_weight: float = 0.0
    status: HobbyStatus = HobbyStatus.SEED
    last_touch: float = 0.0
    penalty: float = 0.0
    dormant_since: Optional[float] = None
    brake_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "hobby_id": self.hobby_id,
            "name": self.name,
            "solo_itch": self.solo_itch,
            "solo_itch_at": self.solo_itch_at,
            "solo_depth": self.solo_depth,
            "solo_notes": self.solo_notes,
            "solo_trials": self.solo_trials,
            "solo_seconds": self.solo_seconds,
            "shared_sessions": self.shared_sessions,
            "shared_initiated": self.shared_initiated,
            "shared_weight": self.shared_weight,
            "status": self.status.value,
            "last_touch": self.last_touch,
            "penalty": self.penalty,
            "dormant_since": self.dormant_since,
            "brake_reason": self.brake_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HobbyEntry":
        payload = dict(data)
        payload["status"] = HobbyStatus(payload["status"])
        return cls(**payload)


# --------------------------------------------------------------------------- #
# 作息配置
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SleepScheduleConfig:
    """作息配置。**不写死真实作息**，默认值只是通用昼夜节律模板。"""

    cycles_per_day: int = 2
    night_start_hour: int = 23
    night_end_hour: int = 7
    min_gap_hours: float = 6.0
    base_stability_hours: float = 72.0
    stability_growth: float = 0.65
    review_gain: float = 0.45
    retention_floor: float = 0.70
    min_sleep_cycles: int = 2
    blind_test_delay_hours: float = 6.0
    demote_floor: float = 0.45
    max_active_pool: int = 5
    daily_new_quota: int = 2

    @classmethod
    def default(cls) -> "SleepScheduleConfig":
        return cls()

    def cycle_slots(self, day: date) -> list[float]:
        """给定日期，返回当日各睡眠周期的计划开始时间戳（UTC 秒）。

        通用模板：把 night_start_hour→night_end_hour（跨零点时自动加一天）
        均分成 ``cycles_per_day`` 段，取每段中点作为结算时刻。
        """
        start = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        ) + timedelta(hours=self.night_start_hour)
        end = datetime(
            day.year, day.month, day.day, tzinfo=timezone.utc
        ) + timedelta(hours=self.night_end_hour)
        if end <= start:
            end += timedelta(days=1)
        span = (end - start) / max(1, self.cycles_per_day)
        return [
            (start + span * (i + 0.5)).timestamp()
            for i in range(max(1, self.cycles_per_day))
        ]

    def is_night(self, ts: float) -> bool:
        """按配置判断某时刻是否落在夜间窗口内。"""
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        if self.night_start_hour <= self.night_end_hour:
            return self.night_start_hour <= hour < self.night_end_hour
        return hour >= self.night_start_hour or hour < self.night_end_hour

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_per_day": self.cycles_per_day,
            "night_start_hour": self.night_start_hour,
            "night_end_hour": self.night_end_hour,
            "min_gap_hours": self.min_gap_hours,
            "base_stability_hours": self.base_stability_hours,
            "stability_growth": self.stability_growth,
            "review_gain": self.review_gain,
            "retention_floor": self.retention_floor,
            "min_sleep_cycles": self.min_sleep_cycles,
            "blind_test_delay_hours": self.blind_test_delay_hours,
            "demote_floor": self.demote_floor,
            "max_active_pool": self.max_active_pool,
            "daily_new_quota": self.daily_new_quota,
        }


def day_key(ts: float) -> str:
    """配额计数用的日期键（UTC）。"""
    return _utc_date(ts).isoformat()
