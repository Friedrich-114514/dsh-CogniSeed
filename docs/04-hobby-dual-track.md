# 04 · 双轨爱好：独自与共享怎么汇流

> 陪伴能拉近距离，不能制造能力。这一篇就是这条边界的具体实现。

---

## 1. 为什么爱好要分两条轨

一个 Agent 的爱好可以来自两种完全不同的过程：

- **Solo（自主轨）**：它自己刷内容、自己练、自己琢磨。产出的是**能力**。
- **Shared（共享轨）**：它和用户一起看过、一起聊过、一起经历过。产出的是**关联**。

这两件事在体验上都很重要，但它们的证据强度完全不同。如果把它们混成一个计数器，
就会出现一种很常见的失真：**一起看了六场电影，第二天它就自称"很懂电影"**。

所以本账本把它们分开记，只在最后一步按系数汇流，并且给共享轨加了一条硬上限：
**纯共享不能晋升 core。**

---

## 2. Solo 轨：手痒值 · 深度 · 试水

### 2.1 手痒值（itch）

手痒值是"想动手"的强度，来自三处：

```text
observe_content  : itch += itch_per_note · n_fresh · depth_diminish^depth
record_solo_session: itch += itch_per_hour · hours
自然冷却          : itch *= exp(-itch_decay_per_day · days)
```

默认：`itch_per_note = 0.25`、`itch_per_hour = 0.05`、`itch_decay_per_day = 0.08`、
`depth_diminish = 0.92`。

两个设计要点：

**（1）边际递减作用在增量上，不作用在累计值上。**
`depth_diminish^depth` 只乘本次新增的增益。如果把整个累计值也乘一遍，深度折减
就会被重复应用两次（写时一次、读时一次），结果手痒值永远涨不到 core 门槛——
这正是本仓库开发过程中真实踩到并修掉的一个 bug。

**（2）冷却让"最近热不热"能被感知。**
一周没碰的东西，手痒值应该降下来，而不是躺在账上装热。`_time_decay` 只按时间
衰减，与深度无关。

### 2.2 深度（depth）

深度 = 该爱好下**去重后**的原子知识点数量。

只认去重计数，因为重复刷同一篇内容不产生新理解。测试里有一条专门的用例：
同一批笔记投两次，深度不变。

### 2.3 试水（trial）

```text
record_trial(hobby_id, passed)
```

试水是"把学到的东西真拿去用一次"。它是一个**显式动作**，不是一个自动推断：

- 状态是 `SEED` 或 `DORMANT` 时不允许试水（抛 `CogniSeedError`）；
- `passed=False` 不计入晋升门槛（失败也算尝试过，但不给分）。

为什么必须显式？因为"它用过没有"这件事，只有接入方知道。库能算的是门槛，
不能替它判断"这一次算不算用出来了"。

### 2.4 晋升 core

```text
core_ready ≜ equivalent_itch ≥ core_itch
           ∧ solo_depth ≥ core_depth
           ∧ solo_trials ≥ core_trials
           ∧ decayed_itch > 0
```

默认 `core_itch = 1.20`、`core_depth = 4`、`core_trials = 1`。

最后一行的 `decayed_itch > 0` 是防"僵尸晋升"：一个被刹车归零、只剩共享权重的
爱好，不该因为折算后数字够线就变成 core。

---

## 3. Shared 轨：折算与发起加权

### 3.1 单场权重

```text
gain = shared_gain · emotional_weight · role_weight
role_weight = initiated_weight (1.00)   若发起方是 Agent
            = passive_weight   (0.55)   若只是被动参与
```

默认 `shared_gain = 0.30`，总权重封顶 `shared_cap = 2.00`。

**发起加权**是本协议的一个立场：主动发起的共同经历比被动陪同更能反映投入。
同一次活动，Agent 策划并邀请 vs. 用户自己看着、它在旁边，权重差 1.8 倍。

`emotional_weight` 是接入方给的系数（1.0 为基准）。它刻意做成外部输入而不是
内部计算——"这场经历对用户有多重要"是模型判断不了的事。

### 3.2 折算成等效手痒

```text
equivalent_itch = decayed_solo_itch + shared_weight · shared_fold
默认 shared_fold = 0.40
```

为什么是折算而不是直接相加？因为 1 点共同经历权重 ≠ 1 点自主手痒。把两者按 1:1
相加，六场电影就能顶掉六条自学知识——这正是我们要避免的失真。0.40 这个系数表达
的是"共同经历对兴趣的推动，大约是自主投入的四成"。

这个数是可以调的，调它就是在调"陪伴在你的产品里占多重"。**建议在接入时明确
想清楚，而不是用默认值糊过去。**

---

## 4. 双向汇流：一个爱好的完整生命周期

```text
 自主内容 ──► 原子知识点 ──► 手痒值 ↑ / 深度 ↑
                                    │
                                    ├──► 试水（拿去用一次）
                                    │         │
                                    ▼         ▼
                              等效手痒 ≥ core_itch ∧ 深度 ≥ core_depth ∧ 试水 ≥ 1
                                    │
 共同场次 ──► 折算 × 0.40 ──────────┤
                                    ▼
                                 CORE（核心爱好）
```

状态流转：

```text
SEED ──(深度>0 或 有共同场次)──► ACTIVE
ACTIVE ──(等效手痒 ≥ trial_itch ∧ 深度 ≥ trial_depth)──► TRIAL
TRIAL ──(过 core 门槛)──► CORE
任意状态 ──(刹车)──► DOWNWEIGHTED ──(release)──► 按事实重新评级
任意状态 ──(闲置 > dormant_days 或显式 sleep)──► DORMANT ──(touch/wake)──► 重新评级
```

默认 `trial_itch = 0.60`、`trial_depth = 2`、`dormant_days = 21`。

评级顺序是固定的：`DORMANT > DOWNWEIGHTED > CORE > TRIAL > ACTIVE > SEED`。
休眠优先级最高——一个休眠的爱好即使账上有分，也不该被主动牵引。

---

## 5. 那条硬规则：纯共享不晋升

```python
core_ready = (... and entry.solo_depth >= cfg.core_depth ...)
```

`solo_depth` 只能由自主内容与自主练习增加。所以：

| 场景 | 深度 | 等效手痒 | 结果 |
|---|---|---|---|
| 六场共同观影，无自主内容 | 0 | 0.8–2.0 | `ACTIVE`，永远不是 `CORE` |
| 两条自学笔记 + 两场共同观影 | 2 | ~1.1 | `TRIAL` |
| 五条自学笔记 + 一次实践 + 一次试水 | 5+ | ≥1.2 | `CORE` |

测试 `test_pure_shared_never_becomes_core` 专门守这条：把 `shared_fold` 调到 1.0、
`shared_cap` 调到 5.0，让六场共同经历的等效手痒**超过** core 门槛，断言状态仍然
不是 `CORE`。

这条规则的实际效果是：它不会说"我不喜欢和你一起看电影"，它只会说"这件事我还
没到能主导的水平"。这两句话在体验上差别很大，而后者是诚实的。

---

## 6. 兴趣刹车阀与休眠

### 6.1 刹车

```python
ledger.brake(hobby_id, reason, factor=0.5)
```

效果：手痒与共享权重各乘 `factor`，`penalty += (1 - factor)`，状态转 `DOWNWEIGHTED`。

为什么是"降权"不是"清零"：

- 用户某天不想聊这个，不代表永远不想聊；
- 清零是不可逆的信息损失，降权是可恢复的；
- `release()` 把 `penalty` 归零，让账本按**事实**重新评级——注意它不会把权重
  补回去，那是伪造历史。

### 6.2 休眠

两条路径：显式 `sleep()`，或闲置超过 `dormant_days` 自动判定。

休眠不删数据，只做两件事：停止偏置引擎的主动牵引（权重 ×0.6），以及在投影里
标成 `DORMANT`。`observe_content` / `record_shared_session` 会清掉 `dormant_since`
把它唤醒——**用户提一句，它就活过来**，不需要额外动作。

这是"不打扰"与"不丢失"之间的平衡点。

---

## 7. 参数表

| 参数 | 默认 | 含义 | 调大的效果 |
|---|---|---|---|
| `itch_per_note` | 0.25 | 每条新知识的手痒增量 | 更快到试水/核心 |
| `itch_per_hour` | 0.05 | 自主实践每小时的增量 | 动手比看内容更值钱 |
| `itch_decay_per_day` | 0.08 | 手痒冷却速率 | 热度掉得更快 |
| `depth_diminish` | 0.92 | 深度对增量的折减 | 越深越难涨 |
| `trial_itch` | 0.60 | 试水门槛 | 更难试水 |
| `trial_depth` | 2 | 试水门槛（深度） | 更难试水 |
| `core_itch` | 1.20 | 核心门槛 | 更难晋升核心 |
| `core_depth` | 4 | 核心门槛（深度） | 更难晋升核心 |
| `core_trials` | 1 | 核心门槛（试水次数） | 要求反复验证 |
| `shared_fold` | 0.40 | 共同经历折算系数 | 陪伴占比更重 |
| `shared_gain` | 0.30 | 单场共同经历基准权重 | 单场更有分量 |
| `initiated_weight` | 1.00 | 主动发起权重 | — |
| `passive_weight` | 0.55 | 被动参与权重 | 主被动的差距更大 |
| `shared_cap` | 2.00 | 共同权重上限 | 陪伴的累积上限更高 |
| `dormant_days` | 21 | 闲置多久算休眠 | 更耐放 |
| `brake_factor` | 0.50 | 刹车后保留比例 | 刹车更轻 |

---

## 8. 反模式

| 反模式 | 问题 |
|---|---|
| 把 `shared_fold` 调到 1.0 以上 | 共同经历比自学更值钱 → 纯陪伴也能晋升 → 本文档的整个立论失效 |
| 每次互动都 `record_shared_session` | 权重迅速触顶，`initiated_by_agent` 的区分失去意义 |
| 用 `solo_depth += 1` 而不是按去重笔记计数 | 重复刷同一篇内容会灌深度 |
| 刹车后直接清零 | 不可恢复，用户改主意时接不回来 |
| 手动静止 `status` 字段 | 状态是投影，每次读取时重算；手改会在下次 `evaluate` 被覆盖 |

最后一条值得重复：`HobbyEntry.status` 是**派生字段**。任何"直接设成 CORE"的写法
都会在下一次 `project()` / `evaluate_all()` 时被打回原形——这是有意的，因为
可手设的状态就是第二个好感度数字。
