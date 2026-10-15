# LinkedIn-Post-Ablauf: Fragebogen, Markier-Liste, Meldung nach dem Posten

Stand: 15.10.2026 · Status: vom Betreiber im Chat freigegeben (Entwurf), Spec zur Durchsicht

## 1. Anlass

Am 14.10.2026 entstand der Hackathon-Post im Chat mit dem Agenten. Drei Dinge liefen schief:

1. **Sprache.** Der Betreiber hat den Post auf LinkedIn deutsch gesehen. Gesendet wurde
   nachweislich der englische Text (Entwurf `f012dd6b`, Versand-Log `sales-linkedin`
   00:48, kein Bearbeiten danach). Wahrscheinlich hat LinkedIn den Post übersetzt angezeigt.
   Prüfen ließ sich das nicht mehr, denn der Post ist gelöscht und unser Zugang darf
   veröffentlichte Posts nicht zurücklesen (403). Folge für den Ablauf: Die Sprache wird
   ausdrücklich abgefragt, und vor dem Entwurf zeigt der Agent den Endtext wortgleich.
2. **Personen-Markierungen** gingen nicht. Der Agent konnte keine Profile suchen, und echte
   @-Markierungen sind über die API nicht möglich (siehe §5).
3. **Kein geführter Ablauf.** Text, Namen und Bild kamen über mehrere Runden zusammen.
   Der Betreiber nannte sich dabei selbst als einen der „vier anderen Builder“.

## 2. Ziel

Ein Ablauf, der bei jedem LinkedIn-Anliegen anspringt, den Betreiber strukturiert abfragt
und daraus einen freigabefertigen Post baut. Markierungen von Personen und Firmen setzt der
Betreiber nach dem Posten von Hand. Das System liefert ihm dafür Link und Liste per WhatsApp,
ohne dass er nachfragen muss.

Erfolg heißt:
- Ein Post entsteht mit höchstens zwei Antworten des Betreibers: Fragebogen und Ok zur Vorschau.
- Die Sprache steht vor dem Schreiben fest, die Vorschau zeigt den Endtext wortgleich.
- Höchstens zwei Minuten nach der Veröffentlichung hat der Betreiber Link und Markier-Liste im Chat.

## 3. Entscheidungen des Betreibers (15.10.2026)

| Frage | Entscheidung |
|---|---|
| Wie kommen @-Namen in den Post? | Nachträglich: veröffentlichen über die API, danach Link und Liste per WhatsApp, Markieren von Hand in der App |
| Was wird abgefragt? | Anlass & Kernbotschaft · Sprache & Ton · Personen & Firmen · Bild/Video & Links |
| Wie wird abgefragt? | Ein Fragebogen in einer Nachricht, Nachfragen nur zu Lücken |
| Firmen über die API markieren? | Nein, unser Zugang darf keine Firmen-IDs nachschlagen (403), und eine geratene ID kann die falsche Firma verlinken. Firmen kommen wie Personen auf die Liste. |

## 4. Bausteine

### 4.1 Skill `linkedin-post` (überarbeitet, `config/workspace/skills/linkedin-post/SKILL.md`)

**Auslöser (Beschreibung):** Jeder Wunsch nach einem LinkedIn-Beitrag, ob neu, überarbeitet,
„mach daraus einen Post“, mit Bild oder mit fremdem Text als Vorlage. LinkedIn-Direktnachrichten
an Personen sind kein Auslöser, die bleiben bei `entwurf_erstellen(kanal='linkedin')`.

**Schritt 0 – Einsammeln.** Ein Bild im Chat (`[media attached: …]`) wird per
`medien_aus_chat_uebernehmen` in die Medien gelegt. Mitgeschickter Text und Links gelten als
Material.

**Schritt 1 – Fragebogen (eine Nachricht).** Vier nummerierte Punkte. Was schon bekannt ist,
steht vorausgefüllt mit „(erkannt: …)“ da:
1. Anlass & Kernbotschaft: worum es geht, was der Leser mitnehmen soll
2. Sprache & Ton: Deutsch/Englisch, persönlich/sachlich. **Pflicht und immer ausdrücklich
   zu bestätigen**, auch wenn das Material eine Sprache nahelegt.
3. Personen & Firmen zum Markieren
4. Bild/Video, Links, Hashtags

Nachgefragt wird nur, was fehlt oder widersprüchlich ist. Geschrieben wird nicht, solange
Punkt 2 offen ist.

**Schritt 2 – Markier-Liste klären.** Personen sucht er per `web_search`, nach der Regel in
AGENTS.md (nur Personen, die der Betreiber für seinen eigenen Beitrag nennt). Bei mehreren
Treffern zeigt er die Kandidaten, der Betreiber wählt. Firmen kommen mit Namen auf die Liste,
eine Firmenseite nur, wenn die Suche sie eindeutig liefert. **Der Betreiber selbst steht nie
auf der Liste** und erscheint im Text nie als „einer der anderen“.

**Schritt 3 – Schreiben.** Das bisherige Handwerk bleibt (Historie lesen, Leser vor Produkt,
drei Einstiege, keine verbrauchten Bausteine, höchstens 3000 Zeichen), jetzt in der Sprache aus
Punkt 2. Namen stehen im Text als Klartext, an der Stelle, an der der Betreiber sie später
markiert.

**Schritt 4 – Vorschau.** Eine Nachricht mit dem Endtext wortgleich (wie er an LinkedIn
geht), der Sprache, dem Medium und der Markier-Liste. Erst auf das Ok des Betreibers folgen
`post_entwurf_erstellen` bzw. `entwurf_bearbeiten` und `post_markierungen_setzen`.
Freigabe und Versand bleiben unverändert beim Betreiber.

### 4.2 Werkzeug `post_markierungen_setzen(draft_id, eintraege)` (sales-mcp, Agent-Werkzeug)

- `eintraege`: Liste aus `{name, art: "person"|"firma", profil: "<https-URL>"|""}`, höchstens 20.
  Der Name ist Pflicht, 1–120 Zeichen. `profil` muss leer sein oder auf
  `https://www.linkedin.com/` bzw. `https://linkedin.com/` zeigen.
- Nur für LinkedIn-**Beiträge** (`channel='linkedin'`, `recipient='eigenes-profil'`) im Status
  `pending` oder `approved`.
- Speichert die Liste als Aktivität `linkedin_markierungen`, Nutzlast `{draft_id, eintraege}`.
  Es gilt die jüngste Buchung, eine leere Liste löscht. Am Schema ändert sich nichts.
- Gibt `{draft_id, anzahl}` zurück, sonst `{fehler}`.
- In Kundenchats verboten, wie alle Werkzeuge rund um Beiträge (Liste in AGENTS.md).

### 4.3 Freigabe-Seite

Bei einem LinkedIn-Beitrag mit Markier-Liste zeigt die Karte unter dem Text „Nach dem Posten
markieren: …“ mit den Namen und Profil-Links. Die Seite bleibt nur lesend, Bearbeiten gibt es
weiter nur im Chat.

### 4.4 Meldung nach dem Posten (Wirt, ohne KI)

- Neues Skript `deploy/linkedin-nachlauf.sh`, gestartet von einem systemd-Timer
  `sales-linkedin-nachlauf.timer` alle 2 Minuten, nur für den Basis-Laden (Ivan veröffentlicht
  keine Beiträge).
- Ablauf:
  1. Per `docker exec sales-mcp python -m linkedin_nachlauf` die `versand`-Aktivitäten mit
     `kanal='linkedin'` aus den letzten 24 h lesen, zu denen es noch keine Aktivität
     `linkedin_nachlauf_gemeldet` mit derselben `draft_id` gibt.
  2. Je Treffer den Meldetext bauen:
     „LinkedIn-Post ist online: https://www.linkedin.com/feed/update/<urn>/“, dazu, falls
     vorhanden, „Jetzt in der App markieren (Bearbeiten → @Name): …“ mit einer Zeile je
     Eintrag (Name · Person/Firma · Profil).
  3. Senden per `docker exec sales-claw openclaw message send --channel whatsapp --target
     <Betreiber> -m <text>`. Der Text wird als Argument übergeben, ohne Shell-Interpolation
     (über ein Array).
  4. Erst nach erfolgreichem Senden `linkedin_nachlauf_gemeldet` buchen. Scheitert das Senden,
     bleibt der Treffer offen und wird beim nächsten Lauf erneut versucht, höchstens 24 h lang.
- Die Betreiber-Nummer kommt aus `SALES_BETREIBER_WHATSAPP` in der `.env` der VM (heute
  +491749708452, dieselbe wie bei `cron-saat.sh`). Fehlt sie, bricht das Skript laut ab, ohne
  etwas zu buchen.
- Der Dienst `sales-linkedin` bleibt ohne WhatsApp-Zugang, die Vertrauensgrenze ändert sich
  nicht.

### 4.5 AGENTS.md

- Kurzer Verweis: „LinkedIn-Beitrag → Skill linkedin-post.“
- `post_markierungen_setzen` in die Werkzeugliste und in die Verbotsliste für Kundenchats.
- Die bestehende Websuche-Regel (14.10.) bleibt, wie sie ist.

## 5. Was bewusst nicht gebaut wird

- **Echte @-Markierungen über die API.** Für fremde Personen gibt LinkedIn einer Profil-App
  keine Personen-ID heraus. Firmen-IDs könnten wir nur mit einer Berechtigung nachschlagen, die
  unser Zugang nicht hat (gemessen 15.10.: `organizations`-Finder/GET/Lookup alle 403).
- **Browser-Automatik** auf linkedin.com: verstößt gegen die Nutzungsbedingungen, Risiko für
  das Konto.
- **Drittanbieter** für ID-Nachschlagen (Ordinal o. ä.).
- **Zurücklesen** veröffentlichter Posts (keine Berechtigung). Die Sprachfrage wird vorher
  gesichert, nicht nachher geprüft.

## 6. Fehlerfälle

| Fall | Verhalten |
|---|---|
| Betreiber beantwortet den Fragebogen unvollständig | Eine Nachfrage nur zu den fehlenden Punkten, Sprache zuerst |
| Websuche findet niemanden oder bleibt mehrdeutig | Name ohne Profil-Link auf die Liste, der Betreiber markiert in der App per Namenssuche |
| Websuche nicht verfügbar | Wie oben, und der Agent sagt, dass er nicht suchen konnte |
| `post_markierungen_setzen` für Direktnachricht, gesendeten oder fremden Entwurf | `{fehler}`, nichts gebucht |
| Versand scheitert | Kein `versand`-Eintrag, also keine Meldung. Fehlerweg wie bisher (`linkedin_versand_ergebnis`) |
| WhatsApp-Senden im Nachlauf scheitert | Nicht als gemeldet gebucht, neuer Versuch alle 2 Min, nach 24 h aufgegeben (Log-Zeile) |
| Gateway-Container läuft nicht | Wie oben |
| Post wird nach Meldung gelöscht | Nichts zu tun |

## 7. Tests

- sales-mcp (pytest, Test-DB): `post_markierungen_setzen` mit Gültigkeitsregeln, Status- und
  Kanalgrenzen, „jüngste gilt“ und Löschen per leerer Liste. Dazu `linkedin_nachlauf`:
  offene Treffer, Text mit und ohne Liste, kein Doppelmelden, 24-h-Grenze.
- Werkzeug-Registry: `post_markierungen_setzen` registriert. Drift-Test AGENTS.md ↔ Werkzeuge
  bleibt grün.
- Freigabe-Seite: Karte zeigt die Liste, alles escaped.
- `deploy/linkedin-nachlauf.sh`: Shell-Test mit gefälschtem `docker`. Prüft, dass erst nach
  erfolgreichem Senden gebucht wird, dass die Argumente als Array übergeben werden und dass das
  Skript ohne Nummer abbricht.
- Skill: Text-Test, dass Fragebogen-Punkte, Sprach-Pflicht, Vorschau-Schritt und die
  Selbst-Regel im SKILL.md stehen.
- Live nach Deploy: Ein Post wird mit dem Betreiber zusammen veröffentlicht, nur auf seinen
  Wunsch, dann wird die Meldung geprüft. Ohne echten Post: Probelauf von
  `linkedin-nachlauf.sh --trocken` gegen den gelöschten Hackathon-Post. Der zeigt den Text,
  sendet nichts und bucht nichts.
