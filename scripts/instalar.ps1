<#
 Instala o ic-ap direto no Windows (sem Docker). Rode uma vez, no PowerShell, na pasta do projeto:
     powershell -ExecutionPolicy Bypass -File .\scripts\instalar.ps1
 Opcoes:  -SemCloudflared   nao baixa o cloudflared
#>
param([switch]$SemCloudflared)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_ambiente.ps1"

function Passo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Passo "Python"
$py = $null
foreach ($c in @("py -3.13", "py -3.12", "python")) {
    try {
        $v = Invoke-Expression "$c --version" 2>$null
        if ($v -match "Python 3\.(12|13)") { $py = $c; break }
    } catch {}
}
if (-not $py) { throw "Python 3.12 ou 3.13 nao encontrado. Instale com:  winget install Python.Python.3.13" }
Write-Host "Usando: $py"

Passo "Ambiente virtual (.venv)"
if (-not (Test-Path $Python)) { Invoke-Expression "$py -m venv `"$Venv`"" }
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $App "requirements-dev.txt")

Passo "Chromium do Playwright"
& $Python -m playwright install chromium

Passo "ffmpeg"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg nao esta no PATH. Instale com:  winget install Gyan.FFmpeg   (feche e abra o PowerShell depois)"
} else { Write-Host "ok: $((Get-Command ffmpeg).Source)" }

Passo "cloudflared (tunel para o Instagram buscar as imagens)"
$bin = Join-Path $Raiz "bin"
if ($SemCloudflared) { Write-Host "pulado" }
elseif (Test-Path (Join-Path $bin "cloudflared.exe")) { Write-Host "ja existe" }
else {
    New-Item -ItemType Directory -Force $bin | Out-Null
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Invoke-WebRequest $url -OutFile (Join-Path $bin "cloudflared.exe")
    Write-Host "baixado em bin\cloudflared.exe"
}

Passo "Pasta de dados"
New-Item -ItemType Directory -Force $env:DATA_DIR | Out-Null

Passo "Pronto"
Write-Host "Iniciar o painel:  .\scripts\iniciar.ps1     (http://localhost:8000)"
Write-Host "Rodar os testes:   .\scripts\testar.ps1"
