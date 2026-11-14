package com.stmanager.pro

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/**
 * 可见 Activity 的前台服务。离开页面即释放 dataSync 服务，避免消耗后台配额。
 * Python 后端在进程内幂等启动；进程被系统回收后，下次打开重新初始化。
 * make_server 持有固定 loopback 端口，绑定成功后才发布可取消的就绪通知。
 */
class BackendService : Service() {

    companion object {
        private const val TAG = "StmBackend"
        private const val CHANNEL_ID = "stm_backend"
        private const val NOTIFICATION_ID = 1001
        private val startupLock = Any()

        // 注册、结算与取消在同一把锁下；回调在主线程重新核验订阅。
        private val readyLock = Any()
        private var readyPort: Int? = null
        private var nextSubscription = 0
        private val listeners = mutableMapOf<Int, (Int) -> Unit>()
        private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

        private fun deliver(id: Int, port: Int) {
            mainHandler.post {
                val listener = synchronized(readyLock) { listeners.remove(id) }
                listener?.invoke(port)
            }
        }

        private fun settle(port: Int) {
            val ids = synchronized(readyLock) {
                readyPort = port
                listeners.keys.toList()
            }
            ids.forEach { deliver(it, port) }
        }

        fun whenReady(listener: (Int) -> Unit): () -> Unit {
            val id: Int
            val result: Int?
            synchronized(readyLock) {
                id = ++nextSubscription
                listeners[id] = listener
                result = readyPort
            }
            if (result != null) deliver(id, result)
            return { synchronized(readyLock) { listeners.remove(id) }; Unit }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, BackendService::class.java))
        }

        fun start(context: Context) {
            val intent = Intent(context, BackendService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }

    @Volatile
    private var serverThread: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification())
        // 幂等：重复 start 不重复起线程。
        if (serverThread != null) return START_NOT_STICKY

        serverThread = Thread({ runBackend() }, "stm-backend").apply {
            isDaemon = true
            start()
        }
        return START_NOT_STICKY
    }

    @Volatile private var destroyed = false

    private fun runBackend() = synchronized(startupLock) {
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
            val internalDir = extractAssetsToFiles()
            // 固定 origin，保持 WebView localStorage 身份；绑定失败直接报错，绝不探活其它进程。
            val serverPort = Python.getInstance().getModule("android_shell.boot")
                .callAttr("start_server", 17863, internalDir.absolutePath, filesDir.absolutePath).toInt()
            if (!destroyed) {
                Log.i(TAG, "后端就绪: http://127.0.0.1:$serverPort")
                settle(serverPort)
            }
        } catch (e: Throwable) {
            Log.e(TAG, "后端未就绪", e)
            if (!destroyed) settle(0)
        }
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        Log.w(TAG, "前台服务达到系统时间限制，结束服务")
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        destroyed = true
        synchronized(readyLock) { readyPort = null }
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    /** 内容摘要决定缓存身份；失败的 staging 不会覆盖上一份完整资源。 */
    private fun extractAssetsToFiles(): File {
        val stamp = assets.open("shell-assets.sha256").bufferedReader().use { it.readText().trim() }
        require(Regex("[a-f0-9]{64}").matches(stamp)) { "资源摘要无效" }
        val target = File(filesDir, ".shell-resources-$stamp")
        val stampFile = File(target, ".stamp")
        if (stampFile.isFile && stampFile.readText().trim() == stamp && validResources(target)) return target
        val staging = File(filesDir, ".shell-resources-staging")
        check(!staging.exists() || staging.deleteRecursively()) { "无法清理资源暂存目录" }
        check(staging.mkdirs()) { "无法创建资源暂存目录" }
        try {
            for (root in listOf("static", "templates")) copyAssetTree(assets, root, staging)
            check(validResources(staging)) { "入口资源不完整" }
            File(staging, ".stamp").writeText(stamp)
            check(!target.exists() || target.deleteRecursively()) { "无法替换资源缓存" }
            check(staging.renameTo(target)) { "无法发布资源缓存" }
        } catch (e: Exception) {
            staging.deleteRecursively()
            throw e
        }
        // 清理旧内容版本，只删除私有缓存目录。
        filesDir.listFiles()?.filter { it.isDirectory && it.name.startsWith(".shell-resources-") && it != target }
            ?.forEach { it.deleteRecursively() }
        return target
    }

    private fun validResources(root: File): Boolean =
        File(root, "templates/index.html").isFile && File(root, "static/js/app.js").isFile

    private fun copyAssetTree(manager: android.content.res.AssetManager, path: String, target: File) {
        val children = manager.list(path) ?: error("无法列出 assets/$path")
        if (children.isEmpty()) {
            val outFile = File(target, path)
            check(outFile.parentFile!!.isDirectory || outFile.parentFile!!.mkdirs())
            manager.open(path).use { input -> outFile.outputStream().use { output -> input.copyTo(output) } }
        } else {
            for (child in children) copyAssetTree(manager, "$path/$child", target)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "后台服务",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "维持 ST Manager 的本地服务运行"
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("ST Manager Pro")
            .setContentText("本地服务运行中")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .build()
    }
}
