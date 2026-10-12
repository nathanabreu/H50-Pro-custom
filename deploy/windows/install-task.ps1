<#
 Instala o H50 Console como tarefa agendada do Windows: sobe sozinho quando você entra no Windows, sem janela.
   powershell -ExecutionPolicy Bypass -File deploy\windows\install-task.ps1            # instala e inicia
   powershell -ExecutionPolicy Bypass -File deploy\windows\install-task.ps1 -Remove    # remove
 Os dados ficam em <repositório>\data (robots.json com os tokens: faça backup pela aba Manutenção).
#>
param([switch]$Remove, [int]$Port = 8050, [string]$Name = "H50 Console")

$ErrorActionPreference = "Stop"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa '$Name' removida."
    exit 0
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$py = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "Python 3.11+ não encontrado. Instale em python.org e tente de novo." }
$pyw = Join-Path (Split-Path $py) "pythonw.exe"          # pythonw: sem janela de console
if (-not (Test-Path $pyw)) { $pyw = $py }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m h50console" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "Painel local para robôs Xiaomi (http://127.0.0.1:$Port)" -Force | Out-Null
$env:H50_PORT = "$Port"
Start-ScheduledTask -TaskName $Name
Write-Host "Instalado e iniciado. Abra http://127.0.0.1:$Port"
Write-Host "No primeiro acesso o código de criação da senha aparece no log: rode `py -m h50console` uma vez no terminal se preferir vê-lo."
