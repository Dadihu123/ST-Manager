package com.stmanager.pro

import java.io.File

/** JSON 解析、路径规范化和启动授权都在同一个失败边界内。 */
class StorageAccessRequest(private val dataRoot: File) {
    fun start(
        readPaths: () -> List<String>,
        ready: (List<String>, Boolean) -> Unit,
        failed: (Exception) -> Unit,
    ) {
        try {
            val root = dataRoot.canonicalPath
            val paths = readPaths().map { raw ->
                require(raw.isNotBlank() && !raw.contains("://") && !raw.contains('\u0000')) {
                    "不支持的目录路径"
                }
                (if (File(raw).isAbsolute) File(raw) else File(dataRoot, raw)).canonicalPath
            }
            val external = paths.any { it != root && !it.startsWith(root + File.separator) }
            ready(paths, external)
        } catch (e: Exception) {
            failed(e)
        }
    }
}
