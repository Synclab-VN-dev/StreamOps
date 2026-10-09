plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.synclab.d4planner.bridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.synclab.d4planner.bridge"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-poc"
        testInstrumentationRunner = "android.test.InstrumentationTestRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
