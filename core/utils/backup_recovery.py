"""启动早期恢复事务（仅标准库，必须在服务和插件加载前运行）。"""
import hashlib
import json
import os
import re
import stat


def durable_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.new'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _file_hash(path):
    result = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _restore_tree(path):
    """启动前也能使用的严格枚举；含空目录，拒绝链接、特殊文件及读取失败。"""
    def check(candidate):
        info = os.lstat(candidate)
        if stat.S_ISLNK(info.st_mode) or getattr(os.path, 'isjunction', lambda _: False)(candidate):
            raise ValueError('待启用目录含符号链接或目录联接')
        return info

    if not stat.S_ISDIR(check(path).st_mode):
        raise ValueError('待启用根不是目录')
    files, directories = {}, []
    def inaccessible(error):
        raise error
    for directory, dirs, names in os.walk(path, onerror=inaccessible):
        for name in sorted(dirs + names):
            candidate = os.path.join(directory, name)
            relative = os.path.relpath(candidate, path).replace('\\', '/')
            info = check(candidate)
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
            elif stat.S_ISREG(info.st_mode):
                checksum = _file_hash(candidate)
                after = os.stat(candidate)
                if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('建立校验清单期间文件变化: ' + relative)
                files[relative] = {'size': info.st_size, 'sha256': checksum}
            else:
                raise ValueError('待启用数据含特殊文件: ' + relative)
    return {'files': files, 'directories': sorted(directories)}


def seal_restore(base, job, moves):
    """记录路径转换后的最终内容；摘要与待启动事务一起持久化。"""
    if not re.fullmatch(r'[0-9a-f]{32}', job):
        raise ValueError('无效恢复任务')
    prefix = 'data/migration/' + job
    roots = [prefix + '/restore', prefix + '/library']
    os.makedirs(os.path.join(base, roots[1]), exist_ok=True)
    value = {'trees': {root: _restore_tree(os.path.join(base, root)) for root in roots},
             'moves': [{key: item[key] for key in ('source', 'target', 'old')} for item in moves]}
    relative = prefix + '/activation.json'
    path = os.path.join(base, relative)
    durable_json(path, value)
    if os.path.getsize(path) > 64 * 1024 ** 2:
        raise ValueError('待启用校验清单超过 64 MiB，请减少单次恢复内容')
    return {'seal': relative, 'seal_sha256': _file_hash(path)}


def _verify_seal(base, plan):
    job = plan.get('job', '')
    if not isinstance(job, str) or not re.fullmatch(r'[0-9a-f]{32}', job):
        raise ValueError('缺少恢复任务及最终校验清单，请重新选择备份')
    prefix = 'data/migration/' + job
    if plan.get('seal') != prefix + '/activation.json':
        raise ValueError('缺少待启用校验清单，请重新选择备份')
    path = os.path.join(base, plan['seal'])
    if os.path.islink(path) or getattr(os.path, 'isjunction', lambda _: False)(path):
        raise ValueError('待启用校验清单包含链接')
    if os.path.getsize(path) > 64 * 1024 ** 2 or _file_hash(path) != plan.get('seal_sha256'):
        raise ValueError('待启用校验清单已变化')
    with open(path, encoding='utf-8') as handle:
        expected = json.load(handle)
    roots = [prefix + '/restore', prefix + '/library']
    if (not isinstance(expected, dict) or set(expected) != {'trees', 'moves'} or
            set(expected['trees']) != set(roots) or expected['moves'] != [
                {key: item[key] for key in ('source', 'target', 'old')} for item in plan['moves']]):
        raise ValueError('待启用校验范围无效')
    for root in roots:
        if _restore_tree(os.path.join(base, root)) != expected['trees'][root]:
            raise ValueError('待启用数据已变化，请重新选择备份并预览: ' + root)
    if _file_hash(path) != plan['seal_sha256']:
        raise ValueError('启动复核期间校验清单发生变化')


def _load_pending(base):
    root = os.path.join(base, 'data', 'migration')
    journal = os.path.join(root, 'pending.json')
    if not os.path.exists(journal):
        return
    with open(journal, encoding='utf-8') as handle:
        plan = json.load(handle)
    # 日志也是输入：绝不允许越出数据根；目标来自服务端固定映射。
    allowed = {'config.json', 'data/system/db', 'data/assets', 'data/library/wallpapers', 'data/library/beautify',
               'data/system/automation', 'data/system/backups', 'data/plugins'}
    for item in plan['moves']:
        if item['target'] not in allowed:
            raise ValueError('非法恢复目标')
        for key in ('source', 'old'):
            if not isinstance(item[key], str) or '\\' in item[key] or '..' in item[key].split('/'):
                raise ValueError('非法恢复暂存路径')
            path = os.path.abspath(os.path.join(base, item[key]))
            if os.path.commonpath([path, os.path.abspath(root)]) != os.path.abspath(root):
                raise ValueError('非法恢复暂存路径')
            current = path
            while current != os.path.abspath(base):
                if os.path.islink(current) or getattr(os.path, 'isjunction', lambda _: False)(current):
                    raise ValueError('恢复路径包含符号链接或目录联接')
                current = os.path.dirname(current)

    return root, journal, plan


def rollback_pending(base, error=''):
    """回滚包括启动验证失败在内的未确认恢复；日志保留到反向切换全部成功。"""
    loaded = _load_pending(base)
    if loaded is None:
        return False
    root, journal, plan = loaded
    if plan['state'] == 'pending':
        return False
    plan.update(state='rolling_back', error=str(error))
    durable_json(journal, plan)
    for item in reversed(plan['moves']):
        target, source, old = [os.path.join(base, item[k]) for k in ('target', 'source', 'old')]
        if os.path.exists(old):
            if os.path.exists(target):
                os.makedirs(os.path.dirname(source), exist_ok=True)
                os.replace(target, source)
            os.replace(old, target)
        elif item.get('started') and not item['existed'] and os.path.exists(target) and not os.path.exists(source):
            os.replace(target, source)
    plan['state'] = 'rolled_back'
    durable_json(os.path.join(root, 'last-restore.json'), plan)
    os.remove(journal)
    return True


def confirm_pending(base):
    """仅在配置、数据库和缓存都成功加载后确认；中断前不会丢掉保护事务。"""
    loaded = _load_pending(base)
    if loaded is None:
        return
    root, journal, plan = loaded
    if plan['state'] != 'awaiting_startup':
        raise ValueError('恢复尚未通过启动验证')
    plan['state'] = 'complete'
    durable_json(journal, plan)
    durable_json(os.path.join(root, 'last-restore.json'), plan)
    os.remove(journal)


def awaiting_startup(base):
    loaded = _load_pending(base)
    return loaded is not None and loaded[2]['state'] == 'awaiting_startup'


def activate_pending(base):
    """早期切换后等待启动确认；切换或初始化中断均在下次启动回滚。"""
    loaded = _load_pending(base)
    if loaded is None:
        return
    root, journal, plan = loaded
    if plan['state'] == 'complete':
        durable_json(os.path.join(root, 'last-restore.json'), plan)
        os.remove(journal)
        return

    if plan['state'] in ('applying', 'awaiting_startup', 'rolling_back'):
        rollback_pending(base, '恢复或启动验证被中断')
        return
    try:
        _verify_seal(base, plan)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # 此时尚未移动任何目录，旧库无需反向切换即可继续启动。
        plan.update(state='rolled_back', error='启动前校验失败，当前资源库未改动，请重新选择备份并预览: ' + str(exc))
        durable_json(os.path.join(root, 'last-restore.json'), plan)
        os.remove(journal)
        return
    plan['state'] = 'applying'
    durable_json(journal, plan)
    try:
        for item in plan['moves']:
            target, source, old = [os.path.join(base, item[k]) for k in ('target', 'source', 'old')]
            item['existed'] = os.path.exists(target)
            item['started'] = True
            durable_json(journal, plan)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.makedirs(os.path.dirname(old), exist_ok=True)
            if item['existed']:
                os.replace(target, old)
            os.replace(source, target)
        plan['state'] = 'awaiting_startup'
        durable_json(journal, plan)
    except Exception as exc:
        rollback_pending(base, exc)
        raise
