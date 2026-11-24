"""CogniSeed —— 真实认知成长型 AI 伴侣引擎。

零第三方依赖（仅 Python 3.10+ 标准库）。

三行最小用法::

    from cogniseed import LearningRegistry, ConsolidationEngine
    reg = LearningRegistry()
    reg.add_node("基础烹饪", "低温慢煮的核心是把温度稳定在蛋白质变性区间")
    print(reg.recently_mulling())

核心主张：成长 = 知识被睡眠巩固；人格数值只是 S4 之后的**只读投影**，
没有认知沉淀就一分不涨。
"""

from .models import (
    ALLOWED_SOURCES,
    FORBIDDEN_SOURCES,
    Answerer,
    AnswererFor,
    BlindTestResult,
    Clock,
    CogniSeedError,
    DomainRing,
    HobbyEntry,
    HobbyStatus,
    HobbyTrack,
    KnowledgeNode,
    PersonaDelta,
    PoolFull,
    PrivacyViolation,
    QuotaExceeded,
    Restatement,
    SleepCycle,
    SleepScheduleConfig,
    SourceKind,
    Stage,
    TransferRecord,
    Verifier,
    clamp01,
    now,
)
from .registry import LearningRegistry
from .ladder import STAGE_FLOW, Ladder, PromotionEvidence, Transition
from .consolidation import (
    ConsolidationEngine,
    SleepRun,
    blind_prompt,
    evidence_for,
    refresh,
    retention_at,
    variation_drills,
)
from .hobby_ledger import HobbyConfig, HobbyLedger, HobbyProjection
from .bias_engine import BiasEngine, BiasWeight
from .anti_cheat import AntiCheat, Probe, ProbeKind, Verdict
from .storage import JsonStore, SqliteStore

__version__ = "1.0.0"
__all__ = [
    "__version__",
    # 模型
    "KnowledgeNode",
    "SleepCycle",
    "PersonaDelta",
    "HobbyEntry",
    "SleepScheduleConfig",
    "Stage",
    "SourceKind",
    "DomainRing",
    "HobbyTrack",
    "HobbyStatus",
    "Restatement",
    "BlindTestResult",
    "TransferRecord",
    "ALLOWED_SOURCES",
    "FORBIDDEN_SOURCES",
    "Verifier",
    "Answerer",
    "AnswererFor",
    "Clock",
    "now",
    "clamp01",
    # 异常
    "CogniSeedError",
    "PrivacyViolation",
    "QuotaExceeded",
    "PoolFull",
    # 核心
    "LearningRegistry",
    "Ladder",
    "Transition",
    "PromotionEvidence",
    "STAGE_FLOW",
    "ConsolidationEngine",
    "SleepRun",
    "retention_at",
    "refresh",
    "variation_drills",
    "blind_prompt",
    "evidence_for",
    "HobbyLedger",
    "HobbyConfig",
    "HobbyProjection",
    "BiasEngine",
    "BiasWeight",
    "AntiCheat",
    "Probe",
    "ProbeKind",
    "Verdict",
    "JsonStore",
    "SqliteStore",
]
