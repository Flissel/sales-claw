# Getrennte Läden mit geteiltem Kalender

**Datum:** 2026-09-16
**Status:** Design. Abschnittsweise vom Betreiber freigegeben (16.09.2026).
**Ersetzt:** `2026-09-11-mehrere-instanzen-design.md` — dessen drei offene Entscheidungen
(eine Datenbank oder mehrere · Ressourcen · wer darf was sehen) sind hier beantwortet.
Der dortige Befund zu Namen, Volumes und Ports gilt unverändert und steht in §1.3.
**Baut auf:** `2026-09-11-team-terminabstimmung-design.md` — die Kalender-Föderation ist
seit dem 15.09.2026 gebaut und trägt hier den ganzen Kalenderteil.

**Der Satz des Betreibers, aus dem alles folgt (16.09.2026):**

> Wir teilen uns nicht die Kontakte, wir wollen jeder einen eigenen Bot. Die Bots sollen
> bloß auf die Kalenderdaten Zugriff haben, so dass eine Terminabstimmung unter uns zwei,
> später unter x, reibungslos funktioniert. Der Bot soll das machen, indem er beide
> anschaut und einen Termin vorschlägt.

---

## 1. Ausgangslage, gemessen

Am 16.09.2026 an der laufenden Anlage auf `vibemind-offload-1` gemessen.

### 1.1 Was die Anwendung schon kann

| Befund | Wert | Folge |
|---|---|---|
| Schema-Parameter | `SCHEMA = os.environ.get("SALES_DB_SCHEMA", "sales")` (`server.py:81`) | Getrennte Läden sind **Konfiguration, kein Umbau** |
| Beweis dafür | die Suite fährt täglich 1738 Tests gegen `sales_test` | der Weg ist begangen, nicht theoretisch |
| Schema-Wache | ein `SystemExit` in `server.py` lässt nur `sales`/`sales_test` zu | eine Liste, die erweitert wird — bewusst eng gehalten |
| Sperrliste | `compliance` liegt **außerhalb** des Instanz-Schemas (`sperrliste.py`) | **Glücksfall:** wer Werbung widerspricht, hat allen widersprochen |
| Kalender-Föderation | `belegungen()` liefert `titel`, `ort`, `quelle`; eine stumme Quelle gilt **nicht** als frei | trägt den ganzen geteilten Kalenderteil |
| Medien-Schalter | `medien_meta.bot_darf_senden` je Datei | der neue Teilen-Schalter bekommt dort sein Zuhause |
| Ergebnisse | zeigt bereits `won`/`lost` samt Begründung | die „abgegrasten Kontakte" gibt es schon |

### 1.2 Was fehlt

| Befund | Folge |
|---|---|
| **Keine Tabelle kennt einen Eigentümer** — weder `leads`, `drafts`, `activities`, `medien_meta` noch `personas` | eine Eigentümer-Spalte wäre nachzurüsten *und* in ~82 Werkzeugen zu beachten; getrennte Schemata umgehen das |
| Kein Werkzeug „freie Zeiten finden" — `termin_konflikte` **prüft** nur eine vorgeschlagene Zeit | der Bot rät heute und fragt nach; bei zwei Kalendern wird das Raten teuer |
| Ein WhatsApp-Agent (`agents/main`), ein Telegram-Token, eine Absenderadresse `felix@vibemind.space` | Einbetreiber-Software |

### 1.3 Der gefährlichste Punkt

Vier Volumes sind **wörtlich** benannt, das Compose-Präfix ist ausdrücklich unterdrückt:
`sales-claw-state`, `sales-claw-keys`, `sales-sprachnachrichten`, `sales-stt-modelle`.

In `sales-claw-state` liegt die WhatsApp-Anmeldung. **Zwei Läden, die sich dieses Volume
teilen, greifen auf dieselbe Sitzung zu.** Das ist kein Schönheitsfehler, sondern der
Unterschied zwischen zwei Bots und einem Bot mit zwei Gesichtern.

Ebenso fest: Projektname `sales-claw`, neun Containernamen, Port `127.0.0.1:18894`.

Die Containerliste des älteren Papiers ist überholt: `sales-auto` gibt es nicht mehr,
dafür `sales-telegram`. Heute laufen `sales-ui`, `sales-mcp`, `sales-dispatch`,
`sales-inbox`, `sales-mail`, `sales-linkedin`, `sales-telegram`, `sales-stt`, `sales-claw`.

### 1.4 Die Maschine

23 GiB Speicher, davon 11 GiB frei. Der ganze sales-Satz braucht **1,65 GiB** —
`sales-claw` 670 MB, `sales-stt` 496 MB, die sieben Python-Dienste zusammen rund 487 MB.
Platte: 81 GB, davon 23 GB frei.

---

## 2. Was gebaut wird

### 2.1 Drei Schemata, davon eines ohne Tabellen

| Schema | Inhalt |
|---|---|
| `sales` | der Laden des Betreibers — unverändert |
| `sales_ivan` | Ivans Laden — dieselben Tabellen, eigene Zeilen |
| `sales_geteilt` | **nur Sichten, keine Tabellen** |
| `compliance` | bleibt gemeinsam, wie schon heute |

**Die Termine brauchen davon nichts.** Jeder abonniert die geheime iCal-Adresse des
anderen; `belegungen()` liefert Titel, Ort und Quelle — also „Termin mit Claudia,
14:00–14:30, Quelle: Ivan". Das läuft seit dem 15.09.2026.

**Ins geteilte Schema kommen genau zwei Sichten:**

1. `firmen_in_arbeit` — vereinigt beide `leads`-Tabellen und zeigt **eine Spalte**: den
   Firmennamen nicht abgeschlossener Kontakte, dazu wessen Laden. Keine Personen, keine
   Adressen, keine Notizen, keine Bewertungen.
2. `medien_geteilt` — die Dateien, bei denen der neue Schalter gesetzt ist. Der Schalter
   selbst ist eine **neue Spalte `kollegen_sehen` in der `medien_meta` jedes Ladens**; die
   Sicht vereinigt nur, was dort auf `true` steht. So bleibt die Entscheidung dort, wo die
   Datei liegt, und das geteilte Schema bleibt schreibfrei.

**Warum Sichten und keine Kopien:** Sichten sind immer aktuell und können nichts vergessen
abzugleichen. Sie werden einmal bei der Einrichtung als `supabase_admin` angelegt — genau
wie `kalender_quellen` am 15.09.2026, nachdem `provision.sql` mit der Laufzeit-Kennung an
`permission denied for schema sales` gescheitert war.

### 2.2 Zwei Datenbankbenutzer — die Trennung gehört in die Datenbank

Beide Läden würden sonst als derselbe Benutzer `sales_app` verbinden; dann trennt sie nur
eine Umgebungsvariable, und wer an Ivans Container kommt, kommt an fremde Kontakte.

Stattdessen `sales_app_felix` und `sales_app_ivan`, jeder berechtigt auf **sein** Schema,
auf `compliance` und lesend auf `sales_geteilt`. Kein DDL, kein DELETE — wie bisher.

Die Folge ist der Kern dieses Entwurfs: **Ein Programmfehler führt zu „keine Daten", nicht
zu „fremde Daten".** Auch eine Anweisung, die jemand dem Bot über WhatsApp unterschiebt,
kann nichts Fremdes lesen — die Datenbank verweigert es, nicht der Code.

### 2.3 Die Oberfläche

```
AUFGABEN
  Heute                  privat
  Heute (Team)           GETEILT   <- neu
  Freigaben              privat
  Wiedervorlagen         privat
  Einordnung             privat
  Kalender               GETEILT   (gebaut)
  Kalender verbinden     eigen     (gebaut) — hier abonniert jeder die
                                   Kalender der anderen; die Liste der
                                   Quellen ist die eigene

ANALYSE
  Kontakte               privat
  Pipeline               privat
  Ergebnisse             privat
                         <- Posteingang entfaellt

DATEN
  Medien                 privat, je Datei teilbar

MONITORING
  WhatsApp               privat
```

Die Seite **„Heute (Team)" gibt es in jeder Oberfläche**; sie liest die Termine aus dem
eigenen `belegungen()` und die Firmen aus `sales_geteilt.firmen_in_arbeit`. Sie zeigt zwei
Dinge und sonst nichts:

1. **Die Termine beider, mit Titel und Quelle** — „14:00–14:30 Termin mit Claudia · Ivan".
   Aus der Föderation.
2. **Firmen, an denen beide arbeiten** — als Warnung, nicht als Liste:
   „⚠ Acme AG bearbeitet ihr beide."

Kennzahlen („12 offene Kontakte") **nicht**. Der Betreiber hat sie nicht verlangt, und jede
Zahl ist eine Stelle, an der später jemand mehr sehen will.

**Der Posteingang entfällt für beide** (Betreiber-Entscheid 16.09.2026, nach Vorlage der
Gegenrede). Die Folge, damit sie gesagt ist: Unbeantwortete Eingänge sieht danach niemand
mehr in der Oberfläche, nur noch direkt im WhatsApp am Handy. Der Direktaufruf von
`/posteingang` muss sauber enden, nicht in einem Fehler 500.

**Medien: zwei unabhängige Schalter je Datei.**

| Schalter | Bedeutung | Zustand |
|---|---|---|
| `kollegen_sehen` | sehen die anderen die Datei | **neu**, Vorgabe `false` |
| `bot_darf_senden` | darf der Bot sie an Kunden schicken | unverändert, hängt am Einwilligungs-Tor |

Sie bleiben getrennt: Man kann Werbung teilen, die der Kollege sieht, sein Bot aber nicht
verschickt — und umgekehrt. `bot_darf_senden` mit „Sichtbarkeit" zu überladen wäre ein
Rückschritt an einer Stelle, die Rechtsfolgen trägt.

**Bei neuen Medien wird unter *Freigaben* gefragt, Vorgabe nein — aber nur bei bewusst
hochgeladenen Dateien** (`herkunft = 'hochgeladen'`). Was aus dem Chat kommt, bleibt stumm
privat und ist auf der Medien-Seite jederzeit teilbar. Sonst ersäuft die Freigabeliste an
jedem Bild, das jemand per WhatsApp schickt.

### 2.4 Ein Bot je Mensch, vier eigene Kanäle

| Kanal | Was anzulegen ist |
|---|---|
| WhatsApp | eigenes Pairing mit eigener Nummer, **eigenes `state`-Volume** (§1.3) |
| Mail | Postfach `ivan@vibemind.space` beim Anbieter |
| Telegram | eigener Bot-Token beim BotFather |
| LinkedIn | eigener Zugang |

**WhatsApp bekommt einen eigenen Gateway-Container** (`ivan-claw`, eigener
Zustandsordner), nicht einen zweiten Agenten im bestehenden Gateway. openclaw hat zwar
eine `agents`-Zuordnung, aber: ein Absturz risse sonst beide Bots mit, und die Frage „kann
ein Gateway je Agent auf einen anderen MCP-Server zeigen?" müsste erst gemessen werden,
bevor man sich darauf verlässt. Der eigene Container stellt sie nicht.

**Wie der Bot beide Kalender sieht: gar nicht über die Datenbank.** Ivans Bot fragt
`belegungen()` in *seinem* Laden, und dessen Quellenliste enthält das abonnierte iCal des
anderen. Kein einziger Zugriff auf ein fremdes Schema.

### 2.5 Das fehlende Werkzeug: `freie_zeiten`

```
freie_zeiten(von: str, bis: str, dauer_minuten: int) -> str
```

Rechnet aus `belegungen()` die Lücken **aller** Quellen aus und gibt die ersten paar
Vorschläge zurück. Antwortet eine Quelle nicht, nennt die Antwort den Vorbehalt —
dieselbe Regel wie bei `termin_konflikte`: eine unbekannte Belegung ist keine freie Zeit.

Ohne dieses Werkzeug rät der Bot und fragt nach; mit zwei Kalendern wird das Raten teuer.

### 2.6 Betrieb

**Zehn Container je Mensch**, bei Ivan als `ivan-mcp`, `ivan-ui`, `ivan-mail`,
`ivan-dispatch`, `ivan-inbox`, `ivan-linkedin`, `ivan-telegram`, `ivan-stt`, `ivan-claw`
und `ivan-openwa`.

*(Korrektur vom 16.09.2026, beim Schreiben des Plans gefunden: `openwa` — die
WhatsApp-Schnittstelle auf Port 12785 — liegt in `docker-compose.openwa.yml`, einer
zweiten Datei mit demselben Projektnamen, und gehört zum Laden. Ein elfter Dienst,
`sales-auto`, steht in der Compose-Datei, wird aber bewusst nie gestartet.)*

**Der Instanzname wird zum Parameter**: Projektname, Containernamen, Volumes und Port
leiten sich daraus ab. Ein Laden ohne Namen bleibt `sales-claw` — die bestehende
Installation ändert sich nicht.

**Speicher:** ein zweiter Satz kostet rund 1,65 GiB; 11 GiB sind frei. Ivan und ein Dritter
passen bequem, ab etwa dem fünften Menschen ist der Speicher die Grenze.
`sales-stt-modelle` (300 MB Download) ist ein Kandidat zum **Teilen** statt zum
Vervielfachen — Modelle sind keine Daten.

**Zugang: jeder eine eigene Adresse.**

```
443   -> Oberflaeche des Betreibers   (nur er)
8444  -> Ivans Oberflaeche            (nur er)
```

Die Tailscale-Regel für Ivan wechselt von `tcp:443` auf `tcp:8444`. **Er kann die fremde
Oberfläche danach nicht mehr erreichen** — nicht „darf nicht", sondern „kommt nicht hin".
Die schmale Rolle `kalender` vom 15.09.2026 wird damit überflüssig; sie bleibt bestehen,
trägt aber nichts mehr.

**Update und Sicherung** erfassen alle Läden in einem Lauf. Eine Wiederherstellung stellt
**einen** davon wieder her, ohne die anderen anzufassen.

---

## 3. Entscheidungen und warum

| Frage | Entscheidung | Warum |
|---|---|---|
| Ein Laden mit Mandanten oder getrennte Schemata? | **Getrennte Schemata** | Bei Mandanten hinge die Privatheit daran, in rund 82 Werkzeugen und 30 Seiten **kein einziges Mal** den Mandanten zu vergessen. Am Bot gibt es zudem keinen „angemeldeten Benutzer", nur eine Nummer. |
| Gleiche VM oder eigene? | **Gleiche VM** | Eine eigene wäre maximal getrennt, aber doppelte Betriebslast (Updates, Secrets, Sicherung, Tailscale, Zertifikate), und das Geteilte bräuchte eine Netzschnittstelle statt einer Sicht. |
| Ein Datenbankbenutzer oder zwei? | **Zwei** | Sonst trennt eine Umgebungsvariable statt der Datenbank. |
| Was zeigt „Heute (Team)"? | **Termine mit Namen, dazu die Firmenwarnung** | Betreiber: „nur Firmenkontakte sollen geshared werden, Termine sollen mit Namen sichtbar sein". |
| Teilen-Schalter und `bot_darf_senden`? | **Zwei unabhängige Schalter** | `bot_darf_senden` hängt am Einwilligungs-Tor; Überladen wäre ein Rückschritt. |
| Vier Kanäle oder nur WhatsApp? | **Alle vier eigen** | Betreiber-Entscheid 16.09.2026. |
| Posteingang? | **Raus** | Betreiber-Entscheid, nach Vorlage der Gegenrede (19 unbeantwortete Eingänge). |

---

## 4. Nicht im Umfang

* **Mandantenfähigkeit in der Anwendung** — ausdrücklich verworfen, s. §3.
* **Verteilung auf mehrere Wirte** — erst wenn eine VM nicht mehr reicht.
* **Gemeinsame Kontakte oder gemeinsame Pipeline** — ausdrücklich nicht gewollt.
* **Eine ladenübergreifende Anmeldung** — jeder meldet sich an seiner eigenen Oberfläche
  an; mit getrennten Ports gibt es nichts zu überbrücken.
* **Die DSN-Umstellung auf den Docker-Netznamen** (`supabase-db:5432` statt der
  LAN-Adresse des Wirts). Eigene Aufgabe, s. WORKBOARD-Claim `cc-vm-lan-abschottung`
  vom 16.09.2026.

---

## 5. Prüfung

**Am laufenden System gemessen, nicht am Code behauptet.** Diese Woche hat viermal dasselbe
gezeigt — der `:ro`-Mount, das `\r\r\n` in der versendeten Datei, das fehlende GRANT, der
CHECK innerhalb eines `create table if not exists`: **die getestete Umgebung ist nicht die
ausgelieferte.** Jedes Mal war der Code richtig und die Suite grün.

Zu **jedem** Tor gehört die Frage: *welche kaputte Fassung fängt diese Prüfung?* Diese
Woche waren fünfzehn Tests grün, die auch ohne die Änderung grün gewesen wären, die sie
beweisen sollten.

1. **Die Trennung hält — an der Datenbank, nicht am Code.** Mit Ivans Zugangsdaten
   `select * from sales.leads`. Erwartet: *permission denied*. Nicht „leeres Ergebnis" —
   verweigert. Das ist der Unterschied zwischen einer Regel und einem Riegel.
2. **Ivan erreicht die fremde Oberfläche nicht.** Portsonde von seinem Gerät auf 443: kein
   Verbindungsaufbau. Dieselbe Messung, mit der am 16.09.2026 das Heimnetz geschlossen
   wurde.
3. **Termine überqueren die Grenze, in beide Richtungen.** Ein Termin des einen erscheint
   in der Team-Sicht des anderen mit Titel und Quelle — und umgekehrt. Beide Richtungen,
   weil eine schiefgehen kann, ohne dass die andere es merkt.
4. **Der Bot findet eine Zeit, statt zu raten.** `freie_zeiten` schlägt vor; eine Zeit, die
   nur bei einem von beiden frei ist, darf nicht vorkommen.
5. **Eine stumme Quelle ist nicht „frei".** Ein iCal abschalten, dann vorschlagen lassen.
   Der Vorschlag muss den Vorbehalt nennen. Schweigt er, ist das Tor gerissen.
6. **Die Firmen-Warnung warnt, und nur dann.** Dieselbe Firma in beiden Läden → Warnung.
   Verschiedene Firmen → **keine** Warnung. Ohne die zweite Hälfte prüft der Test nichts.
7. **Medien, alle vier Kombinationen.** Geteilt/nicht geteilt × Bot darf senden/darf nicht.
   Sonst merkt niemand, wenn die zwei Schalter aneinander hängen.
8. **Die Kanäle sind wirklich getrennt.** Eine Mail aus Ivans Laden trägt
   `ivan@vibemind.space` als Absender — **am echten Postfach nachgesehen, nicht im Log.**
9. **Der Posteingang ist weg** — in beiden Oberflächen, und der Direktaufruf endet sauber.
10. **Getrennte WhatsApp-Anmeldungen.** Ein erneutes Pairing des einen lässt den anderen
    unberührt. Dieses Tor prüft §1.3.
11. **Die gemeinsame Sperrliste wirkt in beiden Läden.** Eine Sperre in `compliance` hält
    auch den zweiten Bot auf.
12. **Ein Update erfasst beide Läden**, ohne dass jemand Befehle je Person wiederholt.
13. **Die Sicherung enthält beide**, und eine Wiederherstellung stellt **einen** wieder her,
    ohne den anderen anzufassen.

---

## 6. Checkliste: ein dritter Mensch später

Damit es beim dritten Mal nicht wieder erforscht werden muss:

1. Schema `sales_<name>` anlegen — als `supabase_admin`, nicht mit der Laufzeit-Kennung.
2. Datenbankbenutzer `sales_app_<name>` anlegen; Rechte auf das eigene Schema, auf
   `compliance` und lesend auf `sales_geteilt`. Kein DDL, kein DELETE.
3. *(Entfällt seit dem Plan vom 16.09.2026: die Schema-Wache in `server.py` prüft nach
   dem Muster `sales(_[a-z][a-z0-9_]{0,30})?` statt gegen eine Liste. Ein neuer Laden
   braucht dort keine Änderung mehr.)*
4. Die beiden Sichten in `sales_geteilt` um den neuen Laden erweitern.
5. Zehn Container mit dem Instanznamen, **eigene Volumes** (§1.3), `sales-stt-modelle`
   geteilt.
6. Vier Kanäle: WhatsApp-Pairing, Postfach, Telegram-Token, LinkedIn-Zugang.
7. Einen Serve-Port vergeben und in Tailscale eine Regel `<person> -> tcp:<port>`.
8. Die Kalender gegenseitig abonnieren — geheime iCal-Adresse, §2.1.
9. Die dreizehn Tore aus §5 durchgehen.

---

## 7. Reihenfolge der Umsetzung: zwei Pläne, nicht einer

Dieser Entwurf ist **ein** Design, aber für **einen** Umsetzungsplan zu groß. Er zerfällt an
einer natürlichen Naht in zwei Teile, die jeder für sich lauffähige Software ergeben.

**Plan 1 — Der zweite Laden steht und ist getrennt.**
Schemata, zwei Datenbankbenutzer, Schema-Wache, Instanzname als Parameter, eigene Volumes,
neun Container, Serve-Port, Tailscale-Regel, die vier Kanäle.
*Tore 1, 2, 8, 10, 11, 12, 13.*
Danach arbeitet Ivan eigenständig — nur ohne geteilte Sicht.

**Plan 2 — Die geteilte Sicht.**
`sales_geteilt` mit beiden Sichten, „Heute (Team)", die Firmenwarnung, der Medien-Schalter
samt Freigabe-Abfrage, `freie_zeiten`, Posteingang raus.
*Tore 3, 4, 5, 6, 7, 9.*

**Warum diese Naht und keine andere:** Plan 1 ist reine Trennung — er kann nichts
verschlimmern, was heute funktioniert, weil er den bestehenden Laden nicht anfasst.
Plan 2 baut Brücken über eine Grenze, die es vorher gar nicht gab. Wer beides in einem Zug
macht, kann bei einem Fehler nicht unterscheiden, ob die Trennung oder die Brücke schuld
ist.

**Vorbedingung für beides — noch offen (Stand 16.09.2026):** Die Kalender-Föderation ist
gebaut, aber **nie mit einem echten zweiten Kalender gelaufen**. Der Torschritt aus
`2026-09-11-team-terminabstimmung-design.md` §6.1 steht aus. Plan 2 ruht vollständig auf
dieser Föderation; sie vorher zu beweisen kostet einen Handgriff und erspart womöglich
einen ganzen Plan.
