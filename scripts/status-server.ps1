#requires -Version 7
<#
.SYNOPSIS
Doppelklick-Status: fuehrt die Abnahme (smoke.sh) auf der VM aus und zeigt
den letzten Update-Status an. Alles "ok" = dem System geht es gut.
#>
ssh offload-vm 'bash ~/sales-claw/deploy/smoke.sh; echo "--- letztes Update ---"; cat ~/sales-betrieb/update-status.json 2>/dev/null || echo "(noch keines)"'
Read-Host "Enter zum Schliessen"
