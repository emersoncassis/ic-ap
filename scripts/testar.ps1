<#
 Roda o lint (ruff) e a suite de testes (usa banco temporario; nao mexe nos seus dados).
     .\scripts\testar.ps1                      lint + tudo (varios minutos: Chromium e ffmpeg reais)
     .\scripts\testar.ps1 -Rapido              lint + so agentes e wizard
     .\scripts\testar.ps1 -Arquivo tests\test_fluxo.py
     .\scripts\testar.ps1 -Lint                so o lint (ruff check --select F,E9), sem testes
     .\scripts\testar.ps1 -SemLint             pula o lint
 Qualquer outro argumento vai direto para o pytest, ex.:  .\scripts\testar.ps1 -x -q
 Obs.: tests\test_fluxo.py depende da ordem; rode o arquivo inteiro, sem -k.
 O script volta para a pasta de onde foi chamado ao terminar (antes deixava o PowerShell dentro de services\app).
#>
param([switch]$Rapido, [switch]$Lint, [switch]$SemLint, [string]$Arquivo, [Parameter(ValueFromRemainingArguments = $true)]$Resto)
. "$PSScriptRoot\_ambiente.ps1"
if (-not (Test-Path $Python)) { throw "Ambiente nao instalado. Rode primeiro:  .\scripts\instalar.ps1" }
$codigo = 0
Push-Location $App
try {
    if (-not $SemLint) {
        & $Python -m ruff check --select F,E9 .
        $codigo = $LASTEXITCODE
    }
    if ($codigo -eq 0 -and -not $Lint) {
        $alvo = @()
        if ($Rapido) { $alvo = @("tests/test_agentes.py", "tests/test_wizard.py") }
        elseif ($Arquivo) { $alvo = @($Arquivo) }
        & $Python -m pytest @alvo @Resto
        $codigo = $LASTEXITCODE
    }
} finally {
    Pop-Location
}
exit $codigo
