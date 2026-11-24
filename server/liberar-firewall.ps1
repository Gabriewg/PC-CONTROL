# Roda como Administrador.
# Libera a porta do servidor no firewall do Windows para acesso via Wi-Fi.

$porta = if ($args.Count -ge 1) { $args[0] } else { 8765 }

Write-Host "Liberando TCP $porta e UDP 8766 no firewall..." -ForegroundColor Cyan

netsh advfirewall firewall delete rule name="LocalControl TCP" | Out-Null
netsh advfirewall firewall delete rule name="LocalControl UDP" | Out-Null

netsh advfirewall firewall add rule name="LocalControl TCP" dir=in action=allow protocol=TCP localport=$porta | Out-Null
netsh advfirewall firewall add rule name="LocalControl UDP" dir=in action=allow protocol=UDP localport=8766 | Out-Null

Write-Host "Pronto. Portas liberadas para as redes locais." -ForegroundColor Green
Write-Host "Se estiver em rede publica, marque a rede como Privada para maior compatibilidade." -ForegroundColor Yellow
