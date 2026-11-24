@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------- JDK 17
if not defined JAVA_HOME (
    for /d %%D in ("C:\Program Files\Eclipse Adoptium\jdk-17*") do set "JAVA_HOME=%%D"
)
if not defined JAVA_HOME (
    echo JAVA_HOME nao definido e nenhum JDK 17 encontrado em C:\Program Files\Eclipse Adoptium.
    echo Instale com: winget install EclipseAdoptium.Temurin.17.JDK
    echo ou defina JAVA_HOME antes de rodar este script.
    pause
    exit /b 1
)

rem ---------------------------------------------------------------- Android SDK
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\AndroidSdk"
if not defined ANDROID_SDK_ROOT set "ANDROID_SDK_ROOT=%ANDROID_HOME%"

rem O local.properties aponta o SDK para o Gradle e fica fora do Git.
if not exist "local.properties" (
    echo sdk.dir=!ANDROID_HOME:\=/!> local.properties
)

rem ---------------------------------------------------------------- Gradle
rem Prefere o wrapper do projeto (versao fixa em gradle/wrapper/gradle-wrapper.properties).
set "GRADLE="
if exist "gradlew.bat" set "GRADLE=gradlew.bat"
if not defined GRADLE if exist "%ANDROID_HOME%\tools\gradle-8.7\bin\gradle.bat" set "GRADLE=%ANDROID_HOME%\tools\gradle-8.7\bin\gradle.bat"
if not defined GRADLE (
    where gradle >nul 2>nul && set "GRADLE=gradle"
)
if not defined GRADLE (
    echo Gradle nao encontrado. Instale o Android Studio ou coloque o Gradle 8.7+ no PATH.
    pause
    exit /b 1
)

call "%GRADLE%" assembleDebug --console=plain %*
if errorlevel 1 (
    echo.
    echo Falha na compilacao.
    pause
    exit /b 1
)

echo.
echo APK gerado em:
echo   %~dp0app\build\outputs\apk\debug\app-debug.apk
echo.
echo Para instalar no celular conectado: instalar-apk.bat
pause
