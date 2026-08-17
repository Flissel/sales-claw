#requires -Version 7
<#
.SYNOPSIS
  Gemeinsame Port-Pruefung fuer alle Skripte dieses Repos.
.NOTES
  Bewusst NICHT Get-NetTCPConnection: das Cmdlet meldet "kein Treffer" als
  Fehler. Mit -ErrorAction SilentlyContinue laesst sich dann ein freier Port
  nicht mehr von einem ausgefallenen Cmdlet unterscheiden — beide liefern
  $null, beide werden zu "frei". GetActiveTcpListeners liefert stattdessen
  eine Liste; ein echter Ausfall wirft und wird vom Aufrufer als Fehler
  gewertet statt als Entwarnung.
#>

function Test-PortFrei {
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Port)

    $listener = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return -not ($listener | Where-Object { $_.Port -eq $Port })
}
