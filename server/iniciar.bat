@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------- ambiente
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python...
    python -m venv .venv || goto :erro
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
)

echo Verificando dependencias...
".venv\Scripts\python.exe" -c "import mss, numpy, cv2, cryptography" 2>nul
if errorlevel 1 (
    echo Instalando dependencias ^(mss, numpy, opencv, pillow, cryptography^)...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet || goto :erro
)

rem dxcam e opcional: se instalar, a captura usa a GPU (bem mais rapida).
rem Se falhar, o servidor cai sozinho para GDI e continua funcionando.
".venv\Scripts\python.exe" -c "import dxcam" 2>nul
if errorlevel 1 (
    echo Instalando dxcam ^(captura via GPU, opcional^)...
    ".venv\Scripts\python.exe" -m pip install dxcam --quiet 2>nul
    if errorlevel 1 echo Aviso: dxcam indisponivel, usando captura GDI.
)

rem ---------------------------------------------------------------- PIN
rem O PIN fica salvo em pin.txt (nunca no Git) e nunca e enviado pela rede.
if not exist "pin.txt" (
    echo Primeiro uso: defina o PIN de acesso ^(4+ caracteres com TLS^).
    ".venv\Scripts\python.exe" server.py --set-pin || goto :erro
)

".venv\Scripts\python.exe" server.py %*
goto :fim

:erro
echo.
echo Falha ao preparar o servidor. Verifique se o Python 3.10+ esta no PATH.
pause

:fim
endlocal
