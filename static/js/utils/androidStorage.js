const DIRECTORY_FIELDS = [
  'cards_dir', 'world_info_dir', 'chats_dir', 'presets_dir', 'regex_dir', 'scripts_dir',
  'quick_replies_dir', 'beautify_dir', 'resources_dir', 'st_data_dir', 'tt_data_dir',
  'st_openai_preset_dir',
];

export async function authorizeAndroidDirectories(form, previous = {}) {
  if (typeof window === 'undefined' || typeof window.stmHost?.requestStorageAccess !== 'function') return;
  const paths = DIRECTORY_FIELDS.filter(key => form[key] !== previous[key])
    .map(key => form[key]).filter(value => typeof value === 'string' && value.trim());
  paths.push(...(form.allowed_abs_resource_roots || [])
    .filter(path => !(previous.allowed_abs_resource_roots || []).includes(path)));
  if (!paths.length) return;
  await new Promise((resolve, reject) => {
    const id = `storage-${Date.now()}`;
    const handler = event => {
      if (event.detail?.id !== id) return;
      window.removeEventListener('host:storage-result', handler);
      if (event.detail.success) resolve();
      else reject(new Error('目录授权已取消或目录不可读写，原配置已保留'));
    };
    window.addEventListener('host:storage-result', handler);
    try { window.stmHost.requestStorageAccess(id, JSON.stringify(paths)); }
    catch (error) { window.removeEventListener('host:storage-result', handler); reject(error); }
  });
}
