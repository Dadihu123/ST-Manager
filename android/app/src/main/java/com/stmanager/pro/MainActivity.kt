package com.stmanager.pro

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.Settings
import android.util.Base64
import android.util.Log
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject
import org.json.JSONArray
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import java.io.File
import java.net.URL
import java.net.HttpURLConnection
import java.util.ArrayDeque

/**
 * 单 Activity + WebView 外壳。
 *
 * 职责边界很重要：**这里只做「宿主能力」，不做业务**。
 * 业务全部在 APK 内嵌的 CPython 里跑 Flask（见 [BackendService]），
 * WebView 只是加载 http://127.0.0.1:<port>。
 *
 * WebView 必须补齐的四件事（缺一个就有一个功能瞎掉，见可行性文档 §4.4）：
 * 1. onShowFileChooser —— 29 处 <input type="file">
 * 2. DownloadListener  —— blob: 下载（导出 JSON/PNG/备份全靠它）
 * 3. onCreateWindow     —— target="_blank" 与 window.open
 * 4. 返回键             —— 先问 JS 视图栈，再考虑退出
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "StmMain"
    }

    private lateinit var webView: WebView
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private lateinit var fileChooserLauncher: ActivityResultLauncher<Intent>
    private var unsubscribeReady: (() -> Unit)? = null
    private var loadedPort = 0
    private var nativeBridgeAvailable = false
    private val popups = mutableSetOf<WebView>()
    private data class ExportRequest(
        val id: String,
        val bytes: ByteArray,
        val fileName: String,
        val mimeType: String,
    )
    private val documentExports = ArrayDeque<ExportRequest>()
    private var pendingDocumentExport: ExportRequest? = null
    private val downloadWriter = DownloadWriter()
    private val documentExportLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val request = pendingDocumentExport ?: return@registerForActivityResult
        val uri = result.data?.data
        if (result.resultCode != Activity.RESULT_OK || uri == null) {
            finishExport(request, false, "已取消保存")
            pendingDocumentExport = null
            startNextDocumentExport()
        } else {
            Thread {
                try {
                    downloadWriter.writeDocument(request.bytes, contentResolver.openOutputStream(uri, "w"))
                    finishExport(request, true)
                } catch (e: Exception) {
                    Log.w(TAG, "保存文件失败: ${request.fileName}", e)
                    finishExport(request, false)
                } finally {
                    runOnUiThread {
                        pendingDocumentExport = null
                        startNextDocumentExport()
                    }
                }
            }.apply { isDaemon = true }.start()
        }
    }
    private var pendingBackup: Pair<String, String>? = null
    private val backupDocumentLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val (job, kind) = pendingBackup ?: return@registerForActivityResult
        pendingBackup = null
        val uri = result.data?.data
        if (result.resultCode != Activity.RESULT_OK || uri == null) {
            reportBackup(job, false, "已取消选择文件或保存位置")
        } else {
            Thread {
                try {
                    val action = if (kind == "export") "download" else "upload"
                    val connection = URL(BackupTransfer.endpoint(if (loadedPort > 0) loadedPort else 17863, job, action))
                        .openConnection() as HttpURLConnection
                    try {
                        connection.instanceFollowRedirects = false
                        connection.connectTimeout = 30_000
                        connection.readTimeout = 120_000
                        if (kind == "export") {
                            check(connection.responseCode == 200) { "无法读取备份" }
                            val expected = connection.contentLengthLong
                            connection.inputStream.use { input ->
                                val output = contentResolver.openOutputStream(uri, "wt")
                                    ?: error("无法打开保存位置")
                                output.use { BackupTransfer.copy(input, it, expected) }
                            }
                            reportBackup(job, true, "已保存到：$uri")
                        } else {
                            connection.requestMethod = "PUT"
                            connection.doOutput = true
                            connection.setRequestProperty("Content-Type", "application/zip")
                            connection.setChunkedStreamingMode(64 * 1024)
                            val input = contentResolver.openInputStream(uri) ?: error("无法读取文档")
                            input.use { source ->
                                connection.outputStream.use { BackupTransfer.copy(source, it) }
                            }
                            check(connection.responseCode == 200) { "上传失败，请检查空间后重新选择" }
                        }
                    } finally { connection.disconnect() }
                } catch (e: Exception) {
                    Log.w(TAG, "备份文件传输失败", e)
                    if (kind == "export") {
                        try { android.provider.DocumentsContract.deleteDocument(contentResolver, uri) }
                        catch (_: Exception) { /* 提供者可能不支持删除；页面仍报告失败。 */ }
                    }
                    reportBackup(job, false, e.message ?: "文件传输失败")
                }
            }.apply { isDaemon = true }.start()
        }
    }

    private fun reportBackup(job: String, success: Boolean, message: String) {
        Thread {
            try {
                val connection = URL(BackupTransfer.endpoint(if (loadedPort > 0) loadedPort else 17863, job, "transfer"))
                    .openConnection() as HttpURLConnection
                try {
                    connection.instanceFollowRedirects = false
                    connection.connectTimeout = 15_000
                    connection.readTimeout = 15_000
                    connection.requestMethod = "POST"
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", "application/json")
                    connection.outputStream.use {
                        it.write(JSONObject().put("success", success).put("message", message).toString().toByteArray())
                    }
                    check(connection.responseCode == 200)
                } finally { connection.disconnect() }
            } catch (e: Exception) {
                Log.w(TAG, "无法确认备份传输结果", e)
                runOnUiThread { Toast.makeText(this, "传输结果未确认，请检查文件后重试", Toast.LENGTH_LONG).show() }
            }
        }.apply { isDaemon = true }.start()
    }

    private fun chooseBackupDocument(job: String, kind: String) {
        BackupTransfer.endpoint(if (loadedPort > 0) loadedPort else 17863, job, if (kind == "export") "download" else "upload")
        require(kind == "export" || kind == "import")
        if (pendingBackup != null) { reportBackup(job, false, "文件选择器正在使用中"); return }
        pendingBackup = job to kind
        try {
            backupDocumentLauncher.launch(Intent(
                if (kind == "export") Intent.ACTION_CREATE_DOCUMENT else Intent.ACTION_OPEN_DOCUMENT,
            ).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/zip"
                if (kind == "export") putExtra(Intent.EXTRA_TITLE, "ST-Manager-${System.currentTimeMillis()}.zip")
            })
        } catch (e: Exception) {
            pendingBackup = null
            reportBackup(job, false, e.message ?: "无法打开系统文件选择器")
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        pendingBackup?.let { (job, kind) ->
            outState.putString("backupJob", job)
            outState.putString("backupKind", kind)
        }
        super.onSaveInstanceState(outState)
    }

    private var pendingStorage: Pair<String, List<String>>? = null
    private val storagePermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { completeStorageRequest() }
    private val legacyStorageLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { completeStorageRequest() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        savedInstanceState?.getString("backupJob")?.let { job ->
            pendingBackup = job to (savedInstanceState.getString("backupKind") ?: "import")
        }

        fileChooserLauncher =
            registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
                val callback = fileChooserCallback ?: return@registerForActivityResult
                fileChooserCallback = null
                val uris: Array<Uri>? =
                    if (result.resultCode == Activity.RESULT_OK) {
                        val data = result.data
                        when {
                            data?.clipData != null -> {
                                val clip = data.clipData!!
                                Array(clip.itemCount) { idx -> clip.getItemAt(idx).uri }
                            }
                            data?.data != null -> arrayOf(data.data!!)
                            else -> null
                        }
                    } else {
                        null
                    }
                callback.onReceiveValue(uris)
            }

        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true          // localStorage：state.js / chatGrid.js 等依赖
                databaseEnabled = true
                allowFileAccess = false           // 全部走 Flask 静态路由，不需要 file://
                allowContentAccess = false
                mediaPlaybackRequiresUserGesture = false
                // 让 WebView 不要按「桌面站点」缩放页面。
                useWideViewPort = true
                loadWithOverviewMode = true
                cacheMode = WebSettings.LOAD_DEFAULT
                // window.open / target=_blank 需要它，配合下面 onCreateWindow。
                setSupportMultipleWindows(true)
                javaScriptCanOpenWindowsAutomatically = true
            }
            webViewClient = StmWebViewClient()
            webChromeClient = StmChromeClient()
            // 不使用向所有 iframe 注入的 JavascriptInterface。
            if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                WebViewCompat.addWebMessageListener(this, "stmNative", setOf("http://127.0.0.1:17863")) {
                    _, message, sourceOrigin, isMainFrame, _ ->
                    NativeBridgePolicy().dispatch(sourceOrigin.toString(), isMainFrame) {
                        dispatchHostMessage(message.data ?: "")
                    }
                }
                nativeBridgeAvailable = true
            }

            // === 2) 下载 ===
            // 导出 JSON / PNG / 备份走的是 blob: + <a download>，
            // WebView 默认不处理，必须自己接。
            setDownloadListener { url, _, contentDisposition, mimetype, _ ->
                handleDownload(url, contentDisposition, mimetype)
            }
        }
        setContentView(webView)

        setupBackHandling()

    }

    override fun onStart() {
        super.onStart()
        if (!nativeBridgeAvailable) {
            showErrorPage("请更新 Android System WebView", "当前 WebView 不支持安全的宿主消息通道")
            return
        }
        BackendService.start(this)
        unsubscribeReady?.invoke()
        unsubscribeReady = BackendService.whenReady { port ->
            if (isDestroyed || isFinishing) return@whenReady
            if (port > 0) {
                if (loadedPort != port) {
                    loadedPort = port
                    webView.loadUrl("http://127.0.0.1:$port/")
                }
            } else {
                loadedPort = 0
                showErrorPage("后端启动失败", "请用 adb logcat -s StmBackend python.stderr 查看日志")
            }
        }
    }

    override fun onStop() {
        unsubscribeReady?.invoke()
        unsubscribeReady = null
        // 不占用后台 dataSync 配额；Python 线程随进程存活，回前台幂等重连。
        BackendService.stop(this)
        super.onStop()
    }

    /**
     * 显示一个纯 HTML 的错误页。
     *
     * 为什么需要：黑屏是**最难排查**的故障形态 —— 用户看不到任何信息，
     * 只能靠 adb。把错误画在屏幕上，用户截图就能定位问题。
     */
    private fun showErrorPage(title: String, detail: String) {
        val html = """
            <!DOCTYPE html><html><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
              body{background:#111;color:#eee;font-family:sans-serif;padding:24px;line-height:1.6}
              h1{font-size:18px;color:#ff6b6b}
              pre{background:#222;padding:12px;border-radius:6px;white-space:pre-wrap;font-size:12px}
            </style></head><body>
            <h1>$title</h1>
            <pre>$detail</pre>
            </body></html>
        """.trimIndent()
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
    }

    // === 2) 下载：blob: 与普通 URL 两条路径 ===
    private fun handleDownload(url: String, contentDisposition: String?, mimetype: String?) {
        if (url.startsWith("blob:") || url.startsWith("data:")) {
            // blob:/data: 在 WebView 里不能用 DownloadManager 取，
            // 必须回到 JS 侧把内容读成 base64 再交回来。
            downloadViaJs(url, contentDisposition, mimetype)
        } else {
            downloadViaIntent(url, contentDisposition, mimetype)
        }
    }

    /**
     * blob:/data: 下载：在页面里用 FileReader 读成 base64，回传给 [saveBase64FileAsync]。
     * 这是 WebView 里唯一可靠的办法——blob: URL 只存在于渲染进程内。
     */
    private fun downloadViaJs(url: String, contentDisposition: String?, mimetype: String?) {
        val safeMime = JSONObject.quote(mimetype ?: "application/octet-stream")
        val suggested = guessFileName(url, contentDisposition)
        val js = """
            (function(){
              var xhr = new XMLHttpRequest();
              xhr.open('GET', ${JSONObject.quote(url)}, true);
              xhr.responseType = 'blob';
              xhr.onload = function(){
                var reader = new FileReader();
                reader.onloadend = function(){
                  var b64 = (reader.result || '').split(',')[1] || '';
                  window.stmHost && window.stmHost.saveBase64FileAsync('', b64, ${JSONObject.quote(suggested)}, $safeMime);
                };
                reader.readAsDataURL(xhr.response);
              };
              xhr.send();
            })();
        """.trimIndent()
        runOnUiThread { webView.evaluateJavascript(js, null) }
    }

    private fun downloadViaIntent(url: String, contentDisposition: String?, mimetype: String?) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            // 旧系统的 DownloadManager 写公共目录也要求 WRITE，改由用户选择导出位置。
            val cookie = CookieManager.getInstance().getCookie(url) ?: ""
            Thread {
                try {
                    val connection = URL(url).openConnection().apply {
                        connectTimeout = 30_000
                        readTimeout = 30_000
                        setRequestProperty("Cookie", cookie)
                    }
                    val bytes = connection.getInputStream().use { it.readBytes() }
                    enqueueDocumentExport(ExportRequest("", bytes, guessFileName(url, contentDisposition),
                        mimetype ?: "application/octet-stream"))
                } catch (e: Exception) {
                    Log.w(TAG, "下载失败: $url", e)
                    runOnUiThread { Toast.makeText(this, "下载失败", Toast.LENGTH_SHORT).show() }
                }
            }.apply { isDaemon = true }.start()
            return
        }
        try {
            val name = guessFileName(url, contentDisposition)
            // 普通 URL：交给系统下载器（带 Cookie，某些接口需要登录态）。
            val request = android.app.DownloadManager.Request(Uri.parse(url)).apply {
                setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                setNotificationVisibility(
                    android.app.DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED,
                )
                if (!mimetype.isNullOrEmpty()) setMimeType(mimetype)
            }
            val dm = getSystemService(DOWNLOAD_SERVICE) as android.app.DownloadManager
            dm.enqueue(request)
            Toast.makeText(this, "已开始下载：$name", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Log.w(TAG, "下载失败: $url", e)
            Toast.makeText(this, "下载失败", Toast.LENGTH_SHORT).show()
        }
    }

    private fun guessFileName(url: String, contentDisposition: String?): String {
        val fromUrl = URLUtil.guessFileName(url, contentDisposition, null)
        return if (fromUrl.isBlank() || fromUrl.startsWith("downloadfile")) {
            "stm-export-${System.currentTimeMillis()}"
        } else {
            fromUrl
        }
    }

    /**
     * Android 10+ 用 MediaStore；旧版用系统创建文档，无需授予公共目录权限。
     * 文件选择、写入和发布全部完成后才通知页面成功。
     */
    private fun saveBase64FileAsync(id: String, base64: String, fileName: String, mimeType: String) {
        Thread {
            val safeFileName = File(fileName.replace('\\', '/')).name.ifBlank { "stm-export" }
            var request = ExportRequest(id, byteArrayOf(), safeFileName, mimeType)
            try {
                request = request.copy(bytes = Base64.decode(base64, Base64.DEFAULT))
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                    enqueueDocumentExport(request)
                    return@Thread
                }
                val resolver = contentResolver
                downloadWriter.writePending(request.bytes, create = {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, safeFileName)
                        put(MediaStore.Downloads.MIME_TYPE, mimeType)
                        put(MediaStore.Downloads.IS_PENDING, 1)
                    }
                    resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                }, open = { uri -> resolver.openOutputStream(uri) }, publish = { uri ->
                    val values = ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }
                    resolver.update(uri, values, null, null)
                }, delete = { uri -> resolver.delete(uri, null, null) })
                finishExport(request, true)
            } catch (e: Exception) {
                Log.w(TAG, "保存文件失败: $safeFileName", e)
                finishExport(request, false)
            }
        }.apply { isDaemon = true }.start()
    }

    private fun enqueueDocumentExport(request: ExportRequest) {
        runOnUiThread {
            if (isDestroyed || isFinishing) return@runOnUiThread
            documentExports.addLast(request)
            startNextDocumentExport()
        }
    }

    private fun startNextDocumentExport() {
        if (isDestroyed || isFinishing || pendingDocumentExport != null || documentExports.isEmpty()) return
        val request = documentExports.removeFirst()
        pendingDocumentExport = request
        try {
            documentExportLauncher.launch(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = request.mimeType.ifBlank { "application/octet-stream" }
                putExtra(Intent.EXTRA_TITLE, request.fileName)
            })
        } catch (e: Exception) {
            Log.w(TAG, "打开保存位置失败", e)
            finishExport(request, false)
            pendingDocumentExport = null
            startNextDocumentExport()
        }
    }

    private fun finishExport(request: ExportRequest, success: Boolean, message: String = "保存导出文件失败") {
        runOnUiThread {
            if (isDestroyed || isFinishing) return@runOnUiThread
            val detail = JSONObject().put("id", request.id).put("success", success).put("message", message)
            webView.evaluateJavascript(
                "window.dispatchEvent(new CustomEvent('host:download-result', {detail:$detail}))", null,
            )
            // download listener 的兜底路径没有等待 JS Promise，由原生显示结果。
            if (request.id.isEmpty()) {
                Toast.makeText(this, if (success) "已保存：${request.fileName}" else message, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private inner class StmChromeClient : WebChromeClient() {
        override fun onShowFileChooser(
            webView: WebView?,
            filePathCallback: ValueCallback<Array<Uri>>?,
            fileChooserParams: FileChooserParams?,
        ): Boolean {
            fileChooserCallback?.onReceiveValue(null)
            fileChooserCallback = filePathCallback

            val intent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
            }
            return try {
                fileChooserLauncher.launch(intent)
                true
            } catch (e: Exception) {
                Log.w(TAG, "打开文件选择器失败", e)
                fileChooserCallback = null
                false
            }
        }

        // === 3) 新窗口：在当前 WebView 打开，避免点击无反应 ===
        override fun onCreateWindow(
            view: WebView?,
            isDialog: Boolean,
            isUserGesture: Boolean,
            resultMsg: android.os.Message?,
        ): Boolean {
            val transport = resultMsg?.obj as? WebView.WebViewTransport ?: return false
            val child = WebView(this@MainActivity)
            popups.add(child)
            fun release() {
                child.post { if (popups.remove(child)) child.destroy() }
            }
            child.webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val uri = request?.url ?: return true
                    if (uri.toString() == "about:blank") return false
                    openNavigation(uri)
                    release()
                    return true
                }
                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                    if (!url.isNullOrBlank() && url != "about:blank") {
                        openNavigation(Uri.parse(url))
                        release()
                    }
                }
            }
            child.webChromeClient = object : WebChromeClient() {
                override fun onCloseWindow(window: WebView?) { release() }
            }
            child.postDelayed({ if (popups.contains(child)) release() }, 10_000)
            transport.webView = child
            resultMsg.sendToTarget()
            return true
        }
    }

    private inner class StmWebViewClient : WebViewClient() {
        override fun onPageFinished(view: WebView?, url: String?) {
            super.onPageFinished(view, url)
            Log.i(TAG, "页面加载完成: $url")
        }

        override fun onReceivedError(
            view: WebView?,
            request: WebResourceRequest?,
            error: android.webkit.WebResourceError?,
        ) {
            super.onReceivedError(view, request, error)
            // 只关心主文档的失败；子资源 404 不该弹错误页。
            if (request?.isForMainFrame == true) {
                val desc = error?.description?.toString() ?: "unknown"
                Log.e(TAG, "主文档加载失败: $desc  url=${request.url}")
                showErrorPage(
                    "页面加载失败",
                    "无法加载 ${request.url}\n\n$desc\n\n" +
                        "可能原因：后端尚未就绪、或 SSE/静态资源路由异常。",
                )
            }
        }

        override fun shouldOverrideUrlLoading(
            view: WebView?,
            request: WebResourceRequest?,
        ): Boolean {
            val url = request?.url?.toString() ?: return false
            val uri = Uri.parse(url)
            if (isBackendUri(uri)) return false
            openNavigation(uri)
            return true
        }
    }

    // === 4) 返回键：先问 JS 视图栈 ===
    private fun setupBackHandling() {
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    // 问 JS：「这次返回你消费了吗？」
                    // viewStack.js 的 handleBack 会先关弹窗、再回默认工作区，
                    // 都不适用时返回 false（此时才真正退出）。
                    webView.evaluateJavascript("window.__stmHostBack ? window.__stmHostBack() : false") { result ->
                        val consumed = result?.trim() == "true"
                        if (!consumed && !webView.canGoBack()) {
                            isEnabled = false
                            onBackPressedDispatcher.onBackPressed()
                            isEnabled = true
                        } else if (!consumed) {
                            webView.goBack()
                        }
                    }
                }
            },
        )
    }

    // 兼容 Android 13+ 的预测性返回：不用额外 API，OnBackPressedCallback 已覆盖。

    private fun isBackendUri(uri: Uri): Boolean =
        uri.scheme == "http" && uri.host == "127.0.0.1" && uri.port == loadedPort

    private fun openNavigation(uri: Uri) {
        if (isBackendUri(uri)) { webView.loadUrl(uri.toString()); return }
        if (uri.scheme !in listOf("https", "http", "mailto")) return
        try { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
        catch (e: Exception) { Log.w(TAG, "无法打开外部链接", e) }
    }

    private fun checkStoragePaths(paths: List<String>): Boolean = try {
        paths.all { raw ->
            require(!raw.contains("://")) { "不支持文档 URI，请导入文件或使用真实目录路径" }
            val dir = (if (File(raw).isAbsolute) File(raw) else File(filesDir, raw)).canonicalFile
            check(dir.isDirectory || dir.mkdirs())
            check(dir.canRead())
            val probe = File.createTempFile(".stm-write-", ".tmp", dir)
            try { probe.writeText("probe"); check(probe.readText() == "probe") }
            finally { probe.delete() }
            true
        }
    } catch (e: Exception) { Log.w(TAG, "目录不可读写", e); false }

    private fun sendStorageResult(id: String, success: Boolean) {
        val payload = JSONObject().put("id", id).put("success", success)
        webView.evaluateJavascript(
            "window.dispatchEvent(new CustomEvent('host:storage-result',{detail:$payload}))", null,
        )
    }

    private fun completeStorageRequest() {
        val (id, paths) = pendingStorage ?: return
        pendingStorage = null
        val success = checkStoragePaths(paths)
        sendStorageResult(id, success)
    }

    private fun requestStorageAccess(id: String, pathsJson: String) {
        if (pendingStorage != null) { sendStorageResult(id, false); return }
        StorageAccessRequest(filesDir).start(readPaths = {
            val array = JSONArray(pathsJson)
            (0 until array.length()).map { array.getString(it) }
        }, ready = { paths, external ->
            pendingStorage = id to paths
            if (external && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
                storagePermissionLauncher.launch(Intent(
                    Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName"),
                ))
            } else if (external && Build.VERSION.SDK_INT < Build.VERSION_CODES.R &&
                androidx.core.content.ContextCompat.checkSelfPermission(this@MainActivity,
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                legacyStorageLauncher.launch(arrayOf(android.Manifest.permission.READ_EXTERNAL_STORAGE,
                    android.Manifest.permission.WRITE_EXTERNAL_STORAGE))
            } else completeStorageRequest()
        }, failed = { e ->
            Log.w(TAG, "无法申请目录权限", e)
            pendingStorage = null
            sendStorageResult(id, false)
        })
    }

    private fun dispatchHostMessage(raw: String) {
        try {
            val message = JSONObject(raw)
            when (message.getString("action")) {
                "backup-document" -> chooseBackupDocument(message.getString("job"), message.getString("kind"))
                "storage" -> requestStorageAccess(message.getString("id"), message.getString("pathsJson"))
                "download" -> saveBase64FileAsync(message.getString("id"), message.getString("base64"),
                    message.getString("fileName"), message.getString("mimeType"))
                // 注意：不要在这里加「打开文件夹」。
                // 壳层无法凭一个路径让外部文件管理器进入应用私有目录。
                // 系统目录入口按能力隐藏；应用内浏览与导出复用业务文件接口。
                // 早先这里用 Settings.ACTION_INTERNAL_STORAGE_SETTINGS 跳系统存储设置页，
                // 但 Web 侧从来没有发过这个消息，属于死代码，已删除。
            }
        } catch (e: Exception) {
            Log.w(TAG, "宿主消息无效", e)
        }
    }

    override fun onDestroy() {
        unsubscribeReady?.invoke()
        unsubscribeReady = null
        popups.toList().forEach { it.destroy() }
        popups.clear()
        fileChooserCallback?.onReceiveValue(null)
        fileChooserCallback = null
        documentExports.clear()
        pendingDocumentExport = null
        super.onDestroy()
        try {
            webView.destroy()
        } catch (e: Exception) {
            Log.w(TAG, "销毁 WebView 失败", e)
        }
    }
}
