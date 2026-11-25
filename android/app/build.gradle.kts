plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.localcontrol"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.localcontrol"
        minSdk = 24
        targetSdk = 34
        versionCode = 7
        versionName = "1.3.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // assina com a chave de debug para poder instalar sem criar keystore
            signingConfig = signingConfigs.getByName("debug")
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
    // Leitor de QR Code (Camera2 + ZXing). O resto do app usa so APIs do Android.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    // O zxing-android-embedded 4.3.0 usa androidx.core mas nao a declara como
    // dependencia transitiva: sem isso o leitor de QR abre e cai na hora com
    // NoClassDefFoundError (androidx.core.content.ContextCompat).
    implementation("androidx.core:core:1.12.0")
}
