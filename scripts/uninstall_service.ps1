<#
.SYNOPSIS
    Remove o servico Windows do Power Central (instalado via install_service.ps1).

.DESCRIPTION
    Para e remove o servico registrado no NSSM. Nao apaga o banco de
    dados nem os arquivos do projeto — só o registro do serviço Windows.

.PARAMETER ServiceName
    Nome do servico Windows (padrao: PowerCentral)

.EXAMPLE
    .\uninstall_service.ps1
#>

param(
    [string]$ServiceName = "PowerCentral"
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

    Write-Error "nssm.exe nao encontrado. Baixe em https://nssm.cc/download e coloque em '$PSScriptRoot' ou no PATH."
    exit 1
}

Confirmar-Administrador
$nssm = Localizar-Nssm

Write-Host "Parando o servico '$ServiceName'..."
& $nssm stop $ServiceName

Write-Host "Removendo o servico '$ServiceName'..."
& $nssm remove $ServiceName confirm

Write-Host "Servico removido. O banco de dados e os arquivos do projeto continuam intactos."
