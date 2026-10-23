# Variaveis de ambiente do ic-ap no Windows. Use com:  . "$PSScriptRoot\_ambiente.ps1"
$Raiz = Split-Path -Parent $PSScriptRoot
$env:DATA_DIR      = Join-Path $Raiz "data"
$env:TEMPLATES_DIR = Join-Path $Raiz "templates"
$env:SKILLS_DIR    = Join-Path $Raiz "skills"
$env:CONTEXT_FILE  = Join-Path $Raiz "context\meu_contexto.md"
$env:FEEDS_FILE    = Join-Path $Raiz "config\feeds.yml"
$env:PYTHONUTF8    = "1"
$cf = Join-Path $Raiz "bin\cloudflared.exe"
if (Test-Path $cf) { $env:CLOUDFLARED_BIN = $cf }
$Venv   = Join-Path $Raiz ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$App    = Join-Path $Raiz "services\app"
