@echo off
rem Inicia o servidor LocalControl em segundo plano (chamado por iniciar-oculto.vbs).
rem O log fica em server.log, nesta mesma pasta.
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [%date% %time%] ERRO: .venv nao encontrada. Rode iniciar.bat uma vez.>> "server.log"
    exit /b 1
)

rem PIN obrigatorio: pin.txt e criado por definir-pin.bat (ou iniciar.bat no
rem primeiro uso). O PIN nunca e passado pela linha de comando.
if not exist "pin.txt" (
    echo [%date% %time%] ERRO: PIN nao configurado. Rode definir-pin.bat>> "server.log"
    exit /b 1
)

rem O proprio servidor grava em server.log (rotativo, com data/hora); por isso
rem nao redirecionamos o stdout aqui (senao cada linha apareceria duas vezes).
rem O stderr fica para erros fatais do interpretador (tracebacks de crash).
".venv\Scripts\python.exe" server.py %* 2>> "server.err.log"

endlocal
