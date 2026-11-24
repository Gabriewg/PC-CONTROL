@echo off
rem Inicia o servidor LocalControl em segundo plano (chamado por iniciar-oculto.vbs).
rem O log fica em server.log, nesta mesma pasta.
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] ERRO: .venv nao encontrada. Rode iniciar.bat uma vez.>> "server.log"
    exit /b 1
)

rem PIN opcional: crie um arquivo pin.txt nesta pasta (fica fora do Git).
set "PIN_ARG="
if exist "pin.txt" (
    set /p PIN=<pin.txt
    if defined PIN set "PIN_ARG=--pin !PIN!"
)

rem O proprio servidor grava em server.log (rotativo, com data/hora); por isso
rem nao redirecionamos o stdout aqui (senao cada linha apareceria duas vezes).
rem O stderr fica para erros fatais do interpretador (tracebacks de crash).
".venv\Scripts\python.exe" server.py !PIN_ARG! 2>> "server.err.log"

endlocal
