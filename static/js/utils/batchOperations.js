import { executeRules, getAutomationTargets } from "../api/automation.js";
import { checkCardSourceUpdate, getSourceUpdateTargets } from "../api/card.js";

function getGlobalStore() {
  return window.Alpine && typeof window.Alpine.store === "function"
    ? window.Alpine.store("global")
    : null;
}

function cardLabel(cardId) {
  const value = String(cardId || "");
  return value.split("/").pop() || value;
}

function createErrorResult(cardId, error) {
  return {
    success: false,
    status: "error",
    card_id: cardId,
    error: error?.message || String(error || "执行失败"),
  };
}

async function resolveTargetIds(resolveTargets, payload) {
  const response = await resolveTargets(payload);
  if (!response?.success) {
    throw new Error(response?.msg || "无法解析批量处理目标");
  }

  const ids = Array.isArray(response.card_ids) ? response.card_ids : [];
  return [...new Set(ids.map((id) => String(id || "").trim()).filter(Boolean))];
}

async function runSequentialBatch({
  title,
  targetPayload,
  resolveTargets,
  executeOne,
  classify,
  onItem,
}) {
  const store = getGlobalStore();
  const cardIds = await resolveTargetIds(resolveTargets, targetPayload);
  if (cardIds.length === 0) {
    store?.showToast("没有找到需要处理的角色卡", 2400);
    return {
      success: true,
      selected: 0,
      completed: 0,
      items: [],
    };
  }

  store?.startBatchProgress(title, cardIds.length);
  const items = [];
  const summary = {
    success: true,
    selected: cardIds.length,
    completed: 0,
    processed: 0,
    checked: 0,
    updated: 0,
    unchanged: 0,
    skipped: 0,
    failed: 0,
    moves: 0,
    tag_changes: 0,
    cancelled: false,
    items,
  };

  for (const cardId of cardIds) {
    if (store?.batchProgress?.cancelRequested) {
      summary.cancelled = true;
      break;
    }

    store?.updateBatchProgress({
      currentCardId: cardId,
      message: `${cardLabel(cardId)}：处理中...`,
    });

    let response;
    try {
      response = await executeOne(cardId);
    } catch (error) {
      response = createErrorResult(cardId, error);
    }

    const item = classify(cardId, response);
    items.push(item);
    summary.completed += 1;
    summary.processed += Number(item.processed || 0);
    summary.checked += Number(item.checked || 0);
    summary.updated += Number(item.updated || 0);
    summary.unchanged += Number(item.unchanged || 0);
    summary.skipped += Number(item.skipped || 0);
    summary.failed += Number(item.failed || 0);
    summary.moves += Number(item.moves || 0);
    summary.tag_changes += Number(item.tag_changes || 0);

    if (typeof onItem === "function") {
      onItem(cardId, response, item);
    }

    store?.updateBatchProgress({
      current: summary.completed,
      currentCardId: cardId,
      message: `${cardLabel(cardId)}：已完成`,
    });
  }

  summary.status = summary.cancelled ? "cancelled" : "completed";
  store?.finishBatchProgress(summary);
  return summary;
}

export function isBatchOperationRunning() {
  return getGlobalStore()?.batchProgress?.status === "running";
}

export async function runAutomationBatch({ rulesetId, targetPayload, title = "批量执行自动化" }) {
  return runSequentialBatch({
    title,
    targetPayload,
    resolveTargets: getAutomationTargets,
    executeOne: (cardId) => executeRules({ ruleset_id: rulesetId, card_ids: [cardId] }),
    classify: (cardId, response) => {
      if (!response?.success) {
        return { card_id: cardId, failed: 1, message: response?.msg || response?.error || "执行失败" };
      }

      return {
        card_id: cardId,
        processed: Number(response.processed || 0),
        skipped: Number(response.skipped || 0),
        moves: Number(response.summary?.moves || 0),
        tag_changes: Number(response.summary?.tag_changes || 0),
        message: response.skipped ? "已处理（部分跳过）" : "已完成",
      };
    },
  });
}

export async function runSourceUpdateBatch({ targetPayload, title = "批量检查来源更新", onItem }) {
  return runSequentialBatch({
    title,
    targetPayload,
    resolveTargets: getSourceUpdateTargets,
    executeOne: (cardId) => checkCardSourceUpdate(cardId),
    classify: (cardId, response) => {
      if (!response?.success) {
        return {
          card_id: cardId,
          failed: 1,
          message: response?.error || response?.msg || "检查来源失败",
        };
      }

      if (!response.supported) {
        return {
          card_id: cardId,
          skipped: 1,
          message: response.message || "不支持的来源，已跳过",
        };
      }

      return {
        card_id: cardId,
        checked: 1,
        updated: response.changed ? 1 : 0,
        unchanged: response.changed ? 0 : 1,
        message: response.message || "检查完成",
      };
    },
    onItem: (cardId, response, item) => {
      window.dispatchEvent(
        new CustomEvent("source-update-result", {
          detail: { card_id: cardId, result: response, item },
        }),
      );
      if (typeof onItem === "function") {
        onItem(cardId, response, item);
      }
    },
  });
}
