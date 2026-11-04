# Post-Sammelstelle: Einordnung v2 – feiner, verlässlich, mit Prüfer

Stand 04.11.2026. Baut auf `2026-10-30-post-sammelstelle-design.md` (Stufe 1, LIVE seit 03.11.) auf.
Was hier nicht geändert wird, gilt dort weiter (Sichtbarkeit, Sensibel-Regeln, Tresor, Abholdienst).

## 1. Warum

Felix hat am 04.11. die ersten 400 einsortierten Mails des Hauptpostfachs (vibemind.space, Firmenpostfach)
angesehen. Das Ergebnis passt nicht:

- Unter **Privat** liegen Social-Media-Mitteilungen (TikTok, Instagram, Bluesky, Mastodon), Login-Codes von
  GitHub/Vercel/Anthropic und Newsletter – alles Firmenkonten. Echte private Mails bekommt Felix praktisch nicht.
- Ursache 1 (Aufbau): „Soziale Netzwerke“ gibt es nur unter Privat; die festen Sensibel-Muster legen jede
  Treffer-Mail fest nach `privat / Konten & Sicherheit`.
- Ursache 2 (Modell ohne Kontext): Der Sortierer kennt weder Postfach noch Firma noch die Bedeutung der Fächer –
  nur ihre Namen.
- Ursache 3 (Streuung): Derselbe Absender landet in mehreren Fächern (Notion in 4, Luma in 4, Tailscale in 2).

Felix' Worte: „gut granular aufteilen … Social Media aufgeteilt zwischen Insta, LinkedIn und so weiter“ und
„ich mag nicht, dass da irgendwo was falsch läuft“ – mit einem „kleinen Review-Agent, der das wirklich anhand
dieser Struktur einordnet“.

## 2. Ziele

1. **Privat eng:** Nur was Felix persönlich betrifft (Familie & Freunde, eigene Käufe, eigene Rechnungen,
   Behörden & Versicherung, Gesundheit). Newsletter, Abos, Plattform-Mitteilungen, Cookie-/Datenschutz-Hinweise
   sind nicht privat. Im Firmenpostfach gilt: **im Zweifel Business**.
2. **Granular:** Unterfächer – Social Media je Plattform, Tools & Dienste je Anbieter, Konten & Sicherheit je Anbieter.
3. **Stabil:** Ein bekannter Absender landet immer im selben Fach (fester Absender-Katalog vor dem Modell).
4. **Geprüft:** Jede Modell-Einordnung prüft ein zweiter Agent (Prüfer). Sind beide uneins, landet die Mail in
   **„Zum Nachsehen“** mit beiden Vorschlägen; Felix übernimmt einen mit einem Klick.
5. **Lernend:** Jede Korrektur von Hand wird standardmäßig zur festen Absender-Regel.
6. **Altbestand neu:** Alle bisherigen Mails werden nach v2 neu einsortiert.

## 3. Nicht-Ziele / Anti-Ziele

- Kein Verschieben/Archivieren im echten Postfach (bleibt Stufe 2).
- Keine frei erfundenen Fächer oder Unterfächer durch ein Modell – die Liste bleibt fest, das Modell wählt nur.
- **Anti-Ziel:** Sensible Inhalte (Codes, Rücksetzlinks) werden für mehr Leute sichtbar als heute. Die Umstellung
  „sensibel nicht mehr fest privat“ darf Login-Codes nicht an Abteilungen oder den Bot geben (s. §6).
- **Anti-Ziel:** Ein Mensch-Entscheid wird von der Neu-Sortierung überschrieben.

## 4. Neue Fachstruktur

Drei Ebenen: **Bereich → Fach → Unterfach** (Unterfach optional, nur wo unten genannt).

**business**
| Fach | Was hinein gehört | Unterfächer |
|---|---|---|
| Kunden & Anfragen | Anfragen, Angebote, laufende Kundengespräche | – |
| Partner & Netzwerk | Kooperationen, Förderer, Hochschulen, persönliche Kontakte aus dem Netzwerk | – |
| Veranstaltungen | Einladungen, Anmeldungen, Tickets, Event-Plattformen (Luma, Easyfairs, Meetups) | – |
| Rechnungen | Rechnungen, Zahlungen, Quittungen der Firma | – |
| Tools & Dienste | Mitteilungen von Software/Diensten, die die Firma nutzt (auch deren Werbung) | je Anbieter aus dem Katalog, sonst „Sonstige“ |
| Soziale Netzwerke | Mitteilungen der Firmenkanäle | Instagram, LinkedIn, TikTok, YouTube, Facebook & Meta, X, Bluesky, Mastodon, Threads, Sonstige |
| Konten & Sicherheit | Login-/Bestätigungscodes, Passwort, Sicherheitswarnungen, Kontoänderungen | je Anbieter aus dem Katalog, sonst „Sonstige“ |
| Bewerbungen & Jobs | Bewerbungen an die Firma, Jobplattformen | – |
| Newsletter & Branche | Fach-Newsletter, Branchennews, Substack | – |
| Werbung | unaufgeforderte Verkaufsmails, Cold Outreach | – |
| Zum Nachsehen | Sortierer und Prüfer uneins oder beide unsicher | – |

**privat**
| Fach | Unterfächer |
|---|---|
| Familie & Freunde | – |
| Käufe & Bestellungen | – |
| Rechnungen | – |
| Behörden & Versicherung | – |
| Gesundheit | – |
| Abos & Newsletter | – |
| Soziale Netzwerke | wie business |
| Konten & Sicherheit | wie business |
| Werbung | – |
| Zum Nachsehen | – |

„Unklar“ entfällt und wird zu „Zum Nachsehen“ (bestehende Zeilen werden umbenannt).

Jedes Fach bekommt im Code eine **Beschreibung** (die Spalte „Was hinein gehört“ bzw. sinngemäß für privat);
sie steht im Auftrag von Sortierer und Prüfer.

Abteilungen (Spec Stufe 1 §7) neu: Veranstaltungen → Marketing, Soziale Netzwerke → Marketing.
**Konten & Sicherheit gehört keiner Abteilung** (sieht nur Besitzer + Leitung, s. §6).

## 5. Ablauf der Einordnung

Reihenfolge je Mail (erste Stufe, die greift, entscheidet Bereich/Fach/Unterfach):

1. **Feste Sensibel-Muster** (wie heute, Liste bleibt): `sensibel = true`, Fach `Konten & Sicherheit`, Bereich =
   **Standardbereich des Kontos** (statt fest privat), Unterfach aus dem Absender-Katalog (sonst „Sonstige“).
   Kein Modell.
2. **Nutzerregeln** (`post_regeln`, neueste zuerst, besitzergebunden – R11/R13 bleiben): setzen Bereich, Fach,
   Unterfach. Über `sensibel` entscheidet weiter das Modell (R18).
3. **Absender-Katalog** (neu, fest im Code, Datei `post_katalog.py`): Domain-Endung → (Fach, Unterfach).
   Bereich = Standardbereich des Kontos. Beispiele: `instagram.com` → Soziale Netzwerke/Instagram,
   `linkedin.com` → Soziale Netzwerke/LinkedIn, `tiktok.com`, `youtube.com`, `facebookmail.com`/`meta.com`,
   `x.com`/`twitter.com`, `bsky.social`, `mastodon.social`, `threads.net`; `github.com` → Tools & Dienste/GitHub,
   ebenso Notion (`notion.so`, `notion.com`, `makenotion.com`), Vercel, OpenRouter, Tailscale, Anthropic, OpenAI,
   Namecheap, Hashnode, dev.to, Spotify for Creators, Cal.com, Calendly; `luma-mail.com`/`luma.com`,
   `easyfairs.com`/`.de` → Veranstaltungen; `substack.com` → Newsletter & Branche;
   `teamtailor-mail.com` → Bewerbungen & Jobs.
   Sensibel entscheidet wie bei 2 das Modell; bei sensibel=true wird das Fach auf `Konten & Sicherheit` mit
   demselben Unterfach umgelenkt (Codes von Instagram landen also unter Konten & Sicherheit / Instagram).
   Der Katalog wird mit den echten Absendern des Altbestands gefüllt (Abfrage je Domain, s. §9).
4. **Sortierer** (Modell, Agent `post`, ohne Werkzeuge, wie heute) mit neuem Auftrag:
   - Kontext: Postfach-Kennung + Standardbereich, Inhaber (Felix, Gründer von VibeMind, einem KI-Startup), dass die
     Social-Media-Konten Firmenkanäle sind, die Regel „Privat nur, wenn es Felix persönlich betrifft; im
     Firmenpostfach im Zweifel Business“.
   - Fächer mit Beschreibung und Unterfächern; Auswahl nur per Enum wie heute.
   - Rückgabe: bereich, fach, unterfach (oder leer), sensibel, sicher (bool), begruendung.
5. **Prüfer** (neu, Agent `post-pruefer`, ohne Werkzeuge, anderes Modell als der Sortierer): bekommt dieselbe Mail,
   dieselbe Fachliste und die Einordnung des Sortierers. Antwort: `bestaetigt` oder eigene Einordnung (gleiches
   Schema). Prüfer-Auftrag: „prüfe gegen die Beschreibungen; im Zweifel bestätige nicht“.
   - Einig (gleicher Bereich, Fach, Unterfach) und der Sortierer war `sicher` → fertig.
   - Sonst → Bereich = **privat** (fail closed: nur Besitzer sieht es), Fach `Zum Nachsehen`, beide Vorschläge
     gespeichert. `sensibel` = ODER beider Urteile.
   - Prüfer läuft **nur nach Stufe 4**, nicht nach Regel- oder Katalog-Treffern.
   - **Prüfer scheitert** (Gateway-Fehler) **oder die Tagesgrenze ist zwischen Sortierer und Prüfer erreicht:**
     Die Mail bleibt `neu`. Beim nächsten Lauf laufen beide Aufrufe neu; Fehlversuche zählen wie heute (R8).
     Nach 3 Fehlversuchen kommt die Mail nach `privat / Zum Nachsehen`, nur mit dem Sortierer-Vorschlag, falls
     einer vorliegt. Sie wird nie ungeprüft übernommen. Einen Zwischenzustand ohne Bereich gibt es nur als `neu`.
   - **Modell sagt sensibel (Stufe 4):** Das Fach wird nicht umgelenkt, ein Kontoauszug bleibt also z. B. unter
     Rechnungen. Den Schutz übernimmt die Markierung (§6). Bei Uneinigkeit kommt auch eine sensible Mail nach
     Zum Nachsehen (privat).

**Fach passt nicht zum Bereich** (Katalog oder Regel nennt ein Fach, das es im Standardbereich des Kontos nicht
gibt, z. B. Notion-Mail im privaten GMX-Konto): Fächer, die es nur unter business gibt (Tools & Dienste,
Veranstaltungen, Bewerbungen & Jobs, Newsletter & Branche, Kunden & Anfragen, Partner & Netzwerk), ziehen den
Bereich auf **business**, denn Firmenwerkzeuge sind Firmensache. Fächer in beiden Bereichen (Soziale Netzwerke,
Konten & Sicherheit, Rechnungen, Werbung) übernehmen den Standardbereich des Kontos. Das prüft ein Test je Fall.

**Nutzerregel vor Katalog:** Eine Entscheidung von Felix schlägt den festen Katalog, so wie heute neueste Regel
vor älterer.

Der Prüfer braucht einen eigenen Agenten in `config/openclaw.json` mit `tools deny *` und festem Modell
(`anthropic/claude-sonnet-5-5`, `fallbacks: []`). Achtung (bekannte Falle): ein im Gateway unbekannter Agentenname
bekommt **alle** Werkzeuge – die ID steht als Konstante im Code, ein Test prüft die Konfiguration.

Tagesgrenze (500 Modellaufrufe) zählt Sortierer- und Prüferaufrufe einzeln.

## 6. Sichtbarkeit (Änderung)

Bisher lagen alle sensiblen Mails unter privat, damit sah sie nur der Besitzer. Jetzt können sie unter business
liegen. Darum:

- `sichtbar_sql`: Eine sensible Mail sieht der Besitzer. Die Leitung sieht sie nur, wenn sie unter
  **business** liegt. Abteilungen sehen sie nie. Sensible Privat-Mails anderer Besitzer sieht die Leitung nicht.
  Privat bleibt also wie heute: nur der Besitzer. Der Bot sieht weiterhin nie sensible Mails (unverändert).
- `Konten & Sicherheit` hängt an keiner Abteilung (doppelte Absicherung).
- `Zum Nachsehen` liegt immer unter privat → nur der Besitzer.
- Tests: Abteilungsmitglied sieht eine sensible business-Mail **nicht**; Leitung und Besitzer sehen nur den Kopf
  (Text bleibt in SQL geleert wie heute).

## 7. Datenmodell (Migration in `db/post-sammelstelle.sql`, idempotent wie bisher)

- `post_konten.standard_bereich text not null default 'business' check in ('privat','business')`.
  Hauptpostfach = business. Im Formular `/post/konten` wählt man ihn beim Anlegen (GMX privat/business).
- `post_mails.unterfach text`, `post_mails.vorschlaege jsonb` (bei „Zum Nachsehen“: Sortierer- und
  Prüfer-Einordnung, ohne Freitext bei sensiblen Mails), `einordnung_quelle` erweitert um `'katalog'` und
  `'pruefer'` (einig geprüft).
- `post_regeln.unterfach text`.
- Umbenennung: `fach = 'Unklar'` → `'Zum Nachsehen'` in `post_mails`, `post_regeln`. Bestehende Zeilen mit
  `bereich = 'business'` und Unklar ziehen dabei nach **privat**, denn Zum Nachsehen ist immer privat. Die
  Neu-Sortierung in §9 ordnet sie ohnehin neu ein.
- Bestehende Konten: Live gibt es am 04.11. nur das Hauptpostfach (`haupt`, Namecheap, vibemind.space), und
  dafür ist der Default `business` richtig. GMX- und Gmail-Konten kommen erst danach über das Formular hinzu,
  mit gewähltem Standardbereich.
- `post_abteilung_faecher`: neue Zuordnungen (Veranstaltungen, Soziale Netzwerke → Marketing).

Produktions-Einspielung nur mit Felix' OK (wie bei Stufe 1).

## 8. Oberfläche (`/post`)

- Navigation: Bereich → Fach (mit Zähler) → Unterfächer aufklappbar (mit Zähler).
- „Zum Nachsehen“: je Mail beide Vorschläge als Knöpfe („Sortierer: …“, „Prüfer: …“) plus die normale
  Korrektur. Ein Klick übernimmt den Vorschlag (Quelle `mensch`).
- Korrektur einer Mail: Unterfach-Auswahl dazu; Haken **„für diesen Absender immer so“ standardmäßig an**
  (abwählbar). Regel = Absenderadresse (wie heute, keine ganze Domain), besitzergebunden. Gleiche Adresse →
  die alte Regel wird ersetzt, nicht verdoppelt. Für ganze Domains ist der Katalog da.
- Ein-Klick-Übernahme aus Zum Nachsehen legt ebenfalls diese Regel an. Der Klick zeigt dieselbe Haken-Option
  (an), z. B. als zwei Knöpfe je Vorschlag oder als Haken über den Knöpfen; das UI-Detail entscheidet der Bauende.
- `/post/konten`: Auswahl „Standardbereich“ beim Anlegen.

## 9. Neu-Sortierung des Altbestands

- Skript `deploy/post-neu-einordnen.sh` (ruft ein Python-Modul im sales-post-Container):
  - `--probe`: ordnet alle eingeordneten Mails neu ein **ohne zu speichern** und gibt nur Zahlen aus
    (alt → neu je Fach, Anzahl Zum Nachsehen, Anzahl Modellaufrufe). Keine Betreffs, keine Inhalte.
  - ohne `--probe`: schreibt. Mails mit `einordnung_quelle = 'mensch'` werden **nie** angefasst.
  - Arbeitet aus der Datenbank (Text liegt vor; sensible Mails nur mit Kopf), kein IMAP.
  - Hält die Tagesgrenze ein und setzt beim nächsten Lauf fort.
- Vor dem Schreiben: Katalog-Abdeckung prüfen (Anteil Katalog-Treffer) und Probe-Zahlen Felix zeigen.
- **Katalog-Einträge:** Der Bauende entwirft sie aus den Absender-Domains des Altbestands (Fach + Unterfach je
  Domain). Die Liste geht als Tabelle zusammen mit den Probe-Zahlen an Felix, **bevor** geschrieben wird. Seine
  Änderungen fließen in den Katalog ein. Das ist der eine Warte-Schritt im Plan.

## 10. Abnahme

- Probe-Zahlen: Privat im Hauptpostfach nahe 0; keine Social-Media-/Tool-Absender mehr unter Privat; jeder
  Katalog-Absender in genau einem Fach.
- Felix sieht im Reiter Mails die neue Struktur und macht eine Stichprobe (20 Mails). Fehlgriffe werden Regeln.
- Tests: Katalog (Domain-Endung, Subdomains, kein Treffer auf ähnliche Fremddomains wie `instagram.com.evil.io`),
  Prüfer einig/uneinig/Fehler, Sensibel-Umlenkung, Sichtbarkeit §6, Migration zweimal einspielbar,
  Neu-Sortierung lässt `mensch` unberührt, Prüfer-Agent-Konfiguration ohne Werkzeuge.

## 11. Entscheidungen, die ich (Claude) getroffen habe – bitte prüfen

- Uneinigkeit → „Zum Nachsehen“ statt „Prüfer hat das letzte Wort“.
- „Unklar“ geht in „Zum Nachsehen“ auf.
- Neues Fach **Veranstaltungen** (viele Luma-/Easyfairs-Mails) und **Gesundheit** unter privat.
- Werbung eines bekannten Tools (z. B. Notion) landet bei Tools & Dienste / Notion, nicht unter Werbung –
  Stabilität „ein Absender, ein Ort“ geht vor.
- Prüfer = anderes Modell (Sonnet 5.5) als der Sortierer (Haiku 5.5), damit es eine echte zweite Meinung ist.
- Sensible Mails: Besitzer immer, Leitung nur unter business, Abteilungen und Bot nie.
- Firmen-Fächer (Tools, Veranstaltungen, Jobs, Branche, Kunden, Partner) ziehen eine Mail auf business, auch
  wenn sie in einem privaten Konto ankommt.
- Prüfer scheitert → später neu versuchen, nach 3 Fehlversuchen nach Zum Nachsehen; nie ungeprüft übernehmen.
- Eigene Absender-Regel schlägt den Katalog.
- Ich entwerfe den Katalog, du bestätigst ihn zusammen mit den Probe-Zahlen.

## 12. Dem Bauenden überlassen

Genaue Prompt-Formulierungen, Aufteilung in Module, wie der Katalog Domain-Endungen abgleicht (muss
Subdomains erkennen, Fremddomains nicht), UI-Details der Unterfach-Navigation, Reihenfolge der Tasks.
