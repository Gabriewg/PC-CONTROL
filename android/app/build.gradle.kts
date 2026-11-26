import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Chave de assinatura: nunca no repositorio. O CI usa os GitHub Secrets; para
// builds locais de release, aponte POLTERGEIST_KEYSTORE_PROPERTIES para o
// keystore.properties (com storeFile, storePassword, keyAlias e keyPassword).
val propsArquivo = System.getenv("POLTERGEIST_KEYSTORE_PROPERTIES")
val props = propsArquivo?.takeIf { file(it).exists() }?.let { caminho ->
    val p = Properties()
    file(caminho).inputStream().use { p.load(it) }
    p
}

fun chave(nome: String, env: String): String? =
    System.getenv(env) ?: props?.getProperty(nome)

val baseChave = propsArquivo?.let { File(it).parentFile }
val arquivoChave = chave("storeFile", "POLTERGEIST_KEYSTORE")?.let { valor ->
    val f = File(valor)
    if (f.isAbsolute) f else baseChave?.resolve(valor) ?: file(valor)
}

android {
    namespace = "io.github.gabriewg.poltergeist"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.gabriewg.poltergeist"
        minSdk = 29
        targetSdk = 34
        versionCode = 9
        versionName = "2.0.1"
    }

    // A chave de release fica FORA do repositorio. No CI ela vem dos GitHub
    // Secrets (o workflow grava o .jks e exporta POLTERGEIST_KEYSTORE...);
    // localmente, aponte POLTERGEIST_KEYSTORE_PROPERTIES para o
    // keystore.properties que acompanha a chave.
    signingConfigs {
        if (arquivoChave != null && arquivoChave.exists()) {
            create("release") {
                storeFile = arquivoChave
                storePassword = chave("storePassword", "POLTERGEIST_STORE_PASSWORD")
                keyAlias = chave("keyAlias", "POLTERGEIST_KEY_ALIAS") ?: "poltergeist"
                keyPassword = chave("keyPassword", "POLTERGEIST_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val assinatura = signingConfigs.findByName("release")
            if (assinatura == null &&
                gradle.startParameter.taskNames.any { it.contains("Release", ignoreCase = true) }) {
                logger.warn(
                    "Chave de release ausente: defina POLTERGEIST_KEYSTORE ou " +
                        "POLTERGEIST_KEYSTORE_PROPERTIES. Sem ela o APK sai assinado " +
                        "com a chave de debug local e nao serve para publicar."
                )
            }
            signingConfig = assinatura ?: signingConfigs.getByName("debug")
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
