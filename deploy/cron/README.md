# Die Cron-Jobs des Gateways — als Deklaration statt als Laufzeitzustand

**Warum es diesen Ordner gibt (Befund 22.09.2026).** `openclaw cron list` zeigte
neun aktive Jobs, und die Spalte `Declaration` war bei **allen** ein Strich: sie
existierten ausschliesslich im Gateway-Volume, in keiner Datei und in keinem
Repository. Geht das Volume verloren, sind sie weg. Und für einen zweiten Laden
gab es keine Vorlage, aus der sie entstehen könnten — was genau dann auffiel, als
Ivans Laden einen Agenten bekommen sollte.

Das ist dieselbe Klasse Fehler wie die Marketing-Dienste, die drei Tage still
lagen: **unsichtbarer Betriebszustand, den niemand vermisst, bis er fehlt.**

## Was hier liegt — und was bewusst nicht

Vier **wiederkehrende** Jobs, aus dem laufenden Gateway geholt
(`openclaw cron get <id>`), normalisiert:

| Datei | Zeitplan | Zustellung | Zustand |
|---|---|---|---|
| `antworten-pruefen.json` | `0 */2 * * *` (Versatz 5 min) | keine | aktiv |
| `firmenkontakte-anreichern.json` | alle 20 Minuten | Meldung | **abgeschaltet** |
| `kalenderantworten-schnellcheck.json` | `0 8 * * *` (Europe/Berlin) | Meldung | aktiv |
| `morgen-digest.json` | `0 10 * * 1-5` (Europe/Berlin) | Meldung | aktiv |

**`firmenkontakte-anreichern` ist abgeschaltet (Betreiber, 22.09.2026).** Er lief
**alle 20 Minuten** und meldete jedes Mal — 72 Agentenlaeufe am Tag, und jeder
kostet Modell-Kontingent. Die Deklaration bleibt hier stehen, damit die Absicht
nachlesbar ist und er sich mit einer Zeile zurueckholen laesst; `enabled` steht
auf `false`, und wer diesen Ordner als Saat benutzt, holt ihn NICHT versehentlich
zurueck.

**Nicht aufgenommen:** die vier `Termin: …`-Jobs. Das sind einmalige
Erinnerungen zu konkreten Terminen — Daten, keine Konfiguration. Sie gehören in
den Kalender, nicht in ein Repository.

**Entfernt wurden die Laufzeitfelder** `id`, `createdAtMs`, `updatedAtMs`,
`lastRunAtMs`, `nextRunAtMs`, `lastRunStatus`, `lastDeliveryStatus`, `state`.
Die beschreiben die Vergangenheit **einer** Instanz, nicht die Absicht. Die `id`
vergibt das Gateway beim Anlegen neu.

## `${MELDE_AN}` — der eine Wert, der sich je Mensch unterscheidet

Drei der vier Jobs verkünden ihr Ergebnis an eine WhatsApp-Nummer. Im laufenden
Gateway stand dort die Nummer des Betreibers, **sechsmal eingebrannt** (in
`delivery` und im Auftragstext). Würde man diese Dateien unverändert in Ivans
Gateway spielen, meldeten seine Läufe an Felix' Telefon.

Deshalb steht dort `${MELDE_AN}`. Wer einen Laden einrichtet, setzt den Wert auf
die Nummer **dieses** Menschen.

## Diese Dateien sind eine Momentaufnahme, kein Abgleich

Es gibt (Stand 22.09.2026) **keinen** Mechanismus, der das Gateway gegen diesen
Ordner prüft. Wer einen Job im laufenden Betrieb per `openclaw cron edit` ändert,
ändert ihn **nicht** hier — und beim nächsten Neuaufbau ist die Änderung weg.

Das ist eine ehrliche Zwischenstufe: sichtbar und wiederherstellbar ist besser
als unsichtbar. Aber es ist noch keine Wahrheit. Wer das ändern will, braucht
einen Abgleich in `deploy/smoke.sh` („laufen genau diese vier, mit diesem
Zeitplan?") — dann fällt ein Auseinanderlaufen auf, statt still zu bleiben.
