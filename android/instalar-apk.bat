@echo off
setlocal
cd /d "%~dp0"

set "APK=%~dp0app\build\outputs\apk\debug\app-debug.apk"
if not exist "%APK%" (
    echo APK nao encontrado. Rode build-apk.bat primeiro.
    pause
    exit /b 1
)

adb devices
echo.
echo Instalando %APK% ...
adb install -r "%APK%"
if errorlevel 1 (
    echo.
    echo Falha ao instalar. Verifique a depuracao USB e a autorizacao do celular.
    pause
    exit /b 1
)

echo.
echo Instalado. Abrindo o app...
adb shell monkey -p com.localcontrol -c android.intent.category.LAUNCHER 1 >nul 2>&1
pause
