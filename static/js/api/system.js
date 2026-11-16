import { downloadFileFromApi } from '../utils/download.js';

/**
 * static/js/api/system.js
 * 系统、文件、标签与备份 API
 */

// 获取服务器状态
export async function getServerStatus() {
  const res = await fetch("/api/status");
  return res.json();
}

// 获取设置
export async function getSettings() {
  const res = await fetch("/api/get_settings");
  return res.json();
}

export async function evaluateSettingsPathSafety(config) {
  const res = await fetch('/api/settings_path_safety', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  });
  return res.json();
}

// 保存设置
export async function saveSettings(config, options = {}) {
  const res = await fetch('/api/save_settings', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      config,
      confirm_risky_paths: !!options.confirm_risky_paths,
    }),
  });
  return res.json();
}

// 执行通用系统指令
export async function performSystemAction(action, data = {}) {
  const res = await fetch("/api/system_action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...data }),
  });
  return res.json();
}

// 触发立即扫描
export async function triggerScan() {
  const res = await fetch("/api/scan_now", { method: "POST" });
  return res.json();
}

export async function getIndexStatus() {
  const res = await fetch("/api/index/status");
  return res.json();
}

export async function requestIndexRebuild(payload = {}) {
  const res = await fetch("/api/index/rebuild", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// === 回收站 ===

export async function openTrash() {
  const res = await fetch("/api/trash/open", { method: "POST" });
  return res.json();
}

export async function emptyTrash() {
  const res = await fetch("/api/trash/empty", { method: "POST" });
  return res.json();
}

// === 文件夹操作 ===

export async function createFolder(payload) {
  // payload: { name, parent }
  const res = await fetch("/api/create_folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function renameFolder(payload) {
  // payload: { old_path, new_name }
  const res = await fetch("/api/rename_folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function deleteFolder(payload) {
  // payload: { folder_path }
  const res = await fetch("/api/delete_folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function moveFolder(payload) {
  // payload: { source_path, target_parent_path, merge_if_exists }
  const res = await fetch("/api/move_folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// === 标签操作 ===

export async function batchUpdateTags(payload) {
  // payload: { card_ids, add:[], remove:[] }
  const res = await fetch("/api/batch_tags", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function deleteTags(payload) {
  // payload: { tags: [] }
  const res = await fetch("/api/delete_tags", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function getTagOrder() {
  const res = await fetch("/api/tag_order");
  return res.json();
}

export async function saveTagOrder(payload) {
  const res = await fetch("/api/tag_order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function getTagTaxonomy() {
  const res = await fetch("/api/tag_taxonomy");
  return res.json();
}

export async function saveTagTaxonomy(payload) {
  const res = await fetch("/api/tag_taxonomy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function getTagManagementPrefs() {
  const res = await fetch("/api/tag_management_prefs");
  return res.json();
}

export async function saveTagManagementPrefs(payload) {
  const res = await fetch("/api/tag_management_prefs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// === 备份与快照 ===

export async function listBackups(payload) {
  // payload: { id, type, file_path }
  const res = await fetch("/api/list_backups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function restoreBackup(payload) {
  // payload: { backup_path, target_id, type, target_file_path }
  const res = await fetch("/api/restore_backup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function createSnapshot(payload) {
  // payload: { id, type, file_path, label, content, compact }
  const res = await fetch("/api/create_snapshot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function cleanupInitBackups(payload) {
  // payload: { id, type, file_path, keep_latest }
  const res = await fetch("/api/cleanup_init_backups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function smartAutoSnapshot(payload) {
  // payload: { id, type, content, file_path }
  const res = await fetch("/api/smart_auto_snapshot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function exportUserDbBackup({ download = false } = {}) {
  if (download) {
    const fileName = await downloadFileFromApi({
      url: '/api/user-db-backup/export?download=1',
      defaultFilename: 'user_db_backup.json',
    });
    return { success: true, file_name: fileName };
  }
  const res = await fetch("/api/user-db-backup/export", {
    method: "POST",
  });
  return res.json();
}

export async function importUserDbBackup(formData) {
  const res = await fetch("/api/user-db-backup/import", {
    method: "POST",
    body: formData,
  });
  return res.json();
}

// 读取文件内容 (用于 Diff)
export async function readFileContent(payload) {
  // payload: { path }
  const res = await fetch("/api/read_file_content", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// 后端清洗卡片数据 (用于 Diff)
export async function normalizeCardData(payload) {
  // payload: rawContent
  const res = await fetch("/api/normalize_card_data", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// 打开系统路径
export async function openPath(payload) {
  // payload: { path, is_file, relative_to_base }
  const res = await fetch("/api/open_path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}


export async function migrationRequest(path, options = {}) {
  const response = await fetch('/api/migration' + path, {
    ...options, headers: {'Content-Type': 'application/json', ...options.headers},
  });
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(result.msg || '备份操作失败');
  return result;
}

export async function uploadMigrationFile(id, file) {
  const response = await fetch(`/api/migration/jobs/${id}/upload`, {
    method: 'PUT', headers: {'Content-Type': 'application/zip'}, body: file,
  });
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(result.msg || '上传失败');
  return result;
}
