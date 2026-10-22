"""主程序版本号与插件 API 契约版本的唯一来源。

插件 manifest 的 `min_app_version` 与 `api_version` 都要和这里比对：
- `APP_VERSION`：主程序对外的语义化版本，插件可据此要求最低主程序版本。
- `PLUGIN_API_VERSION`：当前主程序实现的插件 API 契约版本（v3，见 ADR-0012）。

契约规则本体在 `core/plugins/contract.py`（纯标准库、无副作用）；本模块**不 import
contract**，避免循环导入。`tests/test_plugin_contract_values.py` 断言两处版本一致（S1）。
"""

APP_VERSION = '1.0.0'

# 主程序当前实现的插件 API 契约版本；插件 api_version 不在支持集合内时严格拒绝加载。
PLUGIN_API_VERSION = 3

# v3 一次成型、删除旧版本兼容（ADR-0012）：支持集合只有当前版本。
SUPPORTED_PLUGIN_API_VERSIONS = (PLUGIN_API_VERSION,)
