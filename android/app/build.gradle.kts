plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Sideload signing key for the release APK. Kept next to the module so a
// headless build works without any IDE setup. Password is intentionally not a
// secret — this key only exists to make the APK installable on a device.
val keystoreFile = rootProject.file("phonemic-release.keystore")
val keystoreProps = mapOf(
    "storeFile" to keystoreFile.absolutePath,
    "storePassword" to "phonemic",
    "keyAlias" to "phonemic",
    "keyPassword" to "phonemic",
)

android {
    namespace = "com.phonemic.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.phonemic.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 7
        versionName = "0.3.1"
    }

    signingConfigs {
        if (keystoreFile.exists()) {
            create("release") {
                storeFile = file(keystoreProps["storeFile"] as String)
                storePassword = keystoreProps["storePassword"] as String
                keyAlias = keystoreProps["keyAlias"] as String
                keyPassword = keystoreProps["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystoreFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")

    // WebSocket to the PC agent
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // QR scanning during pairing
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")

    // Optional: end-to-end payload encryption (mirrors the PC agent's SecretBox scheme)
    // implementation("com.goterl:lazysodium-android:5.1.0")
    // implementation("net.java.dev.jna:jna:5.14.0@aar")
}
