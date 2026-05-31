# localRAGcoder — Android APK Build (Chaquopy)
#
# Builds an Android APK embedding the Python engine via Chaquopy.
#
# Prerequisites:
#   Android SDK + NDK (installed by GitHub Actions runner)

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") version "16.0.0"
}

android {
    namespace = "ai.localragcoder.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "ai.localragcoder"
        minSdk = 26
        targetSdk = 34
        versionCode = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull() ?: 1
        versionName = System.getenv("GITHUB_REF_NAME")?.removePrefix("v") ?: "1.0.0"

        python {
            buildPython("/usr/bin/python3")
            pip {
                install("../../requirements.txt")
            }
        }

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.webkit:webkit:1.9.0")
}
