@echo off
rem Gera dist\Poltergeist.exe + dist\Poltergeist.exe.sha256.
rem Nao empacota PIN, chaves nem aparelhos: o app cria tudo na primeira execucao.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python...
    python -m venv .venv || goto :erro
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet || goto :erro
".venv\Scripts\python.exe" -m pip install pyinstaller --quiet || goto :erro

echo Gerando icones...
".venv\Scripts\python.exe" gerar_icone_exe.py || goto :erro

echo Empacotando...
".venv\Scripts\python.exe" -m PyInstaller Poltergeist.spec --noconfirm --clean || goto :erro

rem Garantia: nenhum segredo pode ir junto do executavel.
for %%F in (pin.txt devices.json auth_state.json cert.pem key.pem server.log) do (
    if exist "dist\%%F" (
        echo ERRO: dist\%%F nao pode fazer parte do pacote.
        goto :erro
    )
)

echo Gerando checksum SHA-256...
".venv\Scripts\python.exe" -c "import hashlib, pathlib; p = pathlib.Path('dist/Poltergeist.exe'); h = hashlib.sha256(p.read_bytes()).hexdigest(); pathlib.Path('dist/Poltergeist.exe.sha256').write_text(h + '  Poltergeist.exe\n', encoding='utf-8'); print('SHA-256:', h)" || goto :erro

echo.
echo Pronto: dist\Poltergeist.exe
echo Checksum: dist\Poltergeist.exe.sha256
goto :fim

:erro
echo.
echo Falha ao gerar o executavel.
exit /b 1

:fim
endlocal
