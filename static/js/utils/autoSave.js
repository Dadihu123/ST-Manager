/**
 * static/js/utils/autoSave.js
 * 自动保存核心逻辑封装
 */

import { smartAutoSnapshot } from "../api/system.js";

export function createAutoSaver(context) {
  /**
   * @param {Function} getData - 获取当前编辑器数据的函数 (用于生成 Hash/JSON 比对)
   * @param {Function} getPayload - 获取发送给后端 API 的 Payload 对象的函数
   * @param {Function} onSave - (可选) 保存成功后的回调 (如显示 Toast)
   */
  return {
    timer: null,
    originalJson: null, // 基准快照

    // 初始化基准 (打开编辑器或手动保存后调用)
    initBaseline(data) {
      this.originalJson = JSON.stringify(data);
    },

    // 启动自动保存
    start(getData, getPayload, onTick = null) {
      const settings = Alpine.store("global").settingsForm;

      // 1. 检查开关
      if (!settings.auto_save_enabled) return;

      // 2. 清理旧定时器
      this.stop();

      // 3. 获取间隔 (限制在 1-60 分钟)
      let interval = parseInt(settings.auto_save_interval) || 3;
      if (interval < 1) interval = 1;
      if (interval > 60) interval = 60;

      console.log(`[AutoSave] Timer started (${interval} min)`);

      // 4. 启动定时器
      this.timer = setInterval(
        async () => {
          const currentData = getData();
          const currentJson = JSON.stringify(currentData);

          // 比对：如果无变化，跳过
          if (currentJson === this.originalJson) {
            return;
          }

          console.log("[AutoSave] Change detected, creating snapshot...");

          // 获取 Payload
          const payload = getPayload();
          if (typeof onTick === "function") {
            try {
              await onTick(currentData, currentJson);
              this.originalJson = currentJson;
            } catch (e) {
              console.error("[AutoSave] Custom Tick Error:", e);
            }
            return;
          }

          if (!payload) return;

          try {
            const res = await smartAutoSnapshot(payload);

            if (res.success) {
              // 更新基准，防止重复保存
              this.originalJson = currentJson;

              // 显示提示
              if (res.status === "created") {
                Alpine.store("global").showToast("自动快照已生成", 2000, "snapshot");
              } else if (res.status === "skipped") {
                console.log("[AutoSave] Snapshot skipped (duplicate content)");
              }
            } else {
              console.error("[AutoSave] Failed:", res.msg);
            }
          } catch (e) {
            console.error("[AutoSave] Network Error:", e);
          }
        },
        interval * 60 * 1000,
      );
    },

    // 停止自动保存
    stop() {
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
        console.log("[AutoSave] Timer stopped");
      }
    },
  };
}
