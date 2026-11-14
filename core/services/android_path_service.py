"""Android 设置保存前验证实际目录访问，不把失败的路径写进配置。"""

import os
import tempfile

from core.config import BASE_DIR, RUNTIME_DIR_DEFAULTS, is_embedded_android, load_config


def validate_changed_directories(config):
    if not is_embedded_android():
        return
    previous = load_config()
    fields = set(RUNTIME_DIR_DEFAULTS) | {'st_data_dir', 'tt_data_dir', 'st_openai_preset_dir'}
    paths = [config[key] for key in fields if config.get(key) and config.get(key) != previous.get(key)]
    paths.extend(path for path in config.get('allowed_abs_resource_roots', [])
                 if path not in previous.get('allowed_abs_resource_roots', []))
    for path in paths:
        if not isinstance(path, str) or '://' in path:
            raise ValueError('请使用真实目录路径；文档 URI 需要先导入私有目录')
        resolved = os.path.abspath(os.path.join(BASE_DIR, path))
        try:
            os.makedirs(resolved, exist_ok=True)
            os.listdir(resolved)
            with tempfile.TemporaryFile(dir=resolved) as probe:
                probe.write(b'stm')
                probe.seek(0)
                if probe.read() != b'stm':
                    raise OSError('目录写入校验失败')
        except OSError as exc:
            raise ValueError(f'目录不可读写，原配置已保留: {path}') from exc
