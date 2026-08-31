# 08 — Technische und organisatorische Maßnahmen (TOMs)

Destilliert aus dem gebauten System (Stand 31.08.2026). Jede Zeile ist
im Betrieb messbar — nichts hier ist Absichtserklärung. Referenzen:
[04_BETRIEB_MINIPC.md](04_BETRIEB_MINIPC.md), [06_DSGVO.md](06_DSGVO.md).

## Zugang und Zugriff

- Die Anlage läuft auf einer eigenen VM ohne öffentliche Ports; erreichbar
  nur im Tailscale-Netz (WireGuard-verschlüsselt, gerätegebundene
  Schlüssel). SSH ausschließlich mit Schlüsseln.
- Die Anzeige-Oberfläche nutzt einen eigenen Nur-Lese-API-Schlüssel
  (VIEWER-Key): Lesen erlaubt, Senden gemessen verweigert (HTTP 403).
- Code kommt über einen Nur-Lese-Deploy-Key; auf der VM wird nie
  editiert (fast-forward-only).
- Wer dem Assistenten schreiben darf, steht auf einer Allowlist, die
  ausschließlich ein Mensch pflegt.

## Trennung und Datensparsamkeit

- Produktions- und Testdaten liegen in getrennten Schemata; Tests laufen
  nur gegen das Testschema.
- Privat markierte Kontakte sind fail-closed vom Assistenten abgeschirmt
  (kein Entwurf, kein Profil, Inbox-Drop ohne Nummern-Log).
- Werbliche Erstansprache nur mit dokumentierter Einwilligung
  (UWG-Tor, § 7 UWG — 06, Abschnitt Werbe-Einwilligung).

## Protokollierung und Eingabekontrolle

- Jede relevante Aktion landet als Aktivität in der Datenbank:
  Stufenwechsel mit Begründungspflicht, Einwilligungen mit Quelle,
  Löschanträge mit Wortlaut, Freigaben mit Freigebendem und Zeit.
- Freigaben sind an den gelesenen Text gebunden (Fingerprint) — was
  freigegeben wurde, ist beweisbar das, was gesendet wurde.
- Der Assistent kann bestellen, aber nie ausführen: Updates, Versand-
  Neustarts und Wartungsläufe führt das Wirtssystem über einen
  Auftrags-Spool aus.

## Verfügbarkeit und Wiederherstellbarkeit

- Tägliche Sicherung (04:35, sieben rotierende Stände) plus
  Offsite-Spiegel auf einen zweiten Host (rsync, gemessen).
- Betriebs-Wache alle 15 Minuten; rote Befunde erreichen den Betreiber
  über den Antwort-Takt des Assistenten.
- Updates mit automatischer Abnahme und automatischem Rollback bei
  rotem Ergebnis; Stand vor jedem Update als Git-Tag.

## Prüfbarkeit

- Über 1.450 Vertragstests; die komplette Suite läuft bei jedem Push
  in der CI. Jedes Update endet mit einer Abnahme (Smoke-Prüfungen),
  die den Erfolg misst statt behauptet.

## Organisatorisch

- Löschkonzept mit Vollstopp, Vier-Augen-Prinzip und 30-Tage-Frist (06).
- Geheimnisse stehen nie in Kommandozeilen, Ausgaben oder Logs;
  Rotations-Runbook ist Aufgabe F6 des Betriebsplans.
- Verhaltensregeln des Assistenten (AGENTS.md) sind versioniert und
  werden über die Update-Maschinerie ausgerollt — Änderungen sind
  nachvollziehbar wie Code.
