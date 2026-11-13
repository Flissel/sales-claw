# Bildauswertung live in der Termin-Akte (Design)

Stand 13.11.2026. Baut auf dem Meeting-Mittelpunkt auf
(`2026-11-10-meeting-mittelpunkt-design.md`: Termin-Akte, Vexa-Bot, Mitschrift,
Auswertung, Nachlöschen).

## Warum

Die Mitschrift kennt nur, was gesagt wird. In Terminen zeigt Felix oft etwas
("guck mal hier", "das hier ist der Graph") und das Gesagte allein ist dann
unverständlich. Beispiel aus der Abnahme am 12.11.: Die Auswertung hat aus
Wortfetzen "Bildtiefe im Screen messen" geraten, weil sie nicht sehen konnte,
was auf dem geteilten Bildschirm war.

Felix' Bild: Laura (unser Video-Agent) läuft im Hintergrund mit, sieht den
geteilten Bildschirm, beschreibt was zu sehen ist, macht es durchsuchbar
(Visual Embeddings) und hängt es passend an das Transkript, und zwar live
sichtbar in der Termin-Akte.

## Ziele (Stufe 1)

1. Sobald in einem Termin **ein Bildschirm geteilt** wird, egal von wem, werden
   Standbilder dieses geteilten Bildschirms erfasst.
2. Ein neues Standbild entsteht nur, wenn sich das Bild **spürbar ändert**
   (neue Folie, neuer Graph, anderes Fenster). Stehende Bilder erzeugen keine
   Flut.
3. Zu jedem Standbild entstehen eine **kurze Beschreibung** (was ist zu sehen,
   lesbare Überschriften und Kernaussagen) und ein **Bild-Embedding**, das per
   Text durchsuchbar ist.
4. Jedes Standbild trägt seine **Uhrzeit** und wird über diese den
   Mitschrift-Segmenten zugeordnet.
5. Die Termin-Akte (`/termine/{uid}`) zeigt die Standbilder mit Beschreibung
   **live während des Termins**, neue erscheinen nach und nach (Ziel: wenige
   Sekunden bis Beschreibung, Bild selbst sofort).
6. Die Auswertung nach dem Termin bezieht die Bildbeschreibungen ein. Der
   Gesprächsverlauf benennt, was gezeigt wurde, und verweist auf die Bilder.
7. Standbilder, Beschreibungen und Embeddings werden **mit der Mitschrift
   gelöscht** (alle bestehenden Löschwege: Nachlöschen, Löschantrag, "Nein").

## Nicht-Ziele (Stufe 1)

- **Keine Kamerabilder.** Gesichter und Kamerakacheln werden weder gespeichert
  noch ausgewertet. Erfasst wird nur die Fläche des geteilten Bildschirms.
- **Kein Video.** Es entsteht keine Video- oder Rohdatei, auch nicht
  zwischenzeitlich. (Bestätigt die Regel "Kein Rohmitschnitt bei Vexa",
  docs/06_DSGVO.md.)
- **Keine Kundentermine.** Stufe 1 läuft nur in Terminen, die Felix per
  Schalter als intern markiert (siehe "Welche Termine").
- Laura greift nicht ein: keine Hinweise an Felix, keine Schnittmarken. Das
  ist die Ausbaustufe (unten).
- Keine Live-Mitschrift in der Akte. Live sind nur die Bilder.

## Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- Ein Kamerabild oder ein Ausschnitt mit Gesichtern landet in Speicher, Modell
  oder Akte.
- Die Tonmitschrift von Vexa wird schlechter oder fällt aus, weil die
  Bildauswertung Last oder Störungen erzeugt.
- Bilder oder ihre Beschreibungen tauchen in Logs auf (Regel: keine
  Geheimnisse/Kundentexte in Logs) oder überleben das Löschen der Mitschrift.
- Laufende Kosten über bezahlte APIs ("kein API-Budget").
- Die Akte wird während des Termins langsam oder hängt.

## Von Felix entschieden

- Ausgewertet wird jeder geteilte Bildschirm, egal wer teilt. Kamerabilder nie.
- Live in der Akte, nicht erst nach dem Termin.
- Live-Ansicht dient zum Mitlesen. Laura handelt in Stufe 1 nicht selbst.
- Erst nur interne Termine. Kundentermine später mit Hinweis in der Einladung:
  bitte keine persönlichen Daten zeigen, sonst wird die Aufzeichnung gelöscht.
- "Intern" setzt Felix selbst: Schalter "Bildschirm auswerten" in der Akte,
  vorbelegt aus, je Termin bewusst einschalten.
- Ausbaustufe einplanen: Laura erkennt Pausen (lange Stille, stehendes Bild)
  als Stellen zum Rausschneiden, und markiert später Ausschnitte für den
  Videocutter.

## Von Claude entschieden (bitte prüfen)

- **Eigener Beobachter statt Vexa-Umbau.** Vexa läuft als unverändertes
  Upstream-Abbild (`vexaai/vexa-lite:v0.12.28`); dessen eingebaute
  Videoaufnahme filmt das ganze Bot-Fenster inklusive Kamerakacheln und lädt
  erst nach Termin eine Videodatei hoch, passt also zu keinem Punkt oben. Stattdessen
  tritt ein eigener, schlanker Beobachter dem Termin bei (headless Browser),
  sichtbar als Teilnehmer **"Laura (Bildschirm)"**. Er empfängt nur den
  Bildschirm-Track, kein Ton, keine Kameras, und sendet selbst nichts.
  Begründung: Vexa bleibt updatefähig, Kameras sind technisch ausgeschlossen
  statt nachträglich weggeschnitten, Laura ist für alle sichtbar.
- **Zuerst nur Jitsi** (`JITSI_BASIS`, derzeit meet.ffmuc.net). Interne
  Termine laufen heute über Jitsi. Meet/Teams/Zoom brauchen je eigene
  Beitritts- und Erkennungslogik und kommen später.
- **Lebenszyklus am Vexa-Bot:** Der Taktgeber (`termin_takt`) schickt den
  Beobachter zusammen mit dem Vexa-Bot und holt ihn mit ihm wieder heraus
  (gleiche Regeln: Sicherheitsstopp nach Terminende, "Ohne Aufnahme",
  Löschantrag, `kein_bot`). Ist Vexa nicht eingerichtet oder kommt kein Bot,
  kommt auch kein Beobachter. Fällt nur der Beobachter aus, läuft die
  Tonmitschrift unberührt weiter.
- **Beschreibung über das bestehende KI-Tor** (sales-ki, Claude). Das Tor
  bekommt Bildeingabe dazu (heute nur Text, `claude -p` ohne Werkzeuge, z. B.
  über Bild-Inhalte im stream-json-Eingang). Bildbeschreibungen bekommen eine
  **eigene Spur** mit kurzer Zeitgrenze und dürfen nicht hinter einer
  minutenlangen Auswertung oder einem Briefing warten; sie dürfen bei
  Engpass nachlaufen (Bild sofort sichtbar, Text später). Damit gehen Bilder
  interner Termine an Anthropic, wie heute schon die Mitschriften. Kein
  lokales Bildmodell in Stufe 1.
- **Embeddings lokal auf der CPU**, mit einem CLIP-artigen Modell, das Bild und
  Text in denselben Raum legt (z. B. fastembed, das Laura für Text schon nutzt).
  Weil CLIP-Textkodierer englisch geprägt sind, wird zusätzlich die deutsche
  Beschreibung mit einem Textmodell eingebettet; die Suche nutzt beides.
  **Ablage mit pgvector in der Sales-Datenbank** (Schema des Betreibers),
  nicht in Lauras Qdrant: So hängen die Vektoren per Fremdschlüssel an der
  Mitschrift und verschwinden beim Löschen in derselben Transaktion; kein
  neuer Dienst, kein fremder Stack. Ist pgvector dort nicht verfügbar, ein
  eigener Qdrant im sales-claw-Stack.
- **Suche:** ein Suchfeld im Bildschirm-Abschnitt der Akte (dieser Termin) und
  ein MCP-Werkzeug über alle Termine, damit Laura/Agenten später darauf
  zugreifen.
- **Ausgelöst je Bildänderung, gedrosselt:** höchstens ein Standbild alle 5
  Sekunden, Obergrenze 150 Standbilder je Termin (danach nur noch erfassen,
  wenn sich das Bild sehr stark ändert, und in der Akte vermerken), damit ein
  Folienfeuerwerk weder den Termin noch das Claude-Abo verstopft.
- **Gesichter auf dem geteilten Bildschirm** (z. B. ein geteiltes Fenster mit
  einem anderen Videocall): in Stufe 1 nach bestem Bemühen, keine
  Gesichtserkennung. Die Beschreibung nennt keine Personen anhand ihres
  Aussehens. Vertretbar, weil nur interne Termine.
- **Ressourcen:** Die VM hat 12 Kerne und derzeit ~5 GB freien Speicher. Der
  Beobachter bekommt harte Grenzen (z. B. 1 Kern, 1 GB) und empfängt nur den
  Bildschirm-Track in niedriger Bildrate, damit Vexa nicht leidet.
- **Aufbewahrung:** Standbilder als komprimierte Bilder, zugeordnet zur
  Termin-Akte bzw. Mitschrift; gelöscht zusammen mit der Mitschrift.

## Welche Termine (Felix, 13.11.)

Laut Meeting-Mittelpunkt bekommt nur ein *Kundentermin* Akte und Bot: jeder
sales-claw-Termin und jeder Kalendertermin mit mindestens einem Externen.
Externe sind alle außer Felix und dem Team (Ivan und Logins im Laden). Ein
Gespräch mit Surya zählt danach als Kundentermin. Ein Termin nur mit dem Team
hat gar keine Akte. "Intern" lässt sich also nicht aus den Adressen ablesen.
Wer unangekündigt in den Raum kommt, ist ohnehin unbekannt.

Deshalb hängt die Bildauswertung an einer bewussten Markierung des Termins:
Die Akte bekommt einen Schalter **"Bildschirm auswerten"**, vorbelegt **aus**.
Felix schaltet ihn je Termin selbst ein, wenn das Gespräch intern ist. Nur
dann tritt der Beobachter bei. Schaltet Felix ihn während des Termins aus,
verlässt der Beobachter den Raum sofort; danach entstehen keine Bilder mehr.
Bereits erfasste Bilder bleiben, bis die Mitschrift gelöscht wird oder Felix
sie in der Akte löscht. Der Schalter ist in der Akte vor und während des
Termins bedienbar (auch am Handy). In Stufe 1 gibt es keine automatische
Vorbelegung.

## Zuordnung zum Transkript

Vexa-Segmente tragen absolute Startzeiten (`beginn`). Ein Standbild gehört zu
dem Zeitraum ab seiner Aufnahme bis zum nächsten Standbild bzw. Ende der
Freigabe. Daraus folgt:

- In der Akte steht bei jedem Bild die Uhrzeit und, sobald die Mitschrift
  vorliegt, der passende Abschnitt.
- Für die Auswertung werden die Beschreibungen zeitrichtig zwischen die
  Mitschrift-Zeilen gesetzt (z. B. `[Bild 14:23] Graph von sin(x²) ...`). Der
  Verlauf erhält je Eintrag die zugehörigen Bilder (Verweis, nicht Bildinhalt).

## Live in der Akte

Die Akte hat heute keinen Live-Mechanismus (statische Seiten; es gibt aber
Seiten mit eigenem kleinem JS, z. B. Kalender, Editor). Neu: ein Abschnitt
"Bildschirm" in der Akte, der während des Termins regelmäßig neue Bilder holt
und anzeigt: Vorschaubild, Uhrzeit, Beschreibung (sobald fertig), wer geteilt
hat, falls erkennbar. Nach dem Termin bleibt der Abschnitt als Bildleiste
neben Verlauf und Ergebnis.

## Ausbaustufe (nur eingeplant, nicht bauen)

- Pausenerkennung: lange Stille (aus der Mitschrift) oder stehendes Bild (aus
  der Änderungserkennung) als Zeitspannen zum Rausschneiden markieren. Die
  Datenablage in Stufe 1 hält deshalb je Bild fest, wie lange es unverändert
  stand.
- Rausschneiden setzt ein Video voraus, das es in Stufe 1 bewusst nicht gibt.
  Dafür entscheidet Felix später, ob es Termine mit echter Videoaufnahme gibt
  (z. B. für Lauras Videoraum).
- Laura handelt live: Hinweise an Felix, Ausschnitte für den Videocutter
  vormerken.
- Kundentermine: Hinweistext in der Einladung, Schalter auch dort.

## Rahmenbedingungen

- Läuft auf der VM (`offload-vm`) im sales-claw-Stack; gezieltes Ausrollen nur
  der betroffenen Dienste, openwa (WhatsApp) nie neu erstellen.
- Ladenfest: alles liegt beim Betreiber, nichts in Ivans Laden.
- Keine Bilder, Beschreibungen, Termintitel oder Geheimnisse in Logs.
- Kein `docker volume prune`, `system prune`, `--remove-orphans`.
- Vexa-Abbild bleibt unverändert; dessen Not-Aus für Rohmitschnitte bleibt an.
- Tests im bestehenden Stil (pytest gegen Test-DB, Attrappen für Browser und
  KI-Tor).

## Abnahme

1. Interner Jitsi-Termin, Felix teilt seinen Bildschirm und wechselt mehrmals
   Fenster/Folien: In der Akte erscheinen die Bilder live, Beschreibungen
   folgen innerhalb von Sekunden; ein stehendes Bild erzeugt keine weiteren.
2. Ein zweiter Teilnehmer teilt ebenfalls: auch dessen Bildschirm erscheint.
3. Kameras an während des ganzen Termins: kein Kamerabild irgendwo
   (Speicher, Qdrant, Akte, KI-Tor-Aufrufe).
4. Tonmitschrift ist vollständig wie ohne Beobachter.
5. Nach dem Termin: Der Verlauf der Auswertung benennt Gezeigtes und verweist
   auf Bilder; Textsuche ("Graph", "Kursliste") findet passende Bilder.
6. Termin ohne eingeschalteten Schalter: kein Beobachter tritt bei.
   Schalter während des Termins aus: Beobachter geht binnen einer Taktrunde.
7. Löschen der Mitschrift entfernt Bilder, Beschreibungen und Vektoren.

## Dem Bauenden überlassen

Browser-Technik des Beobachters, Erkennung "wird gerade geteilt" in Jitsi,
Schwellen der Änderungserkennung, Bildformat und Ablageort, genaues
Embedding-Modell, Polling-Takt der Akte, Datenbankschema, Aufteilung in
Dienste/Container.
