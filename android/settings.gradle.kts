pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        google()
        mavenCentral()
        // Chaquopy 的运行时依赖来自它自己的 Maven 仓库。
        maven { url = uri("https://chaquo.com/maven") }
    }
}

rootProject.name = "ST Manager Pro"
include(":app")
