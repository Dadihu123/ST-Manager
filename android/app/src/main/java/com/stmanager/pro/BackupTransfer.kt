package com.stmanager.pro

import java.io.InputStream
import java.io.OutputStream

/** 固定环回端点和有界缓冲；桥不接收任意 URL 或私有文件路径。 */
object BackupTransfer {
    const val MAX_BYTES = 100L * 1024 * 1024 * 1024

    fun endpoint(port: Int, job: String, action: String): String {
        require(port in 1..65535)
        require(job.matches(Regex("[0-9a-f]{32}")))
        require(action in setOf("upload", "download", "transfer"))
        return "http://127.0.0.1:$port/api/migration/jobs/$job/$action"
    }

    fun copy(input: InputStream, output: OutputStream, expected: Long = -1): Long {
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            total += count
            require(total <= MAX_BYTES) { "备份超过 100 GiB 限制" }
            output.write(buffer, 0, count)
        }
        check(expected < 0 || total == expected) { "传输中断，文件长度不符" }
        output.flush()
        return total
    }
}
