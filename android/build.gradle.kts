// 顶层构建脚本：只声明插件版本，具体配置在 app/build.gradle.kts。
//
// 版本说明（与仓库 docs/2026-10-16-android-apk-feasibility.md 的结论对应）：
// - Chaquopy 17.2.0：17.1.0 起显式启用 FTS5，这是本项目的硬性下限
//   （core/data/index_runtime_store.py 依赖 fts5，虽然 fast 表已改成普通表，
//   全文搜索的 full 表仍需要 FTS5）。
// - AGP 8.7.x：落在 Chaquopy 支持的 7.3–9.5 区间内。
// - Kotlin 2.0.x：AGP 8.7 的推荐组合。
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("com.chaquo.python") version "17.2.0" apply false
}
