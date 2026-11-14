package com.stmanager.pro

import org.junit.Assert.*
import org.junit.Test

class NativeBridgePolicyTest {
    private val policy = NativeBridgePolicy()

    @Test fun trustedMainFrameCanDispatch() {
        var calls = 0
        assertTrue(policy.dispatch("http://127.0.0.1:17863", true) { calls++ })
        assertEquals(1, calls)
    }

    @Test fun sandboxAndSameOriginChildCannotDispatchAnyNativeAction() {
        for (origin in listOf("null", "", "http://127.0.0.1:17863")) {
            for (action in listOf("storage", "download", "openFolder")) {
                var calls = 0
                assertFalse(action, policy.dispatch(origin, false) { calls++ })
                assertEquals(0, calls)
            }
        }
    }

    @Test fun untrustedMainFrameCannotDispatch() {
        for (origin in listOf("https://example.com", "http://localhost:17863", "http://127.0.0.1:5000",
            "https://127.0.0.1:17863", "http://127.0.0.1:17863.evil.test", "null", "file:///",
            "http://evil@127.0.0.1:17863", "http://127.0.0.1:17863/?spoof", "malformed origin")) {
            assertFalse(origin, policy.dispatch(origin, true) { fail("Untrusted origin dispatched") })
        }
    }
}
