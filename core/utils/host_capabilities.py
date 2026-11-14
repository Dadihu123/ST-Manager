"""宿主能力声明：把「这个平台能干什么」集中到一处。

历史上这些判断散落在各处的 ``platform.system()`` 分支里（例如
``core/api/v1/system.py`` 每个「打开系统文件管理器」入口都重复一遍
Windows / Darwin / else 三叉）。移动端接进来以后，else 分支既不是
Linux 也没有 ``xdg-open``，重复判断必然出错，因此统一在这里声明。

桌面与 Termux 的文件管理器和监听能力保留原行为；其余值按宿主声明。

.. note::
   下面部分常量在**当前**只有 Android 的代码里尚未被引用，它们是为 iOS 壳
   预留的（iOS 侧尚未开工，见 docs/2026-11-12-multi-target-release-addendum.md）。
   **不要因为「没有被引用」而删除**：它们定义了平台能力契约，删除后 iOS
   落地时会退回散落的 platform 判断，正是本模块要消除的问题。
"""

from core.config import is_android_platform, is_embedded_android, is_ios_platform


def is_mobile_platform() -> bool:
    """是否运行在移动端（iOS / Android）。"""
    return is_ios_platform() or is_embedded_android()


#: 能否把路径交给系统文件管理器（打开文件夹 / 在资源管理器中显示）。
#: 移动端没有桌面意义上的「文件管理器可执行文件」，且 iOS 上 subprocess 被禁用。
#: 使用方：``core/api/v1/system.py``。
CAN_OPEN_SYSTEM_FILE_MANAGER = not is_mobile_platform()

#: 能否启动子进程。PEP 730 规定 iOS 上 subprocess 直接抛异常。
#: iOS 预留：当前没有调用方（现有 subprocess 调用点都还没接移动端判断）。
CAN_SPAWN_SUBPROCESS = not is_ios_platform()

#: 能否用 watchdog 监听文件系统变化。
#: Android 的 /storage/emulated/0 是 FUSE，不投递 inotify；
#: iOS 上 watchdog 会降级为轮询且后台不运行。
#: 使用方：``core/services/scan_service.py``。
CAN_WATCH_FILESYSTEM = not is_mobile_platform()

#: 是否有「前台服务 + 常驻通知」这类可长期后台运行的机制。
#: Android 有 FOREGROUND_SERVICE；iOS 没有等价物。
#: iOS 预留：当前 Android 壳自己决定要不要起服务，还没走这个开关。
CAN_RUN_BACKGROUND_SERVICE = is_android_platform()

#: 是否需要 security-scoped bookmark 才能访问用户选定目录（仅 iOS）。
#: iOS 预留：iOS 壳落地后，文件访问层要按它决定是否申请 scope。
REQUIRES_SECURITY_SCOPED_DIRS = is_ios_platform()


def describe() -> dict:
    """当前平台的能力快照，供诊断日志与接口暴露使用。"""
    return {
        'is_mobile': is_mobile_platform(),
        'can_open_system_file_manager': CAN_OPEN_SYSTEM_FILE_MANAGER,
        'can_spawn_subprocess': CAN_SPAWN_SUBPROCESS,
        'can_watch_filesystem': CAN_WATCH_FILESYSTEM,
        'can_run_background_service': CAN_RUN_BACKGROUND_SERVICE,
        'requires_security_scoped_dirs': REQUIRES_SECURITY_SCOPED_DIRS,
    }
