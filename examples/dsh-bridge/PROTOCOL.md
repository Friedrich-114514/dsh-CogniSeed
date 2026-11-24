# DSH 插件 ↔ CogniSeed 文件桥接协议 v1

DSH 插件跑在宿主（Node.js）里，CogniSeed 核心跑在 Python 里。两者不共享进程，
也不通过网络互相调用——只通过**磁盘上的 JSON 文件**交换状态。这样插件崩了不会
拖死学籍表，核心升级也不用重装插件。

核心侧的唯一依赖是 `cogniseed.storage.JsonStore`，也就是那个用
`{"version": 1, "rows": {...}}` 包起来的 JSON 文件。任何能写这个格式的程序都能
替换掉 `bridge.py`。

---

## 1. 目录布局

```text
<DATA_DIR>/
├── intake/                  # 插件写：一个事件一个文件，事件名 <seq>-<event_id>.json
├── archive/                 # 核心写：已消费事件搬到这里（留痕，不删除）
├── archive/rejected/        # 核心写：校验失败的事件
├── outbox/
│   ├── projection.json      # 核心写：只读投影（模棱两可的事 + 人格 + 爱好）
│   └── status.json          # 核心写：消费游标与计数
└── state/
    ├── registry.json        # 核心写：JsonStore 文件（学籍表 + 爱好账本）
    └── pending_answers.json # 核心写：等待睡眠结算使用的作答（由 sleep.trigger 带来）
```

**写入规则**：谁写谁负责原子化。先写 `<name>.tmp`，再 `rename` 成正式文件名。
读方只认不带 `.tmp` 后缀的文件——这样永远不会读到半截 JSON。

**所有权**：`intake/` 归插件，`outbox/`、`state/`、`archive/` 归核心。插件只读
`outbox/projection.json`，绝不直接改 `state/`。

---

## 2. 事件信封

```json
{
  "protocol": "cogniseed.bridge/1",
  "event_id": "evt-7f3c1a9e",
  "kind": "note",
  "at": 1800000000.0,
  "payload": { }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `protocol` | string | 固定 `cogniseed.bridge/1`，不匹配直接拒收 |
| `event_id` | string | 插件侧唯一；核心用它去重与留痕 |
| `kind` | string | 见下表 |
| `at` | number | Unix 秒（float）。缺省时核心用收到的时间 |
| `payload` | object | 按 `kind` 定义 |

`at` 由**插件**给，不由核心补：插件的时钟才是真实交互发生的时刻。

---

## 3. 事件类型

| `kind` | payload | 对应核心调用 |
|---|---|---|
| `note` | `{domain, statement, source?, tags?}` | `registry.add_node` |
| `restatement` | `{node_id, text, passed}` | `registry.restate` |
| `transfer` | `{node_id, context}` | `registry.record_transfer` |
| `hobby.observe` | `{hobby_id, content_id, notes[], name?}` | `ledger.observe_content` |
| `hobby.solo` | `{hobby_id, seconds, notes?[]}` | `ledger.record_solo_session` |
| `hobby.shared` | `{hobby_id, initiated_by_agent?, emotional_weight?}` | `ledger.record_shared_session` |
| `hobby.brake` | `{hobby_id, reason, factor?}` | `ledger.brake` |
| `sleep.trigger` | `{answers?, cycles?}` | `ConsolidationEngine.run_cycle` |

`source` 只允许 `agent_note` 与 `behavior_log`。插件的聊天原文**不许**作为来源
投进来——白名单会抛 `PrivacyViolation`，事件进 `archive/rejected/`。这是隐私硬线
在协议层的落点：插件负责把「用户原话」变成「Agent 自产笔记」，核心只认后者。

### 3.1 关于 `sleep.trigger.answers`

睡眠结算里有两件事必须由**宿主侧**回答，核心不代劳：

1. 变式练习与延迟盲测的**答案**——只有宿主的 Agent 会说话。
2. 语义等价比对——哪两句算「一个意思」。

所以协议这样分工：

```json
{
  "kind": "sleep.trigger",
  "at": 1800010000.0,
  "payload": {
    "answers": {
      "kn-a94b7e4786": "把温度稳在蛋白质变性区间，不要追求更高温度"
    },
    "verifier": "keyword"
  }
}
```

- `answers`：`node_id -> 该节点的作答文本`。缺某节点即视为该节点未作答（按未通过处理）。
- `verifier`：校验器名字。`bridge.py` 只实现了 `keyword`（字符重合 ≥ 8，**演示替身**）。
  生产做法是把它换成一次 LLM 调用，签名仍是 `Callable[[str, str], bool]`：
  `verifier(expected_statement, candidate_answer) -> bool`。

核心库本身不含任何 LLM 客户端，这一点在协议上就体现为「校验器名由宿主指定」。

---

## 4. 投影（`outbox/projection.json`）

```json
{
  "protocol": "cogniseed.bridge/1",
  "generated_at": 1800010000.0,
  "mulling": [
    {"node_id": "kn-…", "domain": "基础烹饪", "statement": "…",
     "stage": "S3", "stage_label": "巩固", "retention": 0.9, "sleep_cycles": 3}
  ],
  "persona": {"基础烹饪": 0.0271},
  "hobbies": [
    {"hobby_id": "基础烹饪", "status": "core", "equivalent_itch": 1.517,
     "solo_depth": 6, "shared_weight": 0.45}
  ],
  "stats": {"nodes": 2, "stages": {"S1": 0, "S2": 0, "S3": 1, "S4": 1}, "...": "…"}
}
```

插件只读这个文件。「最近在琢磨的事」直接取 `mulling`；人格增量取 `persona`。
**投影是只读的**：插件没有任何写入口，改这个文件不会影响学籍表（下次 `project`
会覆盖回去）。

---

## 5. 时序

```text
插件                                   核心（bridge.py）
 │                                        │
 │  1. 交互发生，插件判定它是 agent_note    │
 │  ── intake/000001-evt-….json ────────► │  2. ingest：校验 → 派发 → archive
 │                                        │     registry.add_node / restate / transfer
 │  3. 睡眠窗口到点                        │
 │  ── intake/…-sleep.trigger.json ─────► │  4. settle：run_cycle（带 answers + verifier）
 │                                        │     → 可能晋升 S4 → 产出人格增量
 │  5. 需要「它在琢磨什么」                 │
 │  ◄── outbox/projection.json ────────── │  6. project：写只读投影
 │                                        │
```

一次 `ingest` 可以吃任意多个事件；核心按文件名排序消费，保证顺序稳定。

---

## 6. 跑起来

```bash
# 1. 初始化目录并跑一遍端到端演示（虚构数据）
python examples/dsh-bridge/bridge.py demo --data ./tmp-bridge

# 2. 分步跑
python examples/dsh-bridge/bridge.py --data ./tmp-bridge init
python examples/dsh-bridge/bridge.py --data ./tmp-bridge ingest
python examples/dsh-bridge/bridge.py --data ./tmp-bridge settle --at 1800010000
python examples/dsh-bridge/bridge.py --data ./tmp-bridge project
python examples/dsh-bridge/bridge.py --data ./tmp-bridge status
```

插件侧骨架 `plugin.js`（Node 18+，无依赖）：

```js
const { createBridge } = require("./plugin.js");
const bridge = createBridge({ dataDir: "./tmp-bridge" });

await bridge.emit("note", {
  domain: "基础园艺",
  statement: "浇水要看土壤干湿而不是固定天数",
  source: "agent_note",
});

const projection = await bridge.readProjection();
console.log(projection.mulling);
```

---

## 7. 兼容性约束

- 协议版本只有 `cogniseed.bridge/1`。加字段可以，改语义必须升版本号。
- 事件是**幂等**的：`note` 用 `(domain, statement)` 去重，`event_id` 重复投递不重复计账。
- 核心不删除 `archive/`。要做保留期策略，由宿主侧的清理任务负责。
- 后端可换：`state/registry.json` 换成 SQLite（`SqliteStore`，表 `learning_registry`）
  时，只需把 `bridge.py` 里那一处 `JsonStore(...)` 换掉，协议不动。
