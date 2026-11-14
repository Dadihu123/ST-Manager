package com.stmanager.pro

import java.net.URI

/** Origin 白名单仍需主框架校验；同源 iframe 也不能获得宿主能力。 */
class NativeBridgePolicy {
    fun dispatch(sourceOrigin: String, isMainFrame: Boolean, action: () -> Unit): Boolean {
        if (!isMainFrame) return false
        val origin = try { URI(sourceOrigin) } catch (_: Exception) { return false }
        if (origin.scheme != "http" || origin.host != "127.0.0.1" || origin.port != 17863 ||
            origin.rawUserInfo != null || origin.rawQuery != null || origin.rawFragment != null ||
            origin.rawPath !in listOf("", "/")) return false
        action()
        return true
    }
}
