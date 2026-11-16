package com.stmanager.pro

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.IOException
import java.io.OutputStream

class BackupTransferTest {
    @Test fun copiesLargeStreamWithBoundedReads() {
        var remaining = 12 * 1024 * 1024
        val input = object : InputStream() {
            override fun read(): Int = error("bulk reads only")
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                assertTrue(length <= 64 * 1024)
                if (remaining == 0) return -1
                val count = minOf(length, remaining)
                buffer.fill(42, offset, offset + count)
                remaining -= count
                return count
            }
        }
        var written = 0L
        val output = object : OutputStream() {
            override fun write(value: Int) { written++ }
            override fun write(buffer: ByteArray, offset: Int, length: Int) { written += length }
        }
        assertEquals(12L * 1024 * 1024, BackupTransfer.copy(input, output, 12L * 1024 * 1024))
        assertEquals(12L * 1024 * 1024, written)
    }

    @Test fun rejectsTruncatedAndFailedOutput() {
        assertThrows(IllegalStateException::class.java) {
            BackupTransfer.copy(ByteArrayInputStream(byteArrayOf(1)), ByteArrayOutputStream(), 2)
        }
        assertThrows(IOException::class.java) {
            BackupTransfer.copy(ByteArrayInputStream(byteArrayOf(1)), object : OutputStream() {
                override fun write(value: Int) { throw IOException("no space") }
            })
        }
    }

    @Test fun allowsOnlyPinnedJobEndpoints() {
        val job = "a".repeat(32)
        assertEquals("http://127.0.0.1:17863/api/migration/jobs/$job/download",
            BackupTransfer.endpoint(17863, job, "download"))
        for (id in listOf("../config.json", "http://evil", "a".repeat(33))) {
            assertThrows(IllegalArgumentException::class.java) { BackupTransfer.endpoint(17863, id, "download") }
        }
        assertThrows(IllegalArgumentException::class.java) { BackupTransfer.endpoint(17863, job, "../../config") }
    }
}
