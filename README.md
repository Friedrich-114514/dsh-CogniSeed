# dsh-CogniSeed

dsh-CogniSeed 是一个框架无关的 Python 零依赖认知成长与爱好演化引擎，定位为 DSH（及插件桥接型 AI 伴侣架构）的核心状态模块。

传统伴侣系统常依赖定时公式让亲密度或性格数值随时间自动微调（数值漂移），缺少真实的知识沉淀；dsh-CogniSeed 则将成长严格锚定在「知识摄入 → 睡眠巩固 → 场景迁移」的闭环上：性格特质变化仅作为知识掌握后的只读投影，爱好演化由认知深度与实际试水共同驱动，并内置防模型顺从装懂的校验防线。

## 一、核心机制：四阶认知阶梯与巩固三判据

引擎将每个知识点建模为受状态机管控的 KnowledgeNode，并引入贴合昼夜作息的处理节奏：清醒窗口限量吸收（默认活跃领域上限 5 个、每日新增上限 2 个），睡眠窗口执行艾宾浩斯遗忘衰减与无提示盲测。

```
[日常对话 / 内容观察 / 共同经历]
│
▼ (每日新增上限 ≤ 2，活跃领域上限 ≤ 5)
┌─────────────────────┐
│ S1: 感知 (Perceived) │ ── 首次接触，提取原子知识点
└──────────┬──────────┘
│ 当轮用自己的话复述要点
▼
┌─────────────────────┐
│ S2: 模仿 (Imitated) │ ── 短期工作记忆阶段，尚未经过遗忘过滤
└──────────┬──────────┘
│ 经历 ≥ 1 次夜间睡眠巩固周期（艾宾浩斯衰减结算）
▼
┌─────────────────────┐
│ S3: 练习 (Practiced) │ ── 跨夜变式练习 / 模拟环境试错 / 错题留痕
└──────────┬──────────┘
│ 同时满足(A睡眠留存 ∧ B延迟盲测 ∧ C场景迁移)
▼
┌─────────────────────┐
│ S4: 掌握 (Mastered) │ ── 正式掌握：触发性格特质投影 & 推进爱好转化
└─────────────────────┘
```

### 晋升 S4_MASTERED 的三联客观判据（缺一不可）

系统不采信模型自评（如“我学会了”），节点从 S3 晋升至 S4 必须同时满足以下三项可验证条件：

- 判据 A（睡眠留存过阈）：完整经历至少 2 个睡眠巩固周期的艾宾浩斯衰减结算，且在无外部强提醒的情况下自然留存分 retention_score ≥ 0.70。
- 判据 B（延迟无提示复述）：在后续睡眠周期的延迟盲测环节（默认距进入 S3 至少 6 小时），不提供原始对话摘要，仅给定领域关键词提示，模型能用自己的语言准确还原核心因果（允许细节自然模糊，禁止编造）。
- 判据 C（场景应用或跨情境迁移）：在后续模拟实践或真实交互中，主动调用该知识指导行动，或将其原理迁移至未教过的变式情境（例如：掌握“炒青菜大火快炒锁水”后，在模拟炒豆芽时主动复用同一做法）。

此外，S3 阶段还需通过至少 1 次换表述的变式练习，用来验证模型不是只会背原句。

## 二、双轨爱好账本与注意力软偏置

为了打通“看了很多内容但无法转化为稳定爱好”的断点，引擎内置了独自型（Solo）与共享型（Shared）双轨爱好账本（HobbyLedger）：

- 独自轨（Solo Track）：当在学池存在活跃主题时，偏置引擎会生成温和的注意力软偏置（仅调整候选权重，默认保留 15% 的均匀探索槽位，不做硬过滤，也不影响正常娱乐浏览）。观看内容时把值得记的原子知识点记入账本，手痒值与去重深度随之累积；知识积累推动认知深度达标后解锁“下场试水”，经试水巩固转化为核心爱好。
- 共享轨（Shared Track）：与用户共同讨论、观看或参与的兴趣事件会记录在共享轨中，按 0.40 的折算系数计入等效手痒，并对 Agent 主动发起的场次加权（发起 1.00 / 被动 0.55），支持“独自萌芽 → 共享升温”与“共同种草 → 独自深挖”的双向汇流。

动态刹车与自然退场：

- 没兴趣刹车：若某学习方向连续出现跳过或低手痒值，可调用 `brake()` 降权（默认保留 50% 权重，不清零）；长期不碰则转入 `DORMANT` 休眠，数据保留，一次触碰即可唤醒。
- 学成退场：某领域知识点全部升至 S4 后，该领域的阶段权重回落到 ×0.85，不再作为在学重点主动加推；知识点与迁移留痕仍保留在学籍表中。

## 三、防装懂四道防线与隐私边界

针对大语言模型常见的顺从复读（装懂）倾向，引擎在校验链路中设置了四项约束：

- 反向情境诱导探针：在刚接触知识点后，于模拟场景中植入带干扰项的反向问题（例如刚学完“切完辣椒忌用热水洗手”，随后在模拟情境中询问“要不要用烫水冲一下”）。若模型顺从答应，直接拦截晋升并将错误记录写入 `registry.corrections`。
- 跨睡眠周期隔离验证：所有有效复述与变式判断均要求脱离短期对话上下文窗口（Context Window）后完成。
- 边界探针：询问学籍表中必然不存在的出处、页码或链接，命中“不知道 / 没有记录”才算过关；编造书名、页码或链接则判为作弊并留痕。
- 不回溯用户聊天原文：所有校验探针与状态评估均基于 Agent 自身生成的日记、独白与模拟行为日志完成，不检索或比对用户的历史聊天原文。

## 四、5 分钟快速上手（DSH 桥接接入）

仓库无任何第三方强制依赖，支持 JSON 与 SQLite 两种本地持久化方式，并附带了面向 DSH 插件桥接架构的完整参考实现。

### 1. 克隆仓库并运行测试

```bash
git clone https://github.com/Friedrich-114514/dsh-CogniSeed.git
cd dsh-CogniSeed

# 使用 Python 标准库运行 70 个内置单元测试与验收探针
python -m unittest discover -s tests
```

### 2. 核心引擎最小可运行示例

```python
from cogniseed import ConsolidationEngine, HobbyLedger, JsonStore, LearningRegistry

T0 = 1_800_000_000.0
H = 3_600.0

# 1. 初始化存储与核心引擎
store = JsonStore("./state/cogniseed_state.json")
registry = LearningRegistry(store=store, clock=lambda: T0)
hobbies = HobbyLedger(store=store, clock=lambda: T0)
consolidation = ConsolidationEngine(
    verifier=lambda expected, candidate: len(set(expected) & set(candidate)) >= 8,
    answerer=lambda prompt: "先把锅烧热再倒凉油，利用油膜隔开食材防粘",
    clock=lambda: T0,
)

# 2. 摄入新知识 (S1)
node = registry.add_node(
    "基础烹饪",
    "热锅冷油防粘锅：先把锅烧热，再倒凉油，利用油膜隔开食材",
    "agent_note",
)

# 3. 当轮复述 (S2) & 记录独自轨内容观察
registry.restate(node.node_id, "先把锅烧热再倒凉油，靠油膜防粘", passed=True)
hobbies.observe_content(
    "cooking",
    "video_001",
    ["热锅冷油能减少食材与锅面的直接接触"],
)

# 4. 执行 2 个夜间睡眠周期结算（S1→S2→S3）
consolidation.run_cycle(registry, at=T0 + 24 * H)
consolidation.run_cycle(registry, at=T0 + 48 * H)
print("在学焦点:", registry.recently_mulling())

# 5. 提交跨场景迁移证据 (判据 C)；判据 B 由 verifier/answerer 在周期内完成
registry.record_transfer(node.node_id, "practice: 煎豆腐前先热锅再下冷油", at=T0 + 49 * H)
consolidation.run_cycle(registry, at=T0 + 72 * H)   # 晋升 S4

# 6. 获取轻量状态投影（可直接注入对话上下文）
print("人格增量:", registry.persona_total)
print("阶段统计:", registry.stats(at=T0 + 72 * H)["stages"])

registry.persist()
hobbies.persist()
store.close()
```

运行输出：

```text
在学焦点: [{'node_id': 'kn-9efa3f126c', 'domain': '基础烹饪', 'statement': '热锅冷油防粘锅：先把锅烧热，再倒凉油，利用油膜隔开食材', 'stage': 'S3', 'stage_label': '巩固', 'retention': 0.8056, 'sleep_cycles': 2}]
人格增量: {'基础烹饪': 0.024243}
阶段统计: {'S1': 0, 'S2': 0, 'S3': 0, 'S4': 1}
```

### 3. DSH 插件桥接接入点

参考实现位于 `examples/dsh-bridge/`（`PROTOCOL.md` + `bridge.py` + `plugin.js`）：插件把事件写成 `intake/` 下的 JSON 文件，核心侧消费后把只读投影写到 `outbox/projection.json`。只需在 DSH 插件生命周期中挂载三个钩子即可完成集成：

- 输入与信息流后置钩子：在内容浏览或对话教学结束后调用 `registry.add_node()` 写入待学池；同时通过 `BiasEngine.weights()` 获取当前软偏置权重，用于微调后续内容推荐权重。
- 夜间例程定时钩子：挂载在凌晨睡眠巩固与夜间日记任务中，触发 `consolidation.run_cycle(registry)` 执行艾宾浩斯衰减计算与盲测校验。
- 对话前置上下文注入：在生成回复前读取 `registry.recently_mulling()` 与 `registry.persona_projection()`，将当前在学焦点与已掌握进展作为轻量状态投影注入上下文。

## 五、仓库结构与设计白皮书

完整的架构规范与算法细节沉淀在 docs/ 目录下的五篇白皮书中：

```
dsh-CogniSeed/
├── README.md / README.en.md
├── LICENSE # MIT
├── pyproject.toml
├── docs/ # 设计白皮书与机制规范
│ ├── 01-manifesto.md # 核心原则：知识巩固驱动成长的边界定义
│ ├── 02-cognitive-ladder.md # 四阶认知发育模型 (S1感知 → S4掌握)
│ ├── 03-consolidation-protocol.md # 睡眠巩固引擎与三联验证判据规范
│ ├── 04-hobby-dual-track.md # 独自探索与共同经历双轨爱好演化机制
│ └── 05-anti-hallucination.md # 防假学四道防线与数据访问边界
├── cogniseed/ # Python 零依赖核心引擎包
│ ├── models.py # 核心数据结构 (KnowledgeNode, HobbyTrack 等)
│ ├── registry.py # 学籍表与容量/配额控制器
│ ├── ladder.py # S1→S4 状态机与晋升判据
│ ├── consolidation.py # 衰减计算、状态机校验与睡眠周期结算
│ ├── hobby_ledger.py # 双轨爱好账本与刹车/退场逻辑
│ ├── bias_engine.py # 注意力软偏置生成器
│ ├── anti_cheat.py # 反向探针与错题留痕管理
│ └── storage/ # JsonStore / SqliteStore 存储实现
├── examples/ # 集成示例与模拟脚本
│ ├── 01-quickstart.py
│ ├── 02-sleep-cycle-demo.py
│ ├── 03-hobby-dual-track.py
│ └── dsh-bridge/ # PROTOCOL.md + bridge.py + plugin.js
└── tests/ # 70 个单元测试与验收探针集
```

## 六、路线图（Roadmap）

- [x] v0.1：零依赖 Python 核心引擎、五篇架构白皮书、DSH 插件桥接参考实现、70 个单元测试与验收探针。

后续方向视反馈而定。

## 开源协议

本项目基于 MIT License 开源。
