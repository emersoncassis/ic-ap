<#
 Sobe o painel do ic-ap em http://127.0.0.1:8000 (somente neste computador).
     .\scripts\iniciar.ps1
 Opcoes:
     -Porta 8000           porta do painel
     -AoLigarWindows       cria uma tarefa agendada que sobe o painel ao entrar no Windows
     -RemoverTarefa        remove essa tarefa
#>
param([int]$Porta = 8000, [switch]$AoLigarWindows, [switch]$RemoverTarefa)
. "$PSScriptRoot\_ambiente.ps1"
$nome = "ic-ap painel"

if ($RemoverTarefa) { Unregister-ScheduledTask -TaskName $nome -Confirm:$false; Write-Host "Tarefa removida."; return }

if (-not (Test-Path $Python)) { throw "Ambiente nao instalado. Rode primeiro:  .\scripts\instalar.ps1" }

if ($AoLigarWindows) {
    $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Porta $Porta"
    $acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Raiz
    $gatilho = New-ScheduledTaskTrigger -AtLogOn
    $cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $cfg -Force | Out-Null
    Write-Host "Tarefa '$nome' criada: o painel sobe sozinho quando voce entrar no Windows."
    return
}

New-Item -ItemType Directory -Force $env:DATA_DIR | Out-Null
Set-Location $App
Write-Host "ic-ap em http://localhost:$Porta  (Ctrl+C para parar)" -ForegroundColor Green
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Porta
