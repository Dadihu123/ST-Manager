package com.stmanager.pro

import java.io.IOException
import java.io.OutputStream

/** 写完并关闭流后才发布下载；任一步失败都回收本次创建的 pending 记录。 */
class DownloadWriter {
    fun writeDocument(bytes: ByteArray, output: OutputStream?) {
        (output ?: throw IOException("无法打开文件输出流")).use { it.write(bytes) }
    }

    fun <T : Any> writePending(
        bytes: ByteArray,
        create: () -> T?,
        open: (T) -> OutputStream?,
        publish: (T) -> Int,
        delete: (T) -> Int,
    ) {
        val target = create() ?: throw IOException("无法创建下载记录")
        try {
            writeDocument(bytes, open(target))
            if (publish(target) <= 0) throw IOException("无法发布下载文件")
        } catch (failure: Exception) {
            try {
                if (delete(target) <= 0) throw IOException("无法清理未完成的下载记录")
            } catch (cleanup: Exception) {
                failure.addSuppressed(cleanup)
            }
            throw failure
        }
    }
}
