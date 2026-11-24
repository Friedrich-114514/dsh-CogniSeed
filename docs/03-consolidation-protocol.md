# 03 · 巩固协议：睡眠周期与三联判据

> 这一篇是整套系统里唯一"有数学"的部分。它的目标很窄：**给「它真的学会了」
> 这个断言提供可以被推翻的证据链。**

---

## 1. 为什么是「睡眠」

清醒时吸收是限量的。这不是诗意的说法，是工程约束：白天的事件流是突发的、无界的，
如果摄入即定型，学籍表会被热搜式的碎知识填满，而每一条都没有被真正处理过。

所以本协议把「定型」推迟到睡眠周期里做，并且只做四件事：

1. **衰减**：按遗忘曲线把每条知识算一遍现在的留存；
2. **再巩固**：对还在的知识做一次复习增益，并把稳定性往上抬一档；
3. **变式练习**：换说法复述，防「只会背原句」；
4. **延迟盲测 + 判据校验**：决定能不能升 S4。

一个睡眠周期是一个原子操作：要么整批结算完成，要么这批不动（`run_cycle` 在内存
里改完后由 `registry.record_cycle` 一次性入账）。

---

## 2. 衰减：艾宾浩斯形式

### 2.1 公式

```text
R(t) = R₀ · exp( -Δt / S )

其中：
  R₀   上次复核后的留存（0..1）
  Δt   距上次复核的小时数
  S    稳定性（小时），随成功次数增长
```

`S` 不是常数，这是本协议与教科书艾宾浩斯的关键差异：

```text
S = base_stability_hours
    × ( 1 + stability_growth · blind_test_passes )
    × ( 1 + 0.25 · sleep_cycles )
```

默认 `base_stability_hours = 72`、`stability_growth = 0.65`。

含义：**复习不是在曲线上把数值加回去，而是让曲线本身变缓。**
一个盲测通过 3 次、经过 6 个周期的知识点，遗忘速度是一个新知识点的数倍之慢。
这才符合"越熟越不容易忘"的直觉；固定半衰期的模型做不到这一点。

### 2.2 再巩固

```text
R' = R_decayed + review_gain · (1 - R_decayed)
   , review_gain = 0.45（默认）
```

这是一次"向 1.0 靠拢但永不到达"的更新。它有两个重要性质：

- **单调有界**：`R' ∈ [R_decayed, 1.0]`，不会因为复习而超过 1；
- **边际递减**：留存已经很高时，复习带来的增量很小——符合"已经很熟了，再看一遍
  收益不大"。

同时 `sleep_cycles += 1`，这是判据 A 的一个输入。

### 2.3 回退看的是"复习前"

实现里有一个容易写错的细节：

```python
decayed = retention_at(node, ts, cfg)   # 先量衰减
refresh(node, ts, cfg)                  # 再复习
if decayed < cfg.demote_floor:          # 用衰减值判回退
    ladder.demote(node, ...)
```

**必须用复习前的值判断回退。** 如果用复习后的值，那么 `R' ≥ review_gain = 0.45`
恒成立，而默认 `demote_floor` 也是 0.45——回退分支永远不会触发，遗忘就成了摆设。
这是"看起来做对了、其实永远走不到"的典型 bug。

---

## 3. 三联判据

升 S4 需要四条同时成立（三条判据 + 变式练习）。每一条防的是不同的东西。

### 判据 A：留存与周期数

```text
A ≜ (retention ≥ retention_floor) ∧ (sleep_cycles ≥ min_sleep_cycles)
默认 retention_floor = 0.70, min_sleep_cycles = 2
```

- 只测留存不够：刚摄入时留存天然是 1.0，一条**完全没被处理过**的知识也满足
  `retention ≥ 0.70`。所以必须叠加周期数。
- 只测周期数也不够：某个周期里睡过去了（异常、跳过）也算"经过了"，但留存可能
  已经崩了。

两个条件互为补丁，缺一个就能被绕。

### 判据 B：延迟盲测

```text
B ≜ (blind_test_passes ≥ 1) ∧ (交付时距进入 S3 ≥ blind_test_delay_hours)
```

盲测的"盲"有两层含义：

1. **不给原句。** 提示词只有领域名和"说出关键要点"，不给待复述的文本；
2. **延迟。** 默认要求距进入 S3 至少 6 小时。当天问当天答，测的是工作记忆。

判定走**回调钩子**：

```python
Verifier = Callable[[str, str], bool]
# verifier(expected_statement, candidate_answer) -> bool
```

接入方自己传。可以是 LLM 判定、可以是嵌入相似度、可以是一条规则、可以是人。
核心库不知道也不关心。

### 判据 C：行为迁移

```text
C ≜ (len(transfer_refs) ≥ 1)，且来源必须是 behavior_log
```

`TransferRecord` 在构造时校验来源，非 `behavior_log` 直接抛 `PrivacyViolation`。
这条校验是刻意的：它同时挡掉了两件事——**自我报告的"我会用了"**，和**伪造的
迁移证据**。

这一条也是最难满足的，因为它要求 Agent 真的在行为层做过一次应用。这恰恰是
"聊三句露馅"的解药：会背和会用是两条通路，只有后者能在被追问第三层细节时撑住。

### 变式练习

```text
变式 ≜ variations_passed ≥ 1
```

判据 B 只测一次复现。变式练习测的是"换个问法还认不认得"：

```python
variation_drills(node)
# → ["换一种说法复述这条知识，不要用原句：{statement}",
#    "举一个具体例子说明这条知识在实践中怎么用：{statement}",
#    "什么情况下这条知识不成立或要打折？如果不能确定，直接说没有记录：{statement}"]
```

提示词是纯模板生成，不调模型——因此可复现、可测试、不花钱。判定仍走同一个
`Verifier`。

---

## 4. 为什么判据接口必须是回调，而不是内置客户端

三条理由，按重要性排序：

**（1）可测试性。** 本仓库的测试用两个朴素的假实现（字符重合判定 + 固定答案）
就能覆盖全部判定分支，跑完 0.1 秒。一旦核心内置 HTTP 客户端，测试就得起 mock
服务，或者打真实 API——两种都会让"跑通"变成一个含糊的说法。

**（2）零依赖是硬约束。** 内置客户端意味着引入 `requests`/`httpx`、重试策略、
超时策略、密钥管理、错误码映射。这些东西每一位接入方都有自己的偏好，塞进核心
只会制造冲突。

**（3）判定标准本来就该由接入方定。** "这两句话算不算一个意思"是业务语义问题，
不是一个通用库能替它回答的问题。中文的近义、方言、行业黑话，只有接入方清楚。

回调的代价是接入方多写一个函数。这个代价是值得的。

---

## 5. 睡眠调度：配置化，不写死

```python
@dataclass(frozen=True)
class SleepScheduleConfig:
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
```

`cycle_slots(day)` 按 `night_start_hour → night_end_hour` 均分给出当日的结算时刻。
默认值只是一份通用昼夜节律模板，**不写死任何真实作息**——真实作息属于部署侧配置，
不在本规范范围内。

`is_night(ts)` 处理跨零点窗口（23:00 → 次日 07:00）。

---

## 6. 一个周期的伪代码

```text
run_cycle(registry, at):
    cycle = SleepCycle(id=..., started_at=at)
    for node in registry.nodes():
        if node.frozen:                      # 冻结节点跳过
            cycle.skipped.append(node.id); continue

        entry_stage = node.stage
        decayed = retention_at(node, at)     # 1. 先量衰减
        refresh(node, at)                    # 2. 再巩固，sleep_cycles += 1
        cycle.reviewed.append(node.id)

        if entry_stage == S3:                # 3. 变式 + 盲测（只对本周期前已是 S3 的）
            drill(node, at)

        evidence = evidence_for(node) if node.stage == S3 else None
        tr = ladder.transition(node, evidence, at)   # 4. 至多上一级
        if tr.changed: cycle.promoted.append(node.id)

        if node.stage == S4 and not emitted(node):
            registry.emit_delta(ladder.persona_delta(node, at))   # 5. 只读投影，一次

        if decayed < demote_floor and node.stage > S1:            # 6. 回退
            ladder.demote(node, at, reason=...)

    registry.record_cycle(cycle)
```

三个易错点，都在上面标了位置：

- 第 3 步用 `entry_stage` 而不是 `node.stage`：否则刚升到 S3 的节点会在**同一个
  周期**里立刻被盲测，延迟判据就形同虚设。
- 第 5 步用 `emit_delta` 而不是直接 append：同一个节点只投影一次，否则每个周期
  都会加一点点——那就又变成定时漂移了。
- 第 6 步用 `decayed`：见 2.3。

---

## 7. 反模式清单

写接入代码时，以下五条都会让整套判据失效，而且失效得很难发现：

| 反模式 | 后果 | 症状 |
|---|---|---|
| `verifier = lambda e, c: True` | 判据 B 恒过 | 所有节点 3 周期内全 S4，人格迅速涨满 |
| 盲测与变式用同一个提示词 | 测不出"换问法就不认得" | 变式通过率与盲测通过率完全一致 |
| `blind_test_delay_hours = 0` | 测的是工作记忆 | 当场记住的东西也被判为掌握 |
| 每个周期都 `emit_delta` | 退化为定时漂移 | 人格曲线是一条直线 |
| 用复习后的留存判回退 | 回退永不触发 | 遗忘机制形同不存在 |

判断有没有踩坑，最快的办法是看 `SleepRun.report()`：如果第一周期就有大量节点
跳到 S4，几乎一定是 A 或 B 被绕过了。

---

## 8. 失败分支

| 情况 | 行为 |
|---|---|
| 未提供 `verifier` / `answerer` | S3 练习整段跳过，节点停在 S3，`notes` 里写明原因 |
| 回调抛异常 | 该次练习按未通过处理，异常类型与消息进 `notes`，不中断整批 |
| `answerer` 对某节点无答案 | 返回空串 → 判据 B 不通过（不是"默认通过"） |
| 盲测已通过 3 次 | 不再消耗盲测，`blind_test_passes` 封顶 |
| 节点 `frozen=True` | 整节点跳过，`sleep_cycles` 不增 |
| 复核前留存 < `demote_floor` | 回退一级，记入 `cycle.demoted` |

设计原则只有一条：**任何缺失都向"不通过"收敛，不向"通过"收敛。**
