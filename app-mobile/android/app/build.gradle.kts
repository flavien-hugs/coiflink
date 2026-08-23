import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Signature stable de l'APK (#178-signature-borne, ADR-0044) : `android/key.properties`
// est absent chez tout contributeur ordinaire (gitignoré, jamais committé) — dans ce
// cas, aucun changement de comportement, Gradle garde sa clé de debug implicite
// auto-générée. En CI (et pour quiconque a provisionné ce fichier localement), la
// config `debug` est signée avec une clé **stable** plutôt que régénérée à chaque
// run : sans ça, chaque nouvel APK a une signature différente et Android refuse la
// mise à jour en place (désinstallation forcée, qui efface le credential borne
// activé et l'imprimante sélectionnée, cf. ADR-0044).
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
val hasUploadKeystore = keystorePropertiesFile.exists()
if (hasUploadKeystore) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "com.incubtek.coiflink"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.incubtek.coiflink"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasUploadKeystore) {
            getByName("debug") {
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
