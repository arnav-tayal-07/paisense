import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// The API key and base URL come from local.properties, which is git-ignored.
// Hard-coding the key would publish it: this repo is public, and anything
// compiled into the APK is extractable anyway - but there is a real
// difference between "on GitHub" and "requires decompiling an APK you own".
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.paisense.app"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.paisense.app"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Surfaced to Kotlin as BuildConfig.API_BASE / BuildConfig.API_KEY.
        // Empty defaults rather than a crash at build time, so someone can
        // clone the repo and build it before they have a key.
        buildConfigField(
            "String",
            "API_BASE",
            "\"${localProps.getProperty("PAISENSE_API_BASE") ?: "https://paisense.onrender.com"}\""
        )
        buildConfigField(
            "String",
            "API_KEY",
            "\"${localProps.getProperty("PAISENSE_API_KEY") ?: ""}\""
        )
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.androidx.work.runtime.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}