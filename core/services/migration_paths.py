"""备份路径字段的编码；资源 ID、普通文本及未知扩展字段始终原样保存。"""
import copy
import ntpath
import posixpath


PRESERVED_UI_NAMESPACES = frozenset({
    '_plugins_v1', '_tag_taxonomy_v1', '_tag_management_prefs_v1', '_tag_order_v1',
    '_isolated_categories_v1', '_entry_layout_v1',
})


class MigrationPaths:
    def __init__(self, base, roots, files=(), *, directories=(), exporting=False, casefold=False):
        self.base = str(base).replace('\\', '/').rstrip('/')
        self.roots = {k: str(v).replace('\\', '/').rstrip('/') for k, v in roots.items()}
        self.exporting = exporting
        self.casefold = casefold
        self.files = {}
        entries = [(slot, relative) for slot, relative, *_ in files]
        entries.extend(directory.split('/', 1) for directory in directories)
        for slot, relative in entries:
            while True:
                path = self.roots[slot] + ('/' + relative if relative else '')
                previous = self.files.get(self._key(path))
                if previous is None or self._priority(slot) < self._priority(previous[0]):
                    self.files[self._key(path)] = (slot, relative)
                if not relative:
                    break
                relative = posixpath.dirname(relative)

    def _key(self, path):
        return path.casefold() if self.casefold else path

    def _priority(self, slot):
        return -len(self.roots[slot]), slot

    def path(self, value, *, relative=False, source_base=None):
        """只处理完整路径值。relative 表示模块约定的应用根相对路径。"""
        if not isinstance(value, str) or not value:
            return value
        path = value.replace('\\', '/')
        if self.exporting:
            if not path.startswith('/') and not ntpath.splitdrive(path)[0]:
                if not relative:
                    return value
                path = posixpath.join(source_base or self.base, path)
            path = posixpath.normpath(path)
            actual = self.files.get(self._key(path))
            if actual:
                return 'stm://' + actual[0] + '/' + actual[1]
            for slot, root in sorted(self.roots.items(), key=lambda item: self._priority(item[0])):
                key, prefix = self._key(path), self._key(root)
                if key == prefix or key.startswith(prefix + '/'):
                    return 'stm://' + slot + path[len(root):]
            if self._key(path) == self._key(self.base) or self._key(path).startswith(self._key(self.base) + '/'):
                return 'stm://base' + path[len(self.base):]
            return value
        if not path.startswith('stm://'):
            return value
        slot, _, suffix = path[6:].partition('/')
        if slot != 'base' and slot not in self.roots:
            raise ValueError('未知路径逻辑目录: ' + slot)
        if any(part in ('.', '..') for part in suffix.split('/')):
            raise ValueError('非法逻辑路径')
        target = (self.base if slot == 'base' else self.roots[slot]) + ('/' + suffix if suffix else '')
        return posixpath.relpath(target, self.base) if relative else target

    def _assets(self, value, source_base=None):
        if isinstance(value, list):
            return [self._assets(item, source_base) for item in value]
        if isinstance(value, dict):
            return {key: self.path(item, relative=True, source_base=source_base)
                    if key in ('file', 'theme_file', 'avatar_file') else self._assets(item, source_base)
                    for key, item in value.items()}
        return value

    def _bindings(self, value):
        if isinstance(value, list):
            return [self._bindings(item) for item in value]
        if isinstance(value, dict):
            return {key: self.binding(item) if key == 'resource_folder' else self._bindings(item)
                    for key, item in value.items()}
        return value

    def binding(self, value):
        """相对绑定属于资源根；统一通过实际文件/目录清单校正分隔符及大小写。"""
        if self.exporting and isinstance(value, str) and value.strip():
            path = value.strip().replace('\\', '/')
            if not path.startswith('/') and not ntpath.splitdrive(path)[0]:
                value = posixpath.normpath(posixpath.join(self.roots['resources_dir'], path))
            else:
                value = path
        return self.path(value)

    def ui(self, value):
        result = copy.deepcopy(value)
        for key, item in list(result.items()):
            if key in ('_beautify_library_v1', '_shared_wallpaper_library_v1'):
                source_base = self.base
                if self.exporting and key == '_beautify_library_v1':
                    from core.services.beautify_service import beautify_project_root
                    source_base = beautify_project_root(self.roots['beautify_dir'])
                result[key] = self._assets(item, source_base)
            elif key == '_worldinfo_notes_v1' and isinstance(item, dict):
                notes = {}
                for note_key, note in item.items():
                    source, sep, path = note_key.partition('::')
                    if sep and source in ('global', 'resource'):
                        path = self.path(path, relative=True) if self.exporting else self.path(path)
                        if not self.exporting:
                            from core.data.ui_store import build_worldinfo_note_key
                            note_key = build_worldinfo_note_key(source, file_path=path)
                        else:
                            note_key = source + '::' + path
                    if note_key in notes:
                        raise ValueError('世界书备注定位键冲突')
                    notes[note_key] = note
                result[key] = notes
            elif key == '_resource_item_categories_v1' and isinstance(item, dict):
                for mode in ('worldinfo', 'presets'):
                    if isinstance(item.get(mode), dict):
                        converted = {}
                        for path, category in item[mode].items():
                            target = self.path(path, relative=True) if self.exporting else self.path(path)
                            if not self.exporting:
                                from core.data.ui_store import _normalize_resource_item_category_path
                                target = _normalize_resource_item_category_path(target, worldinfo=(mode == 'worldinfo'))
                            converted[target] = category
                        result[key][mode] = converted
            elif key not in PRESERVED_UI_NAMESPACES:
                # _a.png、_folder 等仍是合法卡片/目录键；不根据前缀猜测内部命名空间。
                result[key] = self._bindings(item)
        return result

    def settings(self, value):
        result = copy.deepcopy(value)
        # 背景图通常是 /assets/... HTTP 路由，不能按文件系统绝对路径处理。
        if isinstance(result.get('bg_url'), str) and not result['bg_url'].startswith('/assets/'):
            result['bg_url'] = self.path(result['bg_url'], relative=True)
        return result
