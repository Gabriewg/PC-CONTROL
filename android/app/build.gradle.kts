plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.gabriewg.poltergeist"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.gabriewg.poltergeist"
        minSdk = 24
        targetSdk = 34
        versionCode = 8
        versionName = "2.0.0"
    }

    signingConfigs {
        create("release") {
            // Chave fixa do projeto: a mesma nas builds locais e no CI, para o
            // APK novo instalar por cima do anterior sem desinstalar. E' a
            // chave de debug padrao do Android (sideload, nao Play Store).
            storeFile = file("poltergeist.jks")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("release")
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
