# Suche über Kontakte und Gesprächsverlauf — gemessen, bevor gebaut wird

**Stand 17.09.2026. Ergebnis vorweg: die naheliegende Lösung ist die falsche.**

Auslöser war eine einfache Frage des Betreibers — „gibt es zwei Ivans, führ sie
zusammen" — die mit den heutigen Mitteln nur durch geratene `ILIKE`-Muster zu
beantworten war. Daraus wurde der Wunsch nach semantischer Suche, zuerst mit
Qdrant, dann mit einer lokalen supermemory-Variante.

Dieses Dokument hält fest, was **gemessen** wurde, nicht was plausibel klingt.

---

## 1. Was nicht gebaut werden sollte, und warum

### 1.1 Kein zweiter Speicher

**Qdrant** läuft ausschließlich auf dem Windows-Rechner — und dort **doppelt**:
`:6333` und `:6730` antworten beide mit HTTP 200. Das ist der bekannte
Volume-Konflikt. Die Kontakte liegen auf der VM. Qdrant zu benutzen hieße, 549
Kundendatensätze über das Netz in einen zweiten, doppelt laufenden Speicher zu
schieben.

**supermemory** (MIT, `npx supermemory local`, lokale Einbettungen ohne
API-Schlüssel) ist deutlich näher dran und ließe sich auf der VM betreiben — die
Daten blieben also, wo sie hingehören. Zwei Einwände bleiben:

* Es ist trotzdem ein **zweiter Speicher mit Abgleich**. Der Brücken-Audit dieses
  Hauses hält fest, dass genau die Brücken teuer sind, die Inhalt bewegen.
* Sein Standardmodell ist `Xenova/bge-base-**en**-v1.5` — **englisch**, während
  Kontakte und rund 3000 Aktivitätstexte deutsch sind.

**`pgvector` 0.8.0 liegt bereits in derselben Datenbank.** `sales.personas.embedding
vector(1536)` ist im Schema deklariert und wird von **keinem** Codepfad gefüllt —
die Fähigkeit ist da und nie verdrahtet worden.

### 1.2 Und vorerst auch keine Einbettungen

Zwei mehrsprachige Modelle, jeweils gegen **200 echte** Aktivitätstexte
(`kundenantwort` + `nachricht_ausgehend`, 40–300 Zeichen), CPU auf der VM:

| Frage | MiniLM-L12 (384d) | mpnet-base (768d) |
|---|---|---|
| Finanzen, Vorsorge, Versicherung | **0.527 / Median 0.062** — alle Treffer echt | **0.589 / 0.117** — gut |
| Termin vereinbaren | 0.617 / 0.318 — ein Fehltreffer | **0.659 / 0.329** — bester Treffer korrekt |
| Telefonnummer gewechselt | 0.585 / 0.169 — **falsch** | 0.491 / 0.173 — **falsch** |
| Absage, kein Interesse | 0.552 / 0.267 — **falsch** | 0.486 / 0.201 — **falsch** |

Kosten: 149 ms/Text (MiniLM, 0,22 GB) gegen 512 ms/Text (mpnet, 1,0 GB).

**Der Befund ist über beide Modelle hinweg derselbe: Einbettungen fassen THEMEN,
aber keine EREIGNISSE und keine VERNEINUNG.**

* „wer hatte mit Versicherungen zu tun" — sauber getrennt, Bestwert weit über dem
  Median, alle drei Treffer inhaltlich richtig.
* „wer hat die Nummer gewechselt" — die Treffer lauten „Bin in der Arbeit, kann
  gerade nicht telefonieren" und „hast du eine Mail mit deiner Mitarbeiternummer
  erhalten". Das Modell trifft das Thema *Telefon*, nicht das Ereignis *Wechsel*.
* „Absage, kein Interesse" — bester Treffer bei beiden Modellen: „Ich ignorier
  dich ned". Das ist das Gegenteil der Frage. Die Verneinung geht verloren.

Das grössere Modell behebt genau **eine** der beiden schwachen Fragen und kostet
dafür das 3,4-fache. Es behebt nicht die zwei, die der Betreiber heute
tatsächlich gestellt hat.

**Ein Dienst, der auf die gestellte Frage drei falsche Treffer mit
selbstbewussten Zahlen liefert, ist schlechter als kein Dienst.** Dieses Haus hat
am selben Tag zweimal Zeit an stille Fehlfunktionen verloren (eine Prüfung, die
nur auf dem Entwicklungsrechner grün war; eine Mailroute, die nie senden konnte).
Eine dritte dieser Sorte wird hier nicht gebaut.

---

## 2. Was gebaut werden sollte

### 2.1 `pg_trgm` — sofort, und es hat sich schon bewährt

Installiert am 17.09.2026 (Version 1.6). Noch ohne Index, nur als Messung — und
es fand in einem Durchgang drei Dinge, die `ILIKE` nie findet:

* **Echte Dubletten:** „Webdesigner München" ↔ „Webdesign München" (0.81);
  „DataGuard – Datenschutz & Informationssicherheit" ↔ „DATENSCHUTZ UND
  INFORMATIONSSICHERHEIT" (0.76); „Betreiber Selbsttest" ↔ „Betreiber Selbsttest
  E-Mail" (0.75).
* **Eine Auffaelligkeit, die sich beim Nachpruefen aufloeste** (Korrektur
  17.09.2026, noch am selben Tag): dieselbe Nummer steht zweimal in
  verschiedener Schreibweise — `+491749708452` und `+49 174 9708452`. Daraus
  wurde hier zunaechst geschlossen, die Dublettenbremse vergleiche exakt.
  **Das war falsch.** `_lead_mit_gleicher_nummer` filtert per
  `regexp_replace(phone,'[^0-9]','','g')` ueber die letzten acht Ziffern vor und
  entscheidet dann mit `normalisiere_empfaenger` auf BEIDEN Seiten — genau
  dieser Fall wird erkannt. Die Dedup-Kante kam am 18.08.2026 (`b1a538c`), und
  alle vier fraglichen Zeilen sind vom 18.08.2026 und heissen „Betreiber
  Selbsttest", „Anna Beispiel", „Lisa Probekunde": **Testdaten aus dem Tag, an
  dem die Bremse gebaut wurde**, kein laufender Fehler.

  Die Lehre gehoert trotzdem hierher: ein Trigramm-Fund ist ein HINWEIS, kein
  Befund. Er sagt „diese beiden sehen sich aehnlich", nicht „hier ist ein
  Fehler". Wer ihn ohne Gegenprobe gegen den Code weiterreicht, meldet
  Fehlalarme — was hier zwischen dem ersten Entwurf dieses Dokuments und seiner
  Korrektur genau passiert ist.
* **Eine belastbare Negativaussage:** `similarity(name,'Ivan') > 0.3` liefert
  genau einen Treffer mit Ähnlichkeit 1.00. Varianten wie „Iwan" oder „Ivan G."
  hätte es gefunden. **Es gibt keinen zweiten Ivan** — das ist jetzt gemessen,
  nicht vermutet.

Zu bauen: GIN-Index auf `leads.name` und auf der ziffernnormalisierten Form von
`leads.phone`, dazu ein Werkzeug `kontakt_aehnlich(text)` für den Agenten.

### 2.2 Deutsche Volltextsuche — fast umsonst, aber mit bekannten Grenzen

`to_tsvector('german', …)` braucht nur eine generierte Spalte und einen
GIN-Index. Richtig für „welches Gespräch erwähnte X". **Zwei gemessene Grenzen,
die dokumentiert gehören, statt später zu überraschen:**

* Der deutsche Stemmer trennt Substantiv und Verb: die Suche nach „Nummer
  gewechselt" findet den Satz „Falscher Ivan hat Nummer **Wechsel** gehabt"
  **nicht** (0 Treffer).
* Verneinung wird ignoriert: „kein Interesse" liefert lauter *Interessenten*.

### 2.3 Einbettungen — später, und nur für Themenfragen

Wenn die beabsichtigten Fragen Themenfragen sind („wer hatte mit Vorsorge zu
tun"), dann **reicht MiniLM-L12** (0,22 GB, 149 ms/Text) — mpnet kostet das
3,4-fache ohne Gewinn bei den schweren Fällen. Form: Einbetter als Container auf
der VM (dort überlebt er einen Neustart, anders als die `Start-Process`-Kinder
auf Windows), Vektoren in `pgvector`, kein zweiter Speicher.

**Tor davor:** erst eine Liste echter Fragen vom Betreiber, dann gegen dieselben
200 Texte messen. Erst wenn die Trennung dort so sauber ist wie bei
„Versicherung", lohnt der Dienst.

---

## 3. Reihenfolge

1. `pg_trgm` + Indizes + `kontakt_aehnlich` — löst das heutige Problem.
2. ~~Nummern normalisiert speichern~~ — **entfaellt**, siehe die Korrektur in
   2.1: die Normalisierung findet bereits am Tor statt. Die vier auffaelligen
   Zeilen sind Testdaten vom 18.08.2026 und koennen archiviert werden, wenn der
   Betreiber es will; das ist Datenpflege, keine Codeaenderung.
3. Deutsche Volltextsuche mit den zwei dokumentierten Grenzen.
4. Einbettungen nur nach dem Tor aus 2.3.

**Die Messungen sind wiederholbar:** `/tmp/probe.py` auf `offload-vm`, Container
`python:3.12-slim` mit `fastembed` und `psycopg`, Modellname in einer Zeile
austauschbar. Kundendaten verlassen die VM dabei nicht.
