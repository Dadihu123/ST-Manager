package com.stmanager.pro

import java.io.ByteArrayOutputStream
import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class DownloadWriterTest {
    private val bytes = "中文 export".toByteArray(Charsets.UTF_8)
    private val writer = DownloadWriter()

    private class Sink(private val failWrite: Boolean = false, private val failClose: Boolean = false) :
        ByteArrayOutputStream() {
        var closed = false
        override fun write(data: ByteArray, offset: Int, length: Int) {
            if (failWrite) throw IOException("write failed")
            super.write(data, offset, length)
        }
        override fun close() {
            closed = true
            if (failClose) throw IOException("close failed")
            super.close()
        }
    }

    @Test fun publishesOnlyAfterCompleteWriteAndClose() {
        val sink = Sink()
        var published = false
        writer.writePending(bytes, create = { "created-uri" }, open = { uri ->
            assertEquals("created-uri", uri)
            sink
        }, publish = { uri ->
            assertEquals("created-uri", uri)
            assertTrue(sink.closed)
            assertArrayEquals(bytes, sink.toByteArray())
            published = true
            1
        }, delete = { fail("Successful export must not be deleted"); 0 })
        assertTrue(published)
    }

    @Test fun nullOutputStreamDeletesCreatedRecord() {
        var deleted: String? = null
        assertThrows(IOException::class.java) {
            writer.writePending(bytes, create = { "created-uri" }, open = { null },
                publish = { fail("Partial file must not be published"); 0 },
                delete = { uri -> deleted = uri; 1 })
        }
        assertEquals("created-uri", deleted)
    }

    @Test fun writeFailureClosesStreamAndDeletesCreatedRecord() {
        val sink = Sink(failWrite = true)
        var deleted = false
        val failure = assertThrows(IOException::class.java) {
            writer.writePending(bytes, create = { "created-uri" }, open = { sink },
                publish = { fail("Partial file must not be published"); 0 },
                delete = { deleted = true; 1 })
        }
        assertEquals("write failed", failure.message)
        assertTrue(sink.closed)
        assertTrue(deleted)
    }

    @Test fun closeFailureDeletesCreatedRecord() {
        var deleted = false
        assertThrows(IOException::class.java) {
            writer.writePending(bytes, create = { "created-uri" }, open = { Sink(failClose = true) },
                publish = { fail("Unclosed file must not be published"); 0 },
                delete = { deleted = true; 1 })
        }
        assertTrue(deleted)
    }

    @Test fun zeroUpdatedRowsDeletesUnpublishedRecord() {
        var deleted = false
        assertThrows(IOException::class.java) {
            writer.writePending(bytes, create = { "created-uri" }, open = { Sink() },
                publish = { 0 }, delete = { deleted = true; 1 })
        }
        assertTrue(deleted)
    }

    @Test fun publishExceptionDeletesRecordAndPreservesCleanupFailure() {
        val failure = assertThrows(IOException::class.java) {
            writer.writePending(bytes, create = { "created-uri" }, open = { Sink() },
                publish = { throw IOException("publish failed") },
                delete = { throw IOException("delete failed") })
        }
        assertEquals("publish failed", failure.message)
        assertEquals("delete failed", failure.suppressed.single().message)
    }

    @Test fun failedInsertDoesNotOpenOrDeleteOtherRecords() {
        assertThrows(IOException::class.java) {
            writer.writePending<String>(bytes, create = { null },
                open = { fail("No record was created"); null }, publish = { 0 },
                delete = { fail("No record was created"); 0 })
        }
    }

    @Test fun selectedDocumentReceivesExactBytesAndIsClosed() {
        val sink = Sink()
        writer.writeDocument(bytes, sink)
        assertArrayEquals(bytes, sink.toByteArray())
        assertTrue(sink.closed)
        assertThrows(IOException::class.java) { writer.writeDocument(bytes, null) }
    }
}
