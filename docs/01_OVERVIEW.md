# 01 — Überblick

`sales-claw` ist eine eigenständige OpenClaw-Instanz für den Vertriebsarbeitsplatz.
Sie läuft als Container neben der persönlichen lokalen Installation und neben
`openclaw-festival` auf der Proxmox-VM.

## Was diese Stufe leistet

- OpenClaw läuft reproduzierbar im Container, gepinnt auf eine feste Version
- Der Zustand (Konfiguration, WhatsApp-Kopplung, Gedächtnis) liegt in zwei Volumes
- Sicherung und Wiederherstellung sind nachgewiesen, nicht behauptet
- Der Umzug auf die Proxmox-VM ist vorbereitet, aber nicht ausgeführt

## Was diese Stufe nicht leistet

Keine Fachlogik, kein Datenmodell, keine Bedarfsanalyse, keine Antworten an Dritte.
Der Container spricht ausschließlich mit der Nummer des Betreibers (Selbst-Chat).

*Stand 19.08.2026: Der letzte Satz beschreibt die Stufe 1, nicht mehr den
Endzustand — seit dem Auto-Betrieb spricht der Agent zusätzlich mit
Kontakten, die der Betreiber ausdrücklich freigegeben und per
`scripts/sync-allowlist.ps1` in die Allowlist übernommen hat
(Runbook „Auto-Betrieb").*

## Einstiegspunkte

| Ich will … | … dann |
|---|---|
| prüfen, ob alles bereit ist | `pwsh -File scripts/preflight.ps1` |
| den Container starten | `docker compose up -d` |
| den Zustand sichern | `pwsh -File scripts/backup-state.ps1` |
| die Abnahme fahren | `pwsh -File scripts/smoke-test.ps1` |
| auf die VM umziehen | `docs/07_PROXMOX_MIGRATION.md` |
