<#
    Registriert die Aufgabe "VibeMind Ollama": scripts\ollama-pc.ps1 bei der
    Anmeldung und danach alle 5 Minuten. Das Skript selbst ist idempotent
    (endet sofort, wenn Ollama schon antwortet) und dient so als Waechter.

    Idempotent (aktualisiert, wenn schon registriert). -WhatIf zeigt nur, was
    registriert wuerde. -Pruefen berichtet nur. Dieses Skript registriert nur,
    es startet die Aufgabe nicht.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param([switch]$Pruefen)

$ErrorActionPreference = "Stop"
$TaskName = "VibeMind Ollama"
$Skript   = Join-Path $PSScriptRoot "ollama-pc.ps1"

$vorhanden = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Pruefen) {
    if ($vorhanden) {
        Write-Output "Aufgabe '$TaskName' ist registriert, Zustand: $($vorhanden.State)"
    } else {
        Write-Output "Aufgabe '$TaskName' ist NICHT registriert"
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $Skript)) { throw "fehlt: $Skript" }

$argumente = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Skript`""
$action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumente
$anmeldung = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Kein -StartWhenAvailable: ein verpasster Start soll nicht sofort nachgeholt werden.
$alle5     = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]"00:10:00") `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Write-Output "Aufgabe:  $TaskName"
Write-Output "Aktion:   powershell.exe $argumente"
Write-Output "Trigger:  bei Anmeldung und alle 5 Minuten; Laufzeit hoechstens 00:10:00; MultipleInstances IgnoreNew"

if (-not $PSCmdlet.ShouldProcess($TaskName, $(if ($vorhanden) { "aktualisieren" } else { "registrieren" }))) {
    exit 0
}

$trigger = @($anmeldung, $alle5)
if ($vorhanden) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
    Write-Output "Aufgabe '$TaskName' aktualisiert (war bereits registriert)"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Haelt Ollama am PC am Laufen und im Tailnet freigegeben (scripts/ollama-pc.ps1)" | Out-Null
    Write-Output "Aufgabe '$TaskName' registriert (nicht gestartet)"
}
