# Neue Marke per Skill: `/marke_neu` im Marken-Chat, dazu ein Leitfaden für Marketing-Skills

Stand: 21.10.2026. Betrifft vibemind-os (`spaces/marketing`) und sales-claw (`sales-mcp/ui_marke.py`).

## Absicht

Eine neue Marke (Firma, `marketing.mandanten`) entsteht heute nur per Datenbankbefehl. Danach muss der Betreiber
das Profil Stück für Stück im Marken-Chat zusammentragen und weiß nicht, was noch fehlt. Der Betreiber will:

- im bestehenden Marken-Chat einen Befehl tippen, der ein **geführtes Gespräch** startet;
- das Gespräch läuft nach einem **Skill**, der zu Beginn strukturiert die wertvollen Angaben abfragt;
- am Ende ist die Marke in der Oberfläche eingepflegt (im Firmen-Umschalter, Profil gefüllt, Newsletter-Pflichtteil da);
- der Befehl folgt der **OpenClaw-Konvention** und kollidiert nicht mit deren eingebauten Befehlen (`/new` ist dort
  der Sitzungs-Reset).

Daraus folgt ein zweites, allgemeineres Ergebnis: ein **Leitfaden**, wie Marketing-Skills künftig gebaut und in
unsere Chats (und optional ins OpenClaw-Gateway) eingebunden werden. `/marke_neu` ist der erste Skill nach diesem
Leitfaden.

## Ausgangslage (gemessen 21.10.)

- Marken-Chat: `sales-mcp/ui_marke.py` → `POST /api/pult/marke/chat` (`api/marke.py`) → `marketing.pult_marke_anlegen`
  → `workers/marken_arbeiter.py` (`chat_bearbeiten`, `_chat_mit_spur`) über den Marketing-Shim, ohne Werkzeuge
  (`marketing_ohne_werkzeuge`), Websuche optional. Profil-Wahrheit: `companys/<Firma>/Marke.md` (Rowboat-Wissen),
  14 Abschnitte (`markenprofil.ABSCHNITT_REIHENFOLGE`) plus Kopf (Farben, Schriften, Stimme, Logo, Webseite).
  Textänderungen gelten direkt, Farben/Schriften/Logo/Stimme/Webseite als Vorschlag mit „Übernehmen“.
- Kein Chat kennt heute Slash-Befehle. Nur `workers/telegram_bot.py` belegt `/neu /new /reset /start /hilfe /help`.
- Mandanten: Tabelle `marketing.mandanten (id ^[a-z][a-z0-9_]{1,30}$, name, aktiv, verteiler, pflichtteil)`, keine
  API und keine DB-Funktion zum Anlegen. `pult_marke_anlegen` verlangt `aktiv`. Der Umschalter zeigt nur aktive.
  `pflichtteil.impressum` und `abmelde_hinweis` werden gerendert, `vermittlerangaben` nirgends.
- OpenClaw: Skill = Ordner mit `SKILL.md` (Frontmatter einzeilig: `name`, `description`, optional `user-invocable`,
  `disable-model-invocation`, `metadata` als einzeiliges JSON). Befehlsname = `name` bereinigt (klein, alles außer
  `a-z0-9_` → `_`, höchstens 32 Zeichen); Kollision mit eingebauten Namen (u. a. `new`, `reset`, `help`, `skill`,
  `status`, `stop`, `model`, `config` …) hängt still `_2` an. Zusätzlich gilt immer `/skill <name> [text]`.
- Unsere Chats laufen über den Shim, nicht über OpenClaw: ein Skill-Ordner allein erreicht das Modell nicht. Das
  funktionierende Muster ist `workers/video_claw.py`: Code liest `SKILL.md`, schneidet das Frontmatter ab und hängt
  den Text an den System-Prompt.

## Ziele

1. **Leitfaden + Lader für Marketing-Skills.** Ein Ort (`spaces/marketing/skills/<name>/SKILL.md`), ein Format
   (OpenClaw-kompatibel), ein Lader im Code, der daraus Befehle für unsere Chats macht.
2. **`/marke_neu [Name] [Webseite]` im Marken-Chat** startet die Einrichtung einer neuen Marke. Auch
   `/skill marke-neu …` funktioniert (gleiche Auflösung wie OpenClaw).
3. **Geführtes Gespräch:** Webseite zuerst lesen und vorfüllen, danach nur die Lücken abfragen, eine Frage pro Runde,
   mit sichtbarem Fortschritt („Schritt 3 von 7“).
4. **Abschluss mit Bestätigung:** Zusammenfassung → Betreiber bestätigt → Marke wird aktiv, erscheint im Umschalter,
   Profil und Pflichtteil sind gespeichert, Newsletter-Layout der Marke ist gespiegelt.

## Nicht-Ziele

- Kein Telegram-/OpenClaw-Befehl `/marke_neu` in dieser Runde (der Leitfaden beschreibt den Weg; das Gateway hat
  heute kein Marken-Werkzeug).
- Keine Laden-Anbindung (`MARKETING_MANDANT`/`LADEN_MARKE` in sales-Läden) – das bleibt ein eigener Schritt.
- Kein Umbau der bestehenden Skills (email-kampagne, newsletter-bild, video_claw …) auf den neuen Lader. Der
  Leitfaden gilt für Neues; Umzug später.
- Kein Löschen bestehender Marken über die Oberfläche.

## Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)

- Eine halb eingerichtete Marke taucht im Umschalter auf und bekommt Newsletter, Vorlagen oder Aufträge.
- Das Modell **erfindet Rechtsangaben** (Impressum, Vermittlerangaben). Diese stammen wörtlich vom Betreiber oder
  wörtlich von der gelesenen Webseite und werden in der Zusammenfassung ausdrücklich bestätigt.
- Der Befehl heißt `/new`, `/neu` oder kollidiert anders mit OpenClaw- oder Telegram-Befehlen.
- Das Gespräch fühlt sich an wie ein Formular mit 30 Feldern. Es fragt nur, was fehlt, und erklärt kurz, warum
  eine Angabe wertvoll ist.

## Das Gespräch (Inhalt des Skills `marke-neu`)

Reihenfolge der Schritte; ein Schritt gilt als erledigt, sobald seine Felder gefüllt oder bewusst übersprungen sind
(„weiß ich nicht / später“). Pflicht für den Abschluss: Schritt 1 und **Impressum + Abmeldehinweis** aus Schritt 2 –
die beiden lassen sich nicht überspringen (Newsletter ohne Impressum wären ein Rechtsproblem). Vermittlerangaben sind
Pflicht nur, wenn der Betreiber die Frage „Seid ihr Finanz- oder Versicherungsvermittler?“ mit Ja beantwortet; der
Agent stellt die Frage, entscheidet sie aber nie selbst.

1. **Name und Webseite** – Firmenname (wird `name`), daraus die `id`; Webseite (wird gelesen, vorgefüllt).
2. **Pflichtangaben für Newsletter** – Impressum, Abmeldehinweis (Vorgabe angeboten, muss `{abmeldelink}`
   enthalten), bei Finanz-/Versicherungsvermittlern die Vermittlerangaben.
3. **Wer und was** – Kurz gesagt, Wer wir sind, Angebote, Zielgruppe, Abgrenzung.
4. **Aussehen** – Logo (Upload im Chat oder von der Webseite), Akzent-/Zweit-/Grund-/Textfarbe, Schriften.
5. **Stimme** – Ton, Wörter, Do & Don'ts, Sprechstimme.
6. **Belege** – Fakten und Zahlen, Kanäle, Menschen, Bildstil.
7. **Zusammenfassung und Bestätigung.**

Je Runde antwortet der Agent mit: was er übernommen hat (kurz), dem Fortschritt, **genau einer** nächsten Frage und
einem Satz, wozu die Angabe dient. Mehrere Angaben in einer Antwort des Betreibers werden alle übernommen.

## Wie es gebaut wird (vom Betreiber entschieden)

- Befehl im **bestehenden Marken-Chat**, keine eigene Seite.
- Name nach OpenClaw-Konvention: Skill `marke-neu` → `/marke_neu`, zusätzlich `/skill marke-neu`.
- Skill-Datei im OpenClaw-Format, damit sie später auch im Gateway nutzbar ist.
- Webseite zuerst lesen, dann nur Lücken fragen; eine Frage pro Runde; Fortschritt sichtbar; Abschluss mit
  Bestätigung.

## Entwurfsentscheidungen (meine Wahl, für den Builder verbindlich, sofern nicht als offen markiert)

**Skill-Ablage und Format.** `spaces/marketing/skills/marke-neu/SKILL.md`. Frontmatter:
`name: marke-neu`, `description: …` (≤ 100 Zeichen), `user-invocable: true`,
`metadata: {"vibemind":{"chats":["marke"],"schritte":7}}`. Darunter der Leitfaden für das Modell (Schritte, Regeln,
Antwortformat-Ergänzung). Unbekannte Frontmatter-Schlüssel ignoriert der Lader.

**Lader** (neues Modul `spaces/marketing/claw/skills.py`): findet alle `skills/*/SKILL.md`, liest das Frontmatter
(einzeilig, wie OpenClaw), bereinigt den Befehlsnamen nach OpenClaw-Regel, verweigert reservierte Namen (OpenClaw-
Liste + Telegram-Liste, als Konstante mit Quellenangabe) und Doppelungen (Test schlägt fehl, statt still `_2`),
liefert `befehle(chat) -> list[Skill]` und `aufloesen(text, chat) -> (skill, rest) | None`. `/skill <name>`
vergleicht Bindestrich, Unterstrich und Leerraum gleich. `skill.anweisung` = Text ohne Frontmatter.

**Befehl erkennen.** In der Marketing-API, `POST /api/pult/marke/chat`: beginnt die Nachricht mit `/`, wird
aufgelöst. Unbekannter Befehl → 400 mit der Liste der verfügbaren Befehle (die UI zeigt sie als Fehlermeldung).
`/marke_neu` ohne Namen → 400 „Bitte so: /marke_neu Firmenname [Webseite]“ (kein Zwischenstand nötig).
`/marke_neu` legt **keinen** normalen Marken-Auftrag für die aktuell gewählte Firma an, sondern startet die
Einrichtung (unten). Die UI schickt die Nachricht unverändert; sie zeigt unter dem Eingabefeld eine Zeile
„Befehle: /marke_neu – neue Marke einrichten“ (aus `GET /marke` → `befehle`).

**Einrichtung als Entwurfs-Mandant.** `/marke_neu Name [URL]` legt per neuer DB-Funktion
`marketing.pult_mandant_einrichten(name, von)` einen Mandanten mit `aktiv=false` und neuer Spalte
`einrichtung text` (`'laeuft'`, `'abgebrochen'`, NULL = normal) an. Die `id` wird aus dem Namen abgeleitet (Umlaute → ae/oe/ue/ss,
klein, `[^a-z0-9]` → `_`, auf die Regex gekürzt, bei Kollision `_2`, `_3`). Ohne Namen fragt der Agent zuerst danach
Namensregeln: gleicher Name (ohne Groß/Klein) wie eine **aktive** Marke → abgelehnt mit Hinweis auf den normalen
Chat; gleicher Name wie eine Einrichtung (`laeuft` oder `abgebrochen`) → diese wird fortgesetzt (`einrichtung='laeuft'`).
Damit teilen sich nie zwei Mandanten einen Ordner `companys/<Name>/` (`markenwissen.ordner_finden` sucht auch über
den Namen). `_2`-Suffix nur, wenn verschiedene Namen dieselbe id ergeben.
Die Marken-Funktionen, die heute `aktiv` verlangen – `pult_marke_anlegen`, `pult_marke_bearbeitung_anlegen`,
`pult_marke_uebernehmen` (auch der direkte Weg aus `arbeiter_vorschlag`), `pult_marke_rueckgaengig` – akzeptieren
zusätzlich `einrichtung='laeuft'`. Rückgängig setzt wie heute nur Abschnittstexte zurück; das reicht.

**Firmenwahl nur im Marken-Chat.** Das Cookie `mk_mandant` und `marketing_mandant.waehlen()` bleiben **unverändert**
(nur aktive), denn die API-/DB-Schicht für Newsletter, Vorlagen, Kampagnen und Reels prüft `aktiv` nicht – die
UI-Wahl ist dort der einzige Schutz. Die Marken-Seite bekommt eine eigene Wahl für Einrichtungen: Parameter
`?einrichtung=<id>` (nur auf `/marketing/layouts`, geprüft gegen die Liste der Mandanten mit `einrichtung='laeuft'`
aus `GET /mandanten?einrichtung=1`). Alle Formulare der Marken-Seite tragen den Parameter weiter. So kann eine
halbfertige Marke nirgends sonst gewählt werden – erstes Anti-Ziel ohne Änderungen an anderen Modulen.

**Wo das Gespräch sichtbar ist.** `POST /marke/chat` antwortet bei `/marke_neu` mit der neuen `id`; die
Sende-Route in `ui_marke.py` wertet die Antwort aus (heute ignoriert sie sie) und leitet auf
`/marketing/layouts?einrichtung=<id>&reiter=chat#ende`. Über dem Chat steht dann „<Name> – in Einrichtung“ mit Link
zurück zur bisherigen Firma; laufende Einrichtungen sind auf der Marken-Seite als kleine Liste „In Einrichtung“
erreichbar. Pro Firma höchstens eine laufende Einrichtung; eine zweite `/marke_neu` mit gleichem Namen führt
zur bestehenden zurück.

**Runde.** `marken_arbeiter._chat_mit_spur` erkennt `einrichtung='laeuft'` und hängt `skill.anweisung` an den
System-Prompt (Muster `video_claw`), dazu einen Block „Stand der Einrichtung“: je Schritt erledigt/offen, berechnet
aus dem aktuellen Profil (Marke.md) und `pflichtteil`. Websuche und gesichertes Lesen wie heute. Während der
Einrichtung gelten **alle** Profiländerungen direkt (auch Farben, Schriften, Logo, Webseite), weil die Marke noch
nirgends sichtbar ist; die Bestätigung am Ende ersetzt das einzelne „Übernehmen“.

**Pflichtteil.** Das Antwortformat des Modells bekommt in der Einrichtung zusätzlich `pflichtteil` (impressum,
abmelde_hinweis, vermittlerangaben). Geschrieben wird per neuer Funktion `pult_mandant_pflichtteil_setzen`. `vermittlerangaben` wird ab jetzt im
Newsletter-Fuß gerendert, wenn nicht leer (`bloecke_mjml.py`, `pult_render.py`, `seite_html.py`, unter dem Impressum)
– bestehende Marken haben das Feld leer, für sie ändert sich nichts. Regel im
Skill und im Code: Impressum/Vermittlerangaben nur übernehmen, wenn der Betreiber sie in der Nachricht geschrieben
hat oder sie wörtlich auf einer gelesenen Seite stehen (Code prüft: Text kommt als Teilstring in Nachricht oder
gelesenem Seitentext vor, sonst verworfen mit Hinweis). `abmelde_hinweis` muss `{abmeldelink}` enthalten.

**Abschluss.** In Schritt 7 zeigt der Agent die Zusammenfassung; die UI zeigt darunter einen Knopf
„Marke anlegen“ (nur wenn Schritt 1 und 2 erledigt sind). Der Knopf ruft `POST /api/pult/marke/einrichtung/abschliessen`
→ `pult_mandant_aktivieren` (`aktiv=true`, `einrichtung=NULL`; prüft serverseitig Name, Impressum,
Abmeldehinweis mit `{abmeldelink}`). Gespiegelt wird nicht in dieser Route (Marke.md liegt am PC): der Arbeiter spiegelt
wie heute nach jeder Übernahme, also schon während der Einrichtung (das Layout gehört der inaktiven Marke und ist
unsichtbar); der Abgleich alle 600 s erfasst sie ab der Aktivierung. Knopf „Einrichtung abbrechen“ →
`einrichtung='abgebrochen'` (kein Löschen: nach der ersten Runde hängen ohnehin Vorschläge, Spiegel, Medien daran).
Ein späteres `/marke_neu` mit demselben Namen setzt sie fort. Der Ordner `companys/<Name>/` bleibt beim Abbruch liegen (Rowboat-Wissen wird nicht
gelöscht), wird aber im Abschlussbericht genannt.

**Migration.** Eine neue Migration (nächste freie Nummer zur Bauzeit, laut WORKBOARD prüfen; 083/084 sind
vermutlich belegt, 085 ist es) mit `einrichtung`-Spalte und den drei Funktionen, dazu `verify_<nr>.sql`.
Sicherung vor dem Einspielen wie üblich.

## Leitfaden für Marketing-Skills (eigenes Dokument, Teil der Lieferung)

`spaces/marketing/skills/README.md`, kurz und praktisch:

1. Ablage und Format (OpenClaw-kompatibles Frontmatter, einzeilig; Pflicht `name`, `description`).
2. Benennung: `kebab-case`, Befehl = bereinigter Name; reservierte Namen (Liste mit Quelle); Test erzwingt
   Eindeutigkeit.
3. Einbindung in unsere Chats: `metadata.vibemind.chats` (fehlt es, gehört der Skill zu keinem Chat – so bleibt das vorhandene
`newsletter-bild` unberührt; die 100-Zeichen-Grenze der Beschreibung prüft der Test nur für Skills mit Chat), Lader-API, wo der Text in den Prompt kommt, warum (Shim
   reicht keine OpenClaw-Werkzeuge durch).
4. Einbindung ins OpenClaw-Gateway (optional): Kopie in die Workspace-Saat (`anbinden.sh`), Voraussetzung ist ein
   passendes Sidecar-Werkzeug; Hinweis auf „extra usage“ bei OpenClaw-Anfragen.
5. Regeln für Skill-Texte: eine Frage pro Runde, Fortschritt, keine erfundenen Rechts- oder Zahlenangaben, was der
   Code zusätzlich absichert.
6. Testen: Lader-Test, Prompt-Test (Skill-Text landet im System-Prompt), ein Ende-zu-Ende-Durchlauf auf der VM mit
   Wegwerf-Marke.

## Abnahme

- `/marke_neu Probe GmbH https://<echte Seite>` im Marken-Chat: Firma „Probe GmbH“ erscheint im Umschalter nur als
  „in Einrichtung“, nirgends sonst (Newsletter-Anlegen, Vorlagen, Kampagnenplan zeigen sie nicht).
- Der Agent füllt aus der Webseite vor, fragt danach eine Lücke pro Runde, zeigt den Fortschritt.
- Ein erfundenes Impressum wird nicht übernommen; ein im Chat geschriebenes schon.
- „Marke anlegen“ → Firma aktiv, im Umschalter normal, Profil-Reiter zeigt die Abschnitte, Newsletter-Vorschau zeigt
  Impressum und Abmeldehinweis, Layout trägt Farben/Logo.
- `/new`, `/neu`, `/foo` im Marken-Chat → Hinweis mit der Befehlsliste, kein Auftrag.
- `/marke_neu fin2gether` → abgelehnt; die halbfertige Probe ist im Newsletter-Editor, Plan und Reels nicht wählbar,
  auch nicht durch Setzen des Cookies von Hand.
- „Marke anlegen“ ohne Impressum ist nicht möglich (Knopf fehlt, Route lehnt ab).
- Probe-Marke danach abbrechen; Wegwerf-Mandant per SQL entfernen (nur in der Abnahme).

## Dem Builder überlassen

- Genaue Texte im Skill und in der UI (deutsch, kurz, im Ton der bestehenden Marken-Seite).
- Aufteilung in Tasks, Reihenfolge der Auslieferung (API/PC und sales-claw zusammen ausliefern, wie beim Marken-Chat).
- Ob der Fortschritt zusätzlich als kleine Leiste über dem Chat erscheint.
