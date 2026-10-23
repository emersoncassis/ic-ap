<#
 Roda a suite de testes (usa banco temporario; nao mexe nos seus dados).
     .\scripts\testar.ps1                      tudo (varios minutos: Chromium e ffmpeg reais)
     .\scripts\testar.ps1 -Rapido              so agentes e wizard
     .\scripts\testar.ps1 -Arquivo tests\test_fluxo.py
 Qualquer outro argumento vai direto para o pytest, ex.:  .\scripts\testar.ps1 -x -q
 Obs.: tests\test_fluxo.py depende da ordem; rode o arquivo inteiro, sem -k.
#>
param([switch]$Rapido, [string]$Arquivo, [Parameter(ValueFromRemainingArguments = $true)]$Resto)
. "$PSScriptRoot\_ambiente.ps1"
if (-not (Test-Path $Python)) { throw "Ambiente nao instalado. Rode primeiro:  .\scripts\instalar.ps1" }
Set-Location $App
$alvo = @()
if ($Rapido) { $alvo = @("tests/test_agentes.py", "tests/test_wizard.py") }
elseif ($Arquivo) { $alvo = @($Arquivo) }
& $Python -m pytest @alvo @Resto
exit $LASTEXITCODE
