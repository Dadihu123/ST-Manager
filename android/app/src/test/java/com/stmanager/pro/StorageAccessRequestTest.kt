package com.stmanager.pro

import java.io.File
import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class StorageAccessRequestTest {
    private val root = File(System.getProperty("java.io.tmpdir"), "stm-private")

    @Test fun illegalPathFailsWithoutStartingAuthorizationAndAllowsRetry() {
        val request = StorageAccessRequest(root)
        var failures = 0
        request.start({ listOf("bad\u0000path") }, { _, _ -> fail("Invalid path reached permission launcher") },
            { failures++ })
        assertEquals(1, failures)
        var ready = false
        request.start({ listOf("cards") }, { paths, external ->
            assertFalse(external)
            assertEquals(File(root, "cards").canonicalPath, paths.single())
            ready = true
        }, { fail(it.message) })
        assertTrue(ready)
    }

    @Test fun parsingAndCanonicalRootFailuresReturnFailure() {
        var failures = 0
        StorageAccessRequest(root).start({ throw IOException("invalid JSON") },
            { _, _ -> fail("Parsing failed") }, { failures++ })
        StorageAccessRequest(File("bad\u0000root")).start({ listOf("cards") },
            { _, _ -> fail("Canonical root failed") }, { failures++ })
        assertEquals(2, failures)
    }

    @Test fun permissionLauncherFailureReturnsFailure() {
        var failed = false
        StorageAccessRequest(root).start({ listOf(root.parentFile!!.absolutePath) }, { _, external ->
            assertTrue(external)
            throw IllegalStateException("cannot launch settings")
        }, { failed = true })
        assertTrue(failed)
    }
}
