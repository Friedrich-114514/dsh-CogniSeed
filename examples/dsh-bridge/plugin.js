"use strict";
/**
 * CogniSeed ↔ DSH 插件桥接骨架（协议级示例，不做 JS 全量重实现）
 *
 * Node 18+，零依赖。协议见 ./PROTOCOL.md。
 *
 * 这个文件的职责边界写在最前面，免得被误当成第二个实现：
 *   - 它只把宿主里发生的事**写成事件文件**，扔进 <dataDir>/intake/
 *   - 它只**读** <dataDir>/outbox/projection.json
 *   - 它不计算阶段、不留存知识点、不判定语义——那些全在 Python 核心里
 *
 * 用法：
 *     const { createBridge } = require("./plugin.js");
 *     const bridge = createBridge({ dataDir: "./tmp-bridge" });
 *     await bridge.init();
 *     await bridge.emitNote({ domain: "基础园艺", statement: "浇水看土壤干湿" });
 *     const projection = await bridge.readProjection();
 */

const fs = require("fs/promises");
const path = require("path");
const crypto = require("crypto");

const PROTOCOL = "cogniseed.bridge/1";

const KINDS = new Set([
  "note",
  "restatement",
  "transfer",
  "hobby.observe",
  "hobby.solo",
  "hobby.shared",
  "hobby.brake",
  "sleep.trigger",
]);

/** 原子写：先写 .tmp 再 rename。读方只认不带 .tmp 的文件。 */
async function writeAtomic(target, payload) {
  await fs.mkdir(path.dirname(target), { recursive: true });
  const tmp = `${target}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(payload, null, 2) + "\n", "utf8");
  await fs.rename(tmp, target);
}

async function readJsonIfExists(target, fallback = null) {
  try {
    const text = await fs.readFile(target, "utf8");
    return text.trim() ? JSON.parse(text) : fallback;
  } catch (err) {
    if (err.code === "ENOENT") return fallback;
    throw err;
  }
}

function newEventId(kind, at, payload) {
  const digest = crypto
    .createHash("sha1")
    .update(`${kind}|${at}|${JSON.stringify(payload)}`)
    .digest("hex")
    .slice(0, 8);
  return `evt-${digest}`;
}

function createBridge(options = {}) {
  const dataDir = path.resolve(options.dataDir || "./tmp-bridge");
  const now = options.clock || (() => Date.now() / 1000);
  const log = options.logger || console;

  const dirs = {
    root: dataDir,
    intake: path.join(dataDir, "intake"),
    archive: path.join(dataDir, "archive"),
    outbox: path.join(dataDir, "outbox"),
    projection: path.join(dataDir, "outbox", "projection.json"),
    status: path.join(dataDir, "outbox", "status.json"),
  };

  let seq = 0;
  let watcher = null;

  async function init() {
    await Promise.all(
      [dirs.intake, dirs.archive, dirs.outbox].map((d) =>
        fs.mkdir(d, { recursive: true })
      )
    );
    // 序号接着已有事件走，保证文件名单调递增（核心按文件名排序消费）
    try {
      const names = await fs.readdir(dirs.intake);
      const max = names
        .filter((n) => /^\d{6}-/.test(n))
        .reduce((acc, n) => Math.max(acc, parseInt(n.slice(0, 6), 10)), 0);
      seq = max;
    } catch (err) {
      if (err.code !== "ENOENT") throw err;
    }
    return dirs;
  }

  /**
   * 投递一个事件。
   * @param {string} kind  见 KINDS
   * @param {object} payload
   * @param {number} [at]  Unix 秒；缺省用宿主时钟
   */
  async function emit(kind, payload, at) {
    if (!KINDS.has(kind)) throw new Error(`未知 kind: ${kind}`);
    if (payload == null || typeof payload !== "object") {
      throw new Error("payload 必须是对象");
    }
    const stamp = typeof at === "number" ? at : now();
    seq += 1;
    const eventId = newEventId(kind, stamp, payload);
    const name = `${String(seq).padStart(6, "0")}-${eventId}.json`;
    const event = { protocol: PROTOCOL, event_id: eventId, kind, at: stamp, payload };
    await writeAtomic(path.join(dirs.intake, name), event);
    return { eventId, file: name, event };
  }

  // -- 便捷封装：让宿主侧调用点读起来像业务语言 --------------------------- //

  /** Agent 自产笔记（唯一允许的知识来源之一）。 */
  const emitNote = ({ domain, statement, source = "agent_note", tags = [] }, at) =>
    emit("note", { domain, statement, source, tags }, at);

  /** Agent 自己的复述结果。passed 由宿主判定后传进来。 */
  const emitRestatement = ({ nodeId, text, passed }, at) =>
    emit("restatement", { node_id: nodeId, text, passed: Boolean(passed) }, at);

  /** 行为日志里的应用/迁移证据（判据 C 的唯一来源）。 */
  const emitTransfer = ({ nodeId, context }, at) =>
    emit("transfer", { node_id: nodeId, context }, at);

  /** 共同经历。initiated_by_agent 决定加权。 */
  const emitSharedSession = (
    { hobbyId, initiatedByAgent = true, emotionalWeight = 1.0 },
    at
  ) =>
    emit(
      "hobby.shared",
      {
        hobby_id: hobbyId,
        initiated_by_agent: Boolean(initiatedByAgent),
        emotional_weight: Number(emotionalWeight),
      },
      at
    );

  /**
   * 触发睡眠结算。
   *
   * answers 必须由宿主提供——只有宿主那边的 Agent 会说话。键是 node_id，
   * 值是这次它自己答出来的原话。核心只负责判定，不替它编答案。
   */
  const triggerSleep = (answers = {}, at) =>
    emit("sleep.trigger", { answers, verifier: "keyword" }, at);

  /** 读只读投影。没有就返回 null（还没跑过 project）。 */
  async function readProjection() {
    return readJsonIfExists(dirs.projection);
  }

  async function readStatus() {
    return readJsonIfExists(dirs.status);
  }

  /** 「最近在琢磨的事」的快捷取法。 */
  async function readMulling(limit = 5) {
    const projection = await readProjection();
    if (!projection || !Array.isArray(projection.mulling)) return [];
    return projection.mulling.slice(0, limit);
  }

  /** 轮询投影变化，内容变了才回调（没有 fs.watch 的跨平台噪音）。 */
  function watch(onProjection, intervalMs = 1000) {
    let last = null;
    watcher = setInterval(async () => {
      try {
        const projection = await readProjection();
        const stamp = projection ? projection.generated_at : null;
        if (stamp !== last) {
          last = stamp;
          if (projection) onProjection(projection);
        }
      } catch (err) {
        log.error("[cogniseed-bridge] 读投影失败:", err.message);
      }
    }, intervalMs);
    if (typeof watcher.unref === "function") watcher.unref();
    return () => close();
  }

  function close() {
    if (watcher) {
      clearInterval(watcher);
      watcher = null;
    }
  }

  return {
    dirs,
    init,
    emit,
    emitNote,
    emitRestatement,
    emitTransfer,
    emitSharedSession,
    triggerSleep,
    readProjection,
    readStatus,
    readMulling,
    watch,
    close,
  };
}

module.exports = { createBridge, PROTOCOL, KINDS };

// ------------------------------------------------------------------------- //
// 直接 `node plugin.js` 时跑一个演示：写两条事件，读投影
// ------------------------------------------------------------------------- //
if (require.main === module) {
  (async () => {
    const dir = process.argv[2] || "./tmp-bridge-js";
    const bridge = createBridge({ dataDir: dir });
    await bridge.init();
    console.log("data dir:", bridge.dirs.root);

    const a = await bridge.emitNote(
      { domain: "基础园艺", statement: "浇水要看土壤干湿而不是固定天数" },
      1800000000
    );
    const b = await bridge.emitSharedSession(
      { hobbyId: "基础园艺", initiatedByAgent: true, emotionalWeight: 1.2 },
      1800000000
    );
    console.log("emitted:", a.file, b.file);
    console.log("intake 待处理:", (await fs.readdir(bridge.dirs.intake)).length);

    const projection = await bridge.readProjection();
    console.log(
      "projection:",
      projection ? `${projection.mulling.length} 条在琢磨` : "还没有（先跑 bridge.py project）"
    );
    bridge.close();
  })().catch((err) => {
    console.error(err);
    process.exitCode = 1;
  });
}
