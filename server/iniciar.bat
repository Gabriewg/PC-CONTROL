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
".venv\Scripts\python.exe" -c "import mss, numpy, cv2" 2>nul
if errorlevel 1 (
    echo Instalando dependencias ^(mss, numpy, opencv, pillow^)...
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
rem O PIN e local e NUNCA deve ser commitado. Escolha uma das formas:
rem   iniciar.bat --pin 1234        (na linha de comando)
rem   echo 1234> pin.txt            (arquivo pin.txt nesta pasta, ja ignorado pelo Git)
set "PIN_ARG="
if exist "pin.txt" (
    set /p PIN=<pin.txt
    if defined PIN set "PIN_ARG=--pin !PIN!"
)

".venv\Scripts\python.exe" server.py !PIN_ARG! %*
goto :fim

:erro
echo.
echo Falha ao preparar o servidor. Verifique se o Python 3.10+ esta no PATH.
pause

:fim
endlocal
