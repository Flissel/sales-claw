# Freie Fläche für Newsletter (Collage statt Blöcke)

Stand: 20.10.2026 · Auftraggeber: User (Betreiber) · Repos: sales-claw (Editor, Seiten, Versand) und vibemind-os `spaces/marketing` (API, Assistent, Darstellung, Datenbank)

## 1. Worum es geht und warum

Newsletter wirken heute starr und gleichförmig. Der Assistent kann nur Blöcke untereinander stapeln: Überschrift, Text, Bild, Knopf, Spalten. Der User will Newsletter, die nach **High-End-Newsletter** aussehen, mit Freiheit wie in einer Collage. Elemente sollen sich überlappen, schräg stehen und über den Rand ragen dürfen (im Brainstorming Stufe C, „Ganz frei“).

**Entscheidungen des Users:**

1. **Der Assistent gestaltet frei** auf der verfügbaren Fläche und platziert Elemente selbst.
2. **Beide Ausgaben zählen:** die verschickte Mail und das PDF.
3. **Stufe C, ganz frei:** Überlappen, Drehen und Anschnitt sind erlaubt.
4. **Der User bearbeitet auch selbst:** Elemente verschieben, drehen, skalieren und Text ändern, zusätzlich zum Chat mit dem Assistenten.
5. **Die freie Fläche ersetzt den Block-Editor für Newsletter.**
6. **Bestand:** Alte Newsletter werden nicht auf die Fläche umgezogen; wie weit sie weiter bearbeitet werden können, regelt Punkt 11. Neue entstehen nur noch auf der Fläche. Die Vorlagen baut der Assistent einmalig als Collage-Vorlagen neu.
7. **Qualität geht vor Tempo.** Es ist in Ordnung, wenn ein Entwurf ein paar Minuten länger dauert, weil der Assistent sein Werk ansieht und nachbessert.
8. **Anti-Ziel:** Ein Entwurf sieht nicht mehr nach High-End aus, oder die Kreativität leidet. Das gilt als Fehlschlag, auch wenn technisch alles funktioniert.
9. **Mail-Schrift, Mischung:** Alles in einer Markenschrift wird in der Mail zu einem Bildstück und sieht dadurch exakt aus, also Überschriften, Großschrift und Handschrift. Fließtext bleibt echter Text in einer mail-sicheren Schrift, die der Markenschrift nahekommt. Ohne Bilder bleibt die Mail lesbar. Gmail und Outlook laden keine Webschriften, deshalb ist das der Kompromiss zwischen „sieht aus wie das PDF“ und „echter Text“.
10. **Anrede und Textlinks nur in echtem Text:** `{vorname}` und Links im Fließtext dürfen nur in Bereichen stehen, die in der Mail echter Text bleiben. Darauf achten Assistent, Editor und Schönheitsprüfung. Knöpfe bleiben immer anklickbar. Es gibt keine Bilder pro Empfänger.
11. **Alte Block-Newsletter dürfen fertig werden:** Bestehende Block-Newsletter bleiben bearbeitbar, einreichbar, freigebbar und versendbar, auch mit dem Assistenten. Nur **neue** Newsletter entstehen nicht mehr als Blöcke. Der Block-Weg (MJML, Block-Werkzeuge, Freigabe) bleibt dafür im Hintergrund erhalten. Das ersetzt die frühere Fassung von Punkt 6, nach der alte Newsletter nur noch angesehen werden konnten.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**

- Ein Newsletter ist **eine Seite**: feste Breite 600, Höhe frei. Die Elemente darauf haben absolute Position, Größe, Drehung und Ebenenreihenfolge.
- Das **PDF** zeigt die Seite exakt.
- Die **Mail** zeigt sie optisch gleich. Wo es geht, bleibt Text echter Text. Überlappende oder gedrehte Bereiche werden zu Bildern.
- Der **Assistent** legt Seiten an, setzt und ändert Elemente, sieht sich das gerenderte Ergebnis an und bessert nach, bevor der User es sieht.
- Im **Editor am PC** wählt der User Elemente aus, verschiebt, dreht und skaliert sie, ändert Text und Ebenenreihenfolge und kann rückgängig machen.
- **Am Handy** gibt es Vorschau und Assistent wie seit B2 (20.10.), aber kein Schieben.
- Fassungen, Freigabe, Versand über sales-claw, Marke je Firma und der Pflicht-Fuß (Impressum, Abmelden) funktionieren weiter wie bisher.

**Nicht-Ziele**

- Kein freier Editor für LinkedIn-Posts oder andere Inhaltsarten. Nur Newsletter.
- Keine Mehrseiten-Dokumente. Ein Newsletter ist eine lange Seite, und auch das PDF bleibt eine durchgehende Seite wie heute.
- Kein Umzug der alten Block-Newsletter auf die Fläche.
- Kein Schieben am Handy.
- Keine Animationen und kein Video in der Mail.

**Anti-Ziele (ein Fehlschlag, auch wenn es läuft)**

- Entwürfe sehen billig, beliebig oder nach Spam aus.
- Alle Ausgaben haben dieselbe Komposition.
- Text ist auf Bildern unleserlich.
- Die Mail weicht sichtbar vom Entwurf ab, etwa durch andere Umbrüche oder verrutschte Elemente.
- Die Mail besteht nur aus einem einzigen großen Bild. Das schadet der Zustellbarkeit, ist ohne Bilder leer und für Screenreader stumm.

## 3. Was es schon gibt (darauf aufbauen)

In der Recherche vom 20.10. hat sich gezeigt: **Eine kleine freie Fläche existiert bereits**, als „Gestaltung“ in einem Image-Block:

- **Modell und Rechenhilfen:**
  - Modell in `editor/src/schemata.ts:118-182`, Rechenhilfen in `editor/src/gestaltung.ts`: Einrasten, Skalieren, Drehen, Rückgängig mit 100 Schritten.
  - Format quer, quadrat, hoch oder banner, Breite 600, bis 20 Ebenen.
  - Ebenenarten: `bild`, `text` (bis 200 Zeichen), `form` (Rechteck oder Kreis).
  - x und y bezeichnen den **Mittelpunkt** der Ebene.
- **Editor:** `editor/src/App/Gestaltung/` mit `Flaeche.tsx` (absolute Positionen, `translate(-50%,-50%) rotate()`, Zoom), `GestaltungFenster.tsx`, `EbenenListe.tsx`, `Eigenschaften.tsx` und `useGestaltung.ts`.
- **Assistent:** Werkzeuge in `marketing/claw/agent_werkzeuge.py`: `flaeche_anlegen`, `ebene_hinzufuegen`, `ebene_aendern`, `ebene_reihenfolge`, `ebene_loeschen`, `format_setzen`, `hintergrund_setzen`, dazu die Bildwerkzeuge.
- **Rasterung:** Pillow in `marketing/claw/gestaltung.py`. Die Textmaße nähern CSS nur an, deshalb können Editor und Ergebnis auseinanderlaufen.
- **Prüfungen** (als Hinweise in `gestaltung.bild_rechnen`): Text unter 22 Einheiten, Kontrast unter 3:1 gegen die gemessenen Pixel, mehr als 15 % außerhalb der Fläche.

Außerdem wiederverwendbar:

- **PDF:** `marketing/claw/pdf_druck.py` mit Chromium und Playwright, JavaScript aus, strenger Lade-Erlaubnisliste und einer durchgehenden Seite.
- **Bildschirmfotos:** `marketing/workers/export_worker.py` erstellt ganzseitige Aufnahmen über Playwright.
- **Versand:** `GET /api/pult/inhalte/{id}/versand`, Bilder als `cid:`-Anhänge. In sales-claw `mail_dispatch.py`: höchstens **8 MB** Bilder, sonst wird nichts verschickt.
- **Marke je Firma:** `markenprofil`, `_markenlogos`, `claw/vorlagen_marke.py`.
- **Fassungen und Freigabe:** `marketing.inhalte` / `inhalt_fassungen` mit `pult_bloecke_speichern` und `pult_einreichen` / `pult_entscheiden`. Die Fassungen sind unveränderlich.
- **Datenbank-Prüfung `pult_bloecke_fehler`:** ein CHECK-Constraint auf `inhalt_fassungen`, `newsletter_vorlagen` und `newsletter_vorlagen_fassungen`. Jede neue Form braucht eine Migration nach dem Hüllen-Muster von 060/068.

Die Arbeit ist also im Kern: **die vorhandene Fläche zur ganzen Newsletter-Seite befördern**, die Darstellung auf den Browser umstellen und Assistent, Prüfung, Mail-Übersetzung und Vorlagen darauf ausrichten.

## 4. Wie es funktionieren soll

### 4.1 Das Dokument

- Neues Inhaltsformat `seite` neben `felder` und `bloecke` in `inhalt_fassungen.format`. Alte Fassungen behalten `bloecke`.
- **Inhalt einer Seite:**
  - Breite fest 600, Höhe frei in einem festen Rahmen (Vorschlag 400–6000).
  - Hintergrund: Farbe oder Bild.
  - Ebenen: `bild`, `text`, `form`, `knopf`.
  - Jede Ebene hat Position, Größe, Drehung, Deckkraft und Reihenfolge.
- **Textebenen** brauchen mehr als heute: Fließtext, Absätze, Fettungen und Links, Markenschriften (Anzeige, Text, Hand) und eine Schriftgrößen-Stufung. Die heutige Grenze von 200 Zeichen ist für Fließtext zu klein.
- **Knopf** ist eine eigene Ebene mit Link (nur https). Er muss in der Mail anklickbar bleiben.
- **Pflicht-Fuß** (Impressum, Abmelden) ist kein Teil der Seite. Er wird bei Mail und PDF fest unten angehängt, wie heute bei MJML.
- **Platzhalter** `{vorname}` in Textebenen müssen pro Empfänger ersetzbar bleiben.
- **Grenzen:** Größe der Seite und Zahl der Ebenen werden begrenzt, wie heute 256 KB und 150 Blöcke. Die genauen Werte setzt der Builder; 20 Ebenen reichen für eine ganze Seite nicht.
- **Prüfung in der Datenbank:** neue Hüllen-Migration für `pult_bloecke_fehler` (oder eine eigene Prüffunktion für `seite`) mit erlaubten Ebenenarten und Wertebereichen, Bilder nur `medien:…`, Links nur https.

### 4.2 Eine Darstellung für alles: der Browser

Editor, PDF, Prüfbild und Mail-Bilder sollen **aus derselben HTML/CSS-Darstellung** entstehen. Das Pillow-Rastern weicht ab und kommt deshalb für Seiten nicht in Frage. Die alte Gestaltung im Image-Block darf es weiter nutzen.

- **Die Seite wird zu HTML:**
  - Absolut positionierte Elemente.
  - Webschriften aus `/marketing/schrift/`.
  - Bilder über die signierten `/marketing/bild/…`-Adressen.
  - Kein JavaScript.
- **Editor:** zeigt dieselbe Darstellung, darüber liegen die Griffe zum Bearbeiten.
- **PDF:** `pdf_druck.html_zu_pdf` mit dieser HTML, eine Seite in voller Höhe.
- **Prüfbild für den Assistenten und die Mail-Stücke:** ein Bildschirmfoto derselben Seite per Playwright.

### 4.3 Die Mail

Die Seite wird in waagrechte Streifen zerlegt:

- **Streifen, in denen nur frei stehender, ungedrehter Fließtext auf ruhigem Hintergrund liegt,** werden zu echtem Mail-Text, zum Beispiel in MJML-Sektionen mit passender Position. Dafür gilt eine mail-sichere Ersatzschrift, die zur Markenschrift passt (Entscheidung 9). Sie ist je Markenschrift festgelegt, und der Editor zeigt solche Textebenen schon in genau dieser Schrift. Damit brechen Fläche, PDF und Mail die Zeilen gleich um.
- **Streifen mit Überlappung, Drehung, Bild unter Text, Anschnitt oder Text in Markenschrift** (Überschriften, Großschrift, Handschrift) werden zu einem Bildstück aus dem Bildschirmfoto, im Format 600 breit bei 2× Dichte.
- **Anrede und Textlinks** stehen nur in Textstreifen (Entscheidung 10). Eine Textebene mit `{vorname}` oder Link darf deshalb nichts überlappen, nicht gedreht sein und keine Markenschrift tragen. Der Editor zeigt das an, der Assistent hält es ein, und die Prüfung blockiert das Einreichen bei einem Verstoß.
- **Knöpfe in Bildstreifen** bleiben anklickbar, als verlinktes Bildstück oder als Knopf, der darunter echt gesetzt ist. Der Builder entscheidet, was in Outlook und Gmail sicher funktioniert.
- **Jedes Bildstück** bekommt einen Alt-Text aus dem Text, der darin liegt.
- Der **Text-Teil der Mail** (`text_fassung`) enthält allen Text der Seite in Lesereihenfolge.
- **Die 8-MB-Grenze** muss eingehalten werden, über Kompression und Stückgröße. Liegt eine Seite darüber, sagt das die Prüfung vor dem Einreichen und nicht erst beim Versand.
- **Ziel:** Die Mail sieht wie das PDF aus, und es entsteht keine Mail, die nur aus einem einzigen großen Bild besteht.

### 4.4 Der Assistent

- **Werkzeuge** für Seiten: Seite anlegen, Höhe und Hintergrund, Ebenen hinzufügen, ändern, verschieben, drehen, löschen, Reihenfolge. Die vorhandenen Ebenen-Werkzeuge werden erweitert, keine zweite Garnitur. Bildwerkzeuge und Marke bleiben.
- **Ansehen und nachbessern:** Nach jedem Entwurf rendert der Assistent ein Prüfbild der Seite, beurteilt es wie ein Art Director und bessert in einer begrenzten Zahl Runden nach (Vorschlag: bis 3). Erst dann bekommt der User das Ergebnis.
  - Die Beurteilung braucht ein Modell, das Bilder sieht. Die Kette läuft über den Shim `:8117`, und der nimmt Bildteile (`image_url`) schon an (`marketing_shim.py`).
- **Qualitätsregeln im Prompt** statt fester Raster:
  - Schriftgrößen-Stufung, Markenfarben und Markenschriften.
  - Mindestkontrast für Text, auch gegen Bilder darunter.
  - Ruhezonen an den Rändern.
  - Höchstens ein oder zwei laute Elemente (Sticker, gedrehte Großschrift) pro Ausgabe.
  - Klarer Blickverlauf: Aufmacher, Inhalt, Knopf.
- **Abwechslung:** Der Assistent sieht die Kompositionen der letzten Ausgaben derselben Firma in Kurzform und wiederholt sie nicht.
- **Prompt-Länge:** Der Test erzwingt heute 13 000 Zeichen (`claw/tests/test_agent_prompt.py`). Wenn die neuen Regeln das sprengen, wird der Test bewusst angepasst und begründet.

### 4.5 Die Schönheitsprüfung

`schoenheit.py` lernt Seiten:

- Kontrast von Text gegen die tatsächlich gerenderten Pixel darunter (aus dem Prüfbild).
- Mindestgrößen für Schrift.
- Ein Knopf ist vorhanden und anklickbar.
- Begrenzter Anschnitt bei Textebenen.
- Mail-Größe unter 8 MB.
- Text, der zu Bildstücken würde und deshalb in der Mail nicht als Text lesbar ist, wird gemeldet.

Überlappen ist erlaubt, unleserlicher Text nicht. Vorschlag: Unleserlicher Text und ein zu großes Mailgewicht blockieren das **Einreichen**. Alles andere bleibt ein Hinweis.

### 4.6 Der Editor am PC

- Der Block-Editor verschwindet für **neue** Newsletter. Die Fläche wird zur Hauptansicht.
- **Bearbeiten:** Auswählen, Verschieben, Drehen und Skalieren mit Griffen, Einrasten an Rändern und Mitten, Text direkt auf der Fläche bearbeiten, Ebenenliste, Eigenschaften, Rückgängig. Dafür werden `Flaeche.tsx`, `EbenenListe.tsx`, `Eigenschaften.tsx` und `gestaltung.ts` ausgebaut.
- Die **Seitenhöhe** ist ziehbar.
- **Chat, Speichern mit Fassungen, Einreichen und Export** (PDF, Vorschau) bleiben an ihrem Platz.
- **Alte Block-Newsletter** öffnen weiter im Block-Editor und lassen sich fertig machen und verschicken (Entscheidung 11). Neu anlegen lassen sich nur noch Collagen. Ein Knopf „Als neue Collage beginnen“ ist erlaubt, zieht aber keine Inhalte um.

### 4.7 Am Handy

Wie seit B2: Vorschau und Assistent. Die Vorschau zeigt die Seite verkleinert auf Handy-Breite, oder die Mail-Fassung, wie sie auf dem Handy ankommt. Der Builder wählt das Gleichwertige. Ein schmaler Bildschirm darf kein eigenes Layout bekommen, das der Assistent nicht gesehen hat.

**Offen für den Builder:** Wie sieht die Mail auf schmalen Handy-Displays aus? Eine 600 breite Collage wird dort skaliert, und kleiner Text wird dabei kleiner. Die Qualitätsregeln brauchen deshalb Mindestgrößen, die bei etwa 375 px Breite noch lesbar sind.

### 4.8 Vorlagen

Aktiv sind 8 Vorlagen (`newsletter_vorlagen`, Firma vibemind, freigegeben). Dazu kommen 5 zurückgezogene und im Repo 7 JSON-Dateien unter `marketing/vorlagen/newsletter/`.

- Der Assistent baut einmalig **8 Collage-Vorlagen** mit unterschiedlichen Kompositionen.
- Sie werden in der Galerie `/marketing/vorlagen` gezeigt und beim Anlegen mit der Marke der Firma gefüllt, wie heute über `_vorlage_fuellen`.
- Die alten Block-Vorlagen werden zurückgezogen, nicht gelöscht.
- **Meine Entscheidung (Claude):** Jede Collage-Vorlage geht über den normalen Freigabeweg der Vorlagen (`newsletter_vorlagen_fassungen`), und der User gibt sie frei. Beim Füllen mit der Marke einer anderen Firma wird die Seite neu gerendert und durch die Schönheitsprüfung geschickt. Bricht dabei etwas, etwa Text, der überläuft, oder zu wenig Kontrast, passt der Assistent die Ebenen beim Anlegen an, bevor der User den Entwurf sieht. Wertetausch in `_vorlage_fuellen` allein reicht nicht.

## 5. Randbedingungen

- **Repos und Branches:** sales-claw auf `feat/stufe-1-fundament`, vibemind-os auf `master`. Claude-Code-Sessions committen direkt, aber in eigenen Worktrees unter `C:/Users/User/ClaudeWork/`.
- **Koordination:** WORKBOARD-Claim vor Beginn. Eine andere Session arbeitet parallel am Plan `design-s3-s4` (Tasks 3, 5, 8).
- **Datenbank:** Migrationen nach dem Muster von 075/076: idempotent, eine Transaktion, `verify_NNN.sql` über `migration_probe` gegen die echte Datenbank mit ROLLBACK. Einspielen nur mit User-OK.
- **Livegang** (VM `update.sh`, `marketing-aktualisieren.sh`) nur mit User-OK.
- **Sicherheit:** Die Seiten-HTML läuft im PDF-Chromium mit JavaScript aus und der bestehenden Lade-Erlaubnisliste. Keine fremden Hosts, keine freien Style-Attribute aus Nutzertext ins Mail-HTML. Die Werte der Ebenen werden geprüft und erst daraus wird CSS gebaut.
- **Sales-UI** ohne JavaScript. Der Editor ist die React-App unter CSP `CSP_EDITOR`.
- **Keine Modelle auf der VM.** Der Assistent und die Bilderzeugung laufen weiter auf dem PC.
- **Bilder:** Erzeugte Bildstücke für die Mail müssen bis zum Versand erhalten bleiben. Die heutige Müllabfuhr löscht nach 7 Tagen unreferenzierte `gs-…`-Bilder.

## 6. Was der Builder entscheidet

- Ebenen- und Seitenmodell im Detail (Feldnamen, Grenzen), solange 4.1 erfüllt ist.
- Wie genau Streifen zerlegt und Knöpfe in Bildstreifen umgesetzt werden (4.3), mit einem Nachweis an Outlook und Gmail (Litmus-artig oder echte Testmails).
- Wie Ansehen und Nachbessern technisch läuft (4.4), einschließlich der Zahl der Runden und des Modells.
- Ob die Seite eine neue Spalte oder ein neues `format` in `inhalt_fassungen` bekommt, und wie die Datenbank-Prüfung erweitert wird.
- Reihenfolge der Lieferung. Vorschlag in Stufen, jede für sich nutzbar:
  1. Seitenmodell, Browser-Darstellung, PDF.
  2. Editor am PC.
  3. Assistent mit Ansehen und Nachbessern.
  4. Mail-Übersetzung und Versand.
  5. Schönheitsprüfung und Vorlagen, danach kein Neuanlegen von Block-Newslettern mehr. Der Block-Weg bleibt für bestehende Newsletter erhalten (Entscheidung 11).

## 7. Woran man Erfolg erkennt

- Drei Newsletter, die der Assistent auf der Fläche gestaltet hat, sehen nach High-End aus und unterscheiden sich in der Komposition deutlich. Das Urteil liegt beim User.
- PDF und Mail derselben Fassung sehen gleich aus: echte Testmail in Gmail und Outlook gegen das PDF. Einzige erlaubte Abweichung: die festgelegte Ersatzschrift im Fließtext, die schon der Editor zeigt.
- In der Mail bleibt der Großteil des Texts echter Text. Mit abgeschalteten Bildern bleibt die Botschaft verständlich.
- Der User kann ein Element in unter 10 Sekunden verschieben, drehen und den Text ändern, und das Ergebnis erscheint exakt so in PDF und Mail.
- Alte Newsletter lassen sich weiter ansehen und als PDF holen.
