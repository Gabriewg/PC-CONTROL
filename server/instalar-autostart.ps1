# Cria um atalho para iniciar-oculto.vbs na pasta Inicializar do Windows.
# Assim o servidor sobe junto com o login, sem janela de console.

$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $aqui 'iniciar-oculto.vbs'
$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$atalho = Join-Path $startup 'LocalControl Servidor.lnk'

if (-not (Test-Path $vbs)) {
    Write-Host "iniciar-oculto.vbs nao encontrado em $aqui" -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($atalho)
$lnk.TargetPath = 'wscript.exe'
$lnk.Arguments = '"' + $vbs + '"'
$lnk.WorkingDirectory = $aqui
$lnk.Description = 'Servidor Local Control'
$lnk.Save()

Write-Host "Atalho criado em: $atalho" -ForegroundColor Green
Write-Host "O servidor vai iniciar no proximo login (sem janela)." -ForegroundColor Cyan
Write-Host "Para remover, apague o atalho 'LocalControl Servidor' dessa pasta." -ForegroundColor Yellow
