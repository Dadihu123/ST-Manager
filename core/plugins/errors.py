"""插件系统异常类型。

每个异常都带一个 `code`，与设计文档 10.4 的「统一错误码」表一一对应，
便于路由层直接映射为 HTTP 状态码与响应体。

manifest 校验失败走**两层**错误信息（设计文档 2.2「分层错误信息」）：
机器可读的 `code` / `field`，给作者看的 `hint`，以及给普通用户看的 `user_msg`。
"""



class PluginError(Exception):
    """插件系统异常基类。"""

    code = 'plugin_error'
    http_status = 500

    def __init__(
        self,
        message: str = '',
        *,
        detail: str = '',
        code: str = '',
        field: str = '',
        hint: str = '',
        user_msg: str = '',
    ):
        super().__init__(message or self.__class__.__doc__ or 'plugin error')
        self.message = message
        self.detail = detail
        # 结构化字段（可选）：留空时不进入响应体，保持既有错误载荷形状不变。
        self.field = field
        self.hint = hint
        self.user_msg = user_msg
        if code:
            self.code = code

    def __str__(self) -> str:
        text = self.message or super().__str__()
        if self.hint:
            return f'{text}（{self.hint}）'
        return text

    def to_dict(self) -> dict:
        payload = {'success': False, 'msg': self.message, 'error': self.code}
        if self.detail:
            payload['detail'] = self.detail
        if self.field:
            payload['field'] = self.field
        if self.hint:
            payload['hint'] = self.hint
        if self.user_msg:
            payload['user_msg'] = self.user_msg
        return payload

    def as_detail(self) -> dict:
        """返回可持久化到 `ui_data` 的完整错误结构（供注册表记录 load_error）。"""
        return {
            'code': self.code,
            'field': self.field,
            'msg': self.message,
            'hint': self.hint,
            'user_msg': self.user_msg,
        }


class PluginManifestError(PluginError):
    """manifest 缺失或不符合规范。"""

    code = 'plugin_manifest_invalid'
    http_status = 400


class PluginApiVersionError(PluginError):
    """插件 api_version 与主程序不兼容（D8：严格拒绝加载）。"""

    code = 'api_version_unsupported'
    http_status = 409


class PluginLoadError(PluginError):
    """插件代码加载或注册阶段失败。"""

    code = 'plugin_load_failed'
    http_status = 500


class PluginCliError(PluginError):
    """插件 CLI 子命令相关错误（N2）：命令不存在或参数非法。"""

    code = 'plugin_cli_error'
    http_status = 400


class PluginNotFoundError(PluginError):
    """插件不存在。"""

    code = 'plugin_not_found'
    http_status = 404


class PluginDisabledError(PluginError):
    """插件已被禁用。"""

    code = 'plugin_disabled'
    http_status = 409


class PluginSecretError(PluginError):
    """密钥读写失败。"""

    code = 'plugin_secret_error'
    http_status = 500


class PluginJobError(PluginError):
    """作业参数或状态非法。"""

    code = 'plugin_job_error'
    http_status = 400


class PluginJobNotFoundError(PluginError):
    """作业不存在。"""

    code = 'job_not_found'
    http_status = 404


class PluginJobStateError(PluginError):
    """作业当前状态不允许该操作。"""

    code = 'job_not_running'
    http_status = 409


class PluginJobDuplicateError(PluginError):
    """同插件已有运行中的作业。"""

    code = 'job_already_running'
    http_status = 409


class PluginSseLimitError(PluginError):
    """SSE 连接数超限。"""

    code = 'sse_limit_reached'
    http_status = 429


class PluginCatalogError(PluginError):
    """官方目录不可达或格式非法。"""

    code = 'catalog_offline'
    http_status = 502


class PluginInstallError(PluginError):
    """安装流程失败。"""

    code = 'plugin_install_failed'
    http_status = 400


class PluginArchiveUnsafeError(PluginInstallError):
    """归档未通过安全检查（zip-slip / 炸弹 / 链接逃逸）。"""

    code = 'install_unsafe_archive'
    http_status = 400


class PluginAssetsError(PluginError):
    """插件静态资源路径非法。"""

    code = 'plugin_asset_invalid'
    http_status = 404
