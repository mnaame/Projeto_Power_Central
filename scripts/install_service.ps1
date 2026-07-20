<#
.SYNOPSIS
    Instala o Power Central como servico do Windows usando o NSSM.

.DESCRIPTION
    Rode como Administrador, com o NSSM (https://nssm.cc/download) ja
    baixado e "nssm.exe" acessivel no PATH ou na mesma pasta deste script.

    O script:
      1. Confere pre-requisitos (Administrador, NSSM, ambiente virtual, .env)
      2. Aplica as migrations do banco (flask db upgrade)
      3. Registra o servico Windows (waitress-serve) com reinicio automatico
      4. Liga o servico

    Depois de instalado, crie o primeiro administrador com:
      .venv\Scripts\python.exe -m flask seed-admin

.PARAMETER ServiceName
    Nome do servico Windows (padrao: PowerCentral)

.PARAMETER InstallPath
    Pasta onde o projeto foi clonado/copiado (padrao: pasta atual)

.PARAMETER Port
    Porta TCP onde a aplicacao vai escutar (padrao: 8000).

.PARAMETER BindHost
    Endereco em que o waitress escuta (padrao: 127.0.0.1 — só a própria
    máquina, mais seguro, para usar atrás de reverse proxy/Cloudflare
    Tunnel). Use "0.0.0.0" para liberar acesso de outros computadores da
    MESMA rede local (sem HTTPS — ok para uso interno confiável; ver
    docs/OPERACAO.md seção 4 para HTTPS interno ou acesso externo).

.EXAMPLE
    .\install_service.ps1 -InstallPath "C:\power_central" -Port 8000

.EXAMPLE
    # Libera para qualquer computador da rede local acessar (sem HTTPS)
    .\install_service.ps1 -InstallPath "C:\power_central" -Port 8000 -BindHost "0.0.0.0"
#>

param(
    [string]$ServiceName = "PowerCentral",
    [string]$InstallPath = (Get-Location).Path,
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

function Confirmar-Administrador {
    $identidade = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identidade)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "Rode este script como Administrador (botao direito no PowerShell > Executar como administrador)."
        exit 1
    }
}

function Localizar-Nssm {
    $comando = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($comando) { return $comando.Source }

    $local = Join-Path $PSScriptRoot "nssm.exe"
    if (Test-Path $local) { return $local }

    Write-Error "nssm.exe nao encontrado. Baixe em https://nssm.cc/download, extraia o executavel win64 e coloque em '$PSScriptRoot' ou em uma pasta do PATH."
    exit 1
}

Confirmar-Administrador
$nssm = Localizar-Nssm

$venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
$waitress = Join-Path $InstallPath ".venv\Scripts\waitress-serve.exe"
$envFile = Join-Path $InstallPath ".env"
$logsDir = Join-Path $InstallPath "logs"

if (-not (Test-Path $venvPython)) {
    Write-Error "Ambiente virtual nao encontrado em '$venvPython'. Rode antes:`n  python -m venv .venv`n  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path $envFile)) {
    Write-Warning "'$envFile' nao encontrado. Copie .env.example para .env e preencha antes de continuar (credenciais do portal, SECRET_KEY, ENCRYPTION_KEY)."
}
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

Write-Host "Aplicando migrations do banco..."
Push-Location $InstallPath
$env:FLASK_APP = "app:create_app"
& $venvPython -m flask db upgrade
Pop-Location

Write-Host "Instalando o servico '$ServiceName'..."
& $nssm install $ServiceName $waitress "--host=$BindHost --port=$Port --call app:create_app"
& $nssm set $ServiceName AppDirectory $InstallPath
& $nssm set $ServiceName AppEnvironmentExtra "START_SCHEDULER=true"
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppExit Default Restart
& $nssm set $ServiceName AppRestartDelay 5000
& $nssm set $ServiceName AppStdout (Join-Path $logsDir "service_stdout.log")
& $nssm set $ServiceName AppStderr (Join-Path $logsDir "service_stderr.log")

Write-Host "Iniciando o servico..."
& $nssm start $ServiceName

if ($BindHost -eq "0.0.0.0") {
    $regraExistente = Get-NetFirewallRule -DisplayName "Power Central ($Port)" -ErrorAction SilentlyContinue
    if (-not $regraExistente) {
        New-NetFirewallRule -DisplayName "Power Central ($Port)" -Direction Inbound -LocalPort $Port -Protocol TCP -Action Allow | Out-Null
        Write-Host "Regra de firewall criada, liberando a porta $Port para a rede."
    }
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
    Write-Host ""
    Write-Host "Pronto. Na MESMA rede local, outros computadores acessam em http://${ip}:$Port"
    Write-Host "(sem HTTPS — ok para uso interno confiavel; para HTTPS ou acesso de fora da rede, veja docs/OPERACAO.md secao 4)"
} else {
    Write-Host ""
    Write-Host "Pronto. O painel responde em http://127.0.0.1:$Port nesta maquina."
    Write-Host "Para outros computadores acessarem, reinstale com -BindHost '0.0.0.0', ou configure um reverse proxy (docs/OPERACAO.md secao 4)."
}
Write-Host "Se ainda nao existe nenhum administrador, crie um com:"
Write-Host "  $venvPython -m flask seed-admin"
