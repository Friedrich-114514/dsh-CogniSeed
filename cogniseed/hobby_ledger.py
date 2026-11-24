"""双轨爱好账本：Solo 轨与 Shared 轨双向汇流。

Solo 轨：自主内容 → 原子知识点 → 手痒值（itch）+ 深度（depth）→ 试水（trial）
         → 满足条件晋升 core。
Shared 轨：共同场次按系数折算成等效手痒值，**发起方加权**（Agent 主动发起的
         场次比被动陪伴权重高）。
兴趣刹车阀：负反馈 → 降权（DOWNWEIGHTED）；长期不碰 → 休眠（DORMANT）。

一条硬规则：**纯共享不能晋升 core**。陪伴能拉近距离，不能代替能力——深度
为 0 的爱好最高只到 TRAIL（试水），这是「真实成长」与本账本的一致性所在。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional, Sequence

from .models import (
    Clock,
    CogniSeedError,
    HobbyEntry,
    HobbyStatus,
    HobbyTrack,
    now as _now,
    stable_id,
)

__all__ = ["HobbyConfig", "HobbyLedger", "HobbyProjection"]


@dataclass(frozen=True)
class HobbyConfig:
    """爱好演化参数。全部可调，默认值是给「几百场内内容消费」规模用的。"""

    itch_per_note: float = 0.25          # 每个新原子知识点的初始手痒增量
    itch_per_hour: float = 0.05          # 自主实践每小时的手痒增量
    itch_decay_per_day: float = 0.08     # 手痒自然冷却（每天）
    depth_diminish: float = 0.92         # 手痒随深度增长的边际递减
    trial_itch: float = 0.60             # 试水门槛（等效手痒）
    trial_depth: int = 2                 # 试水门槛（深度）
    core_itch: float = 1.20              # 核心门槛（等效手痒）
    core_depth: int = 4                  # 核心门槛（深度）
    core_trials: int = 1                 # 核心门槛（试水次数）
    shared_fold: float = 0.40            # 共同场次 → 等效手痒的折算系数
    shared_gain: float = 0.30            # 单场共同经历基准权重
    initiated_weight: float = 1.00       # Agent 发起
    passive_weight: float = 0.55         # 被动参与
    shared_cap: float = 2.00             # 共同轨权重上限
    dormant_days: float = 21.0           # 多久不碰算休眠
    brake_factor: float = 0.50           # 刹车阀：降权后保留比例

    def to_dict(self) -> dict[str, Any]:
        return {
            "itch_per_note": self.itch_per_note,
            "itch_per_hour": self.itch_per_hour,
            "itch_decay_per_day": self.itch_decay_per_day,
            "depth_diminish": self.depth_diminish,
            "trial_itch": self.trial_itch,
            "trial_depth": self.trial_depth,
            "core_itch": self.core_itch,
            "core_depth": self.core_depth,
            "core_trials": self.core_trials,
            "shared_fold": self.shared_fold,
            "shared_gain": self.shared_gain,
            "initiated_weight": self.initiated_weight,
            "passive_weight": self.passive_weight,
            "shared_cap": self.shared_cap,
            "dormant_days": self.dormant_days,
            "brake_factor": self.brake_factor,
        }


@dataclass(frozen=True)
class HobbyProjection:
    """一条爱好的只读视图（派生量都在这里算，不改账本）。"""

    hobby_id: str
    name: str
    status: HobbyStatus
    solo_itch: float
    solo_depth: int
    solo_trials: int
    shared_weight: float
    equivalent_itch: float
    days_idle: float
    penalty: float
    brake_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hobby_id": self.hobby_id,
            "name": self.name,
            "status": self.status.value,
            "solo_itch": round(self.solo_itch, 4),
            "solo_depth": self.solo_depth,
            "solo_trials": self.solo_trials,
            "shared_weight": round(self.shared_weight, 4),
            "equivalent_itch": round(self.equivalent_itch, 4),
            "days_idle": round(self.days_idle, 2),
            "penalty": round(self.penalty, 4),
            "brake_reason": self.brake_reason,
        }


class HobbyLedger:
    """双轨爱好账本。所有派生量都在读取时算，账本本身只存事实。"""

    def __init__(
        self,
        cfg: Optional[HobbyConfig] = None,
        *,
        store: Any = None,
        clock: Optional[Clock] = None,
    ) -> None:
        self.cfg = cfg or HobbyConfig()
        self.store = store
        self.clock = clock or _now
        self._rows: dict[str, HobbyEntry] = {}
        self._seen_notes: dict[str, set[str]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}

    # -- 内部 -------------------------------------------------------------- #

    def now(self) -> float:
        return float(self.clock())

    def _log(self, hobby_id: str, kind: str, at: float, **payload: Any) -> None:
        self._history.setdefault(hobby_id, []).append(
            {"kind": kind, "at": at, **payload}
        )

    def _time_decay(self, entry: HobbyEntry, at: float) -> float:
        """累计手痒只按时间冷却。深度折减**不**在这里做（否则会重复打折）。"""
        elapsed_days = max(0.0, (at - entry.solo_itch_at) / 86400.0)
        return max(0.0, entry.solo_itch * math.exp(-self.cfg.itch_decay_per_day * elapsed_days))

    def _decayed_itch(self, entry: HobbyEntry, at: float) -> float:
        return self._time_decay(entry, at)

    def _note_gain(self, entry: HobbyEntry, count: int) -> float:
        """边际递减：越深的新知识点，单条带来的手痒越小。"""
        return (
            self.cfg.itch_per_note
            * count
            * (self.cfg.depth_diminish ** max(0, entry.solo_depth))
        )

    def _equivalent(self, entry: HobbyEntry, at: float) -> float:
        return self._decayed_itch(entry, at) + entry.shared_weight * self.cfg.shared_fold

    def _status(self, entry: HobbyEntry, at: float) -> HobbyStatus:
        cfg = self.cfg
        days_idle = (at - entry.last_touch) / 86400.0 if entry.last_touch else 0.0
        dormant = entry.dormant_since is not None or (
            entry.last_touch > 0 and days_idle > cfg.dormant_days
        )
        if dormant:
            return HobbyStatus.DORMANT
        if entry.penalty > 0:
            return HobbyStatus.DOWNWEIGHTED

        equivalent = self._equivalent(entry, at)
        core_ready = (
            equivalent >= cfg.core_itch
            and entry.solo_depth >= cfg.core_depth
            and entry.solo_trials >= cfg.core_trials
            and self._decayed_itch(entry, at) > 0.0
        )
        if core_ready:
            return HobbyStatus.CORE
        if (equivalent >= cfg.trial_itch and entry.solo_depth >= cfg.trial_depth) or (
            entry.solo_trials > 0
        ):
            return HobbyStatus.TRIAL
        if entry.solo_depth > 0 or entry.shared_sessions > 0:
            return HobbyStatus.ACTIVE
        return HobbyStatus.SEED

    # -- 创建与读取 -------------------------------------------------------- #

    def touch(self, hobby_id: str, name: Optional[str] = None) -> HobbyEntry:
        entry = self._rows.get(hobby_id)
        if entry is None:
            ts = self.now()
            entry = HobbyEntry(
                hobby_id=hobby_id,
                name=name or hobby_id,
                last_touch=ts,
            )
            self._rows[hobby_id] = entry
            self._seen_notes[hobby_id] = set()
        elif name and entry.name != name:
            entry.name = name
        return entry

    def get(self, hobby_id: str) -> HobbyEntry:
        if hobby_id not in self._rows:
            raise CogniSeedError(f"账本里没有爱好 {hobby_id!r}")
        return self._rows[hobby_id]

    def entries(self) -> list[HobbyEntry]:
        return [self._rows[k] for k in sorted(self._rows)]

    def history(self, hobby_id: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self._history.get(hobby_id, [])]

    # -- Solo 轨 ----------------------------------------------------------- #

    def observe_content(
        self,
        hobby_id: str,
        content_id: str,
        notes: Sequence[str],
        *,
        at: Optional[float] = None,
        name: Optional[str] = None,
    ) -> HobbyEntry:
        """自主内容消费：把内容拆成原子知识点，累手痒值与深度（按去重计数）。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id, name)
        seen = self._seen_notes.setdefault(hobby_id, set())

        fresh = [n for n in notes if n.strip() and n.strip() not in seen]
        for n in fresh:
            seen.add(n.strip())

        before = self._time_decay(entry, ts)
        gain = self._note_gain(entry, len(fresh))
        entry.solo_itch = before + gain
        entry.solo_itch_at = ts
        entry.solo_depth += len(fresh)
        entry.solo_notes += len(fresh)
        entry.last_touch = ts
        entry.dormant_since = None
        self._log(
            hobby_id,
            "observe_content",
            ts,
            content_id=str(content_id),
            fresh_notes=len(fresh),
            itch=round(entry.solo_itch, 4),
        )
        self._refresh_status(entry, ts)
        return entry

    def record_solo_session(
        self,
        hobby_id: str,
        seconds: float,
        *,
        at: Optional[float] = None,
        notes: Sequence[str] = (),
    ) -> HobbyEntry:
        """一次自主实践（动手练）。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        if seconds < 0:
            raise CogniSeedError("seconds 不能为负")
        hours = seconds / 3600.0
        entry.solo_itch = self._time_decay(entry, ts) + self.cfg.itch_per_hour * hours
        entry.solo_itch_at = ts
        entry.solo_seconds += float(seconds)
        entry.last_touch = ts
        entry.dormant_since = None
        seen = self._seen_notes.setdefault(hobby_id, set())
        fresh = [n for n in notes if n.strip() and n.strip() not in seen]
        for n in fresh:
            seen.add(n.strip())
        entry.solo_depth += len(fresh)
        entry.solo_notes += len(fresh)
        self._log(hobby_id, "solo_session", ts, seconds=seconds, fresh_notes=len(fresh))
        self._refresh_status(entry, ts)
        return entry

    def record_trial(
        self, hobby_id: str, *, passed: bool = True, at: Optional[float] = None
    ) -> HobbyEntry:
        """试水：把学到的东西真拿去用一次（不通过不计入晋升门槛）。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        status = self._status(entry, ts)
        if status in (HobbyStatus.SEED, HobbyStatus.DORMANT):
            raise CogniSeedError(
                f"{hobby_id} 当前 {status.value}，尚未具备试水资格"
                f"（需等效手痒 ≥ {self.cfg.trial_itch} 且深度 ≥ {self.cfg.trial_depth}）"
            )
        if passed:
            entry.solo_trials += 1
        entry.last_touch = ts
        self._log(hobby_id, "trial", ts, passed=bool(passed))
        self._refresh_status(entry, ts)
        return entry

    # -- Shared 轨 --------------------------------------------------------- #

    def record_shared_session(
        self,
        hobby_id: str,
        *,
        initiated_by_agent: bool = True,
        emotional_weight: float = 1.0,
        at: Optional[float] = None,
        name: Optional[str] = None,
    ) -> HobbyEntry:
        """一场共同经历。发起方加权，情感权重线性放大，总权重有上限。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id, name)
        if emotional_weight < 0:
            raise CogniSeedError("emotional_weight 不能为负")
        role = self.cfg.initiated_weight if initiated_by_agent else self.cfg.passive_weight
        gain = self.cfg.shared_gain * emotional_weight * role
        entry.shared_sessions += 1
        if initiated_by_agent:
            entry.shared_initiated += 1
        entry.shared_weight = min(self.cfg.shared_cap, entry.shared_weight + gain)
        entry.last_touch = ts
        entry.dormant_since = None
        self._log(
            hobby_id,
            "shared_session",
            ts,
            initiated=bool(initiated_by_agent),
            emotional_weight=emotional_weight,
            shared_weight=round(entry.shared_weight, 4),
        )
        self._refresh_status(entry, ts)
        return entry

    # -- 刹车阀 ------------------------------------------------------------ #

    def brake(
        self,
        hobby_id: str,
        reason: str,
        *,
        factor: Optional[float] = None,
        at: Optional[float] = None,
    ) -> HobbyEntry:
        """兴趣刹车：负反馈或用户冷淡 → 降权（不是清零，留可恢复空间）。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        k = self.cfg.brake_factor if factor is None else max(0.0, min(1.0, factor))
        entry.solo_itch = self._time_decay(entry, ts) * k
        entry.solo_itch_at = ts
        entry.shared_weight *= k
        entry.penalty = min(1.0, entry.penalty + (1.0 - k))
        entry.brake_reason = reason
        entry.last_touch = ts
        self._log(hobby_id, "brake", ts, reason=reason, factor=k)
        self._refresh_status(entry, ts)
        return entry

    def release(self, hobby_id: str, *, at: Optional[float] = None) -> HobbyEntry:
        """解除刹车：恢复权重保留标记，重新按事实评级。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        entry.penalty = 0.0
        entry.brake_reason = ""
        entry.last_touch = ts
        entry.dormant_since = None
        self._log(hobby_id, "release", ts)
        self._refresh_status(entry, ts)
        return entry

    def sleep(self, hobby_id: str, *, at: Optional[float] = None) -> HobbyEntry:
        """显式休眠：不删数据，只停止主动牵引。"""
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        entry.dormant_since = ts
        entry.status = HobbyStatus.DORMANT
        self._log(hobby_id, "sleep", ts)
        return entry

    def wake(self, hobby_id: str, *, at: Optional[float] = None) -> HobbyEntry:
        ts = at if at is not None else self.now()
        entry = self.touch(hobby_id)
        entry.dormant_since = None
        entry.last_touch = ts
        self._log(hobby_id, "wake", ts)
        self._refresh_status(entry, ts)
        return entry

    # -- 投影 -------------------------------------------------------------- #

    def _refresh_status(self, entry: HobbyEntry, at: float) -> HobbyStatus:
        entry.status = self._status(entry, at)
        return entry.status

    def evaluate_all(self, at: Optional[float] = None) -> dict[str, HobbyStatus]:
        ts = at if at is not None else self.now()
        return {e.hobby_id: self._refresh_status(e, ts) for e in self.entries()}

    def project(self, at: Optional[float] = None) -> list[HobbyProjection]:
        ts = at if at is not None else self.now()
        out: list[HobbyProjection] = []
        for entry in self.entries():
            status = self._refresh_status(entry, ts)
            out.append(
                HobbyProjection(
                    hobby_id=entry.hobby_id,
                    name=entry.name,
                    status=status,
                    solo_itch=self._decayed_itch(entry, ts),
                    solo_depth=entry.solo_depth,
                    solo_trials=entry.solo_trials,
                    shared_weight=entry.shared_weight,
                    equivalent_itch=self._equivalent(entry, ts),
                    days_idle=(ts - entry.last_touch) / 86400.0 if entry.last_touch else 0.0,
                    penalty=entry.penalty,
                    brake_reason=entry.brake_reason,
                )
            )
        return sorted(
            out,
            key=lambda p: (-p.equivalent_itch, -p.solo_depth, p.hobby_id),
        )

    def core_hobbies(self, at: Optional[float] = None) -> list[str]:
        return [p.hobby_id for p in self.project(at) if p.status is HobbyStatus.CORE]

    # -- 序列化 ------------------------------------------------------------ #

    def to_state(self) -> dict[str, Any]:
        return {
            "cfg": self.cfg.to_dict(),
            "rows": {k: v.to_dict() for k, v in self._rows.items()},
            "seen_notes": {k: sorted(v) for k, v in self._seen_notes.items()},
        }

    @classmethod
    def from_state(cls, state: Mapping[str, Any], *, clock: Optional[Clock] = None) -> "HobbyLedger":
        cfg = HobbyConfig(**state.get("cfg", {}))
        ledger = cls(cfg=cfg, clock=clock)
        for key, payload in state.get("rows", {}).items():
            ledger._rows[key] = HobbyEntry.from_dict(payload)
        for key, notes in state.get("seen_notes", {}).items():
            ledger._seen_notes[key] = set(notes)
        return ledger

    def persist(self, store: Any = None, key: str = "hobby:ledger") -> None:
        # 注意：不能用 `store or self.store`——空账本后端 __len__ 为 0，会被当成假值
        st = store if store is not None else self.store
        if st is None:
            raise CogniSeedError("没有可用 store；构造时传入或 persist(store=...)")
        st.save(key, self.to_state())

    def __len__(self) -> int:
        return len(self._rows)
