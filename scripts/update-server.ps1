#requires -Version 7
<#
.SYNOPSIS
Doppelklick-Update: spielt auf der VM den GitHub-Stand ein und zeigt das
Ergebnis an. Fuer den Betreiber gedacht — ein Klick, eine Antwort.
#>
ssh offload-vm 'bash ~/sales-claw/deploy/update.sh'
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nUpdate in Ordnung." -ForegroundColor Green
} else {
    Write-Host "`nUPDATE MELDET EINEN FEHLER - Ausgabe oben lesen." -ForegroundColor Red
}
Read-Host "Enter zum Schliessen"
