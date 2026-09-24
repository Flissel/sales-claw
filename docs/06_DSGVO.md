# 06 — DSGVO-Handwerk

Stand 27.08.2026 (P2). Zwei definierte Abläufe; alles andere an
Datenschutz-Verhalten (Zustimmungs-Gate, Verschwiegenheit in Posts,
append-only-Protokoll) steht in AGENTS.md und den jeweiligen Werkzeugen.

## Auskunft (Art. 15)

Eine Person will wissen, was über sie gespeichert ist.

1. `kontakt_auskunft(lead_id)` — per Chat („erstell die Auskunft für X")
   oder durch Claude. Ergebnis: vollständiger Markdown-Export
   (Stammdaten, Anreicherung, jede Protokollzeile, jeder Entwurf) unter
   `reports/auskunft-<name>-<datum>.md`.
2. **Der Betreiber prüft und übergibt selbst** — der Export geht nie
   automatisch raus. Frist nach Art. 12: ein Monat.
3. Verlangt der Kontakt die Auskunft im Chat, sagt der Bot es dem
   Betreiber; er stellt den Export nie selbst in den Chat.

- **Terminkarten** (seit 24.09.2026) stehen in der Auskunft als Aktivität `terminkarte`
  mit Dateiname, eingesetzten Werten und Fassung der Vorlage. Die Datei selbst liegt in
  `media-erzeugt` des Ladens (Basis-Laden: `media-erzeugt/`, weitere Läden:
  `laeden-daten/<laden>/media-erzeugt/`).

## Löschbegehren (Art. 17)

Eine Person will gelöscht werden.

**Schritt 1 — sofort: `loeschantrag_vermerken(lead_id, quelle, wortlaut)`.**
Wirkung (alles getestet, tests/test_dsgvo.py):

* Kontakt wird archiviert (verschwindet aus allen Listen);
* KEINE neuen Entwürfe mehr, kein Auto-Betrieb — `antwort_entwerfen` und
  `entwurf_erstellen` verweigern mit Verweis hierher;
* kein stilles Zurückholen: `kontakt_wiederherstellen` verweigert;
* der Vermerk selbst steht als `loeschantrag`-Zeile im Protokoll.

Der Bot darf den Vermerk selbst setzen, wenn ein Kontakt die Löschung im
Chat ausdrücklich verlangt (mit Quelle und Wortlaut) — der Vermerk ist
Schutz, kein Risiko. Er informiert den Betreiber sofort.

**Schritt 2 — binnen 30 Tagen: physische Löschung, Menschen-Schritt.**
Bewusst OHNE Werkzeug: die Dienst-Rolle hat kein DELETE, und ein
Lösch-Werkzeug wäre genau der Unfall-Hebel, den es nie geben soll.
Ablauf (Vier-Augen — Betreiber plus eine zweite Person):

1. Prüfen, ob gesetzliche Aufbewahrungspflichten entgegenstehen
   (Vertragsunterlagen: §257 HGB / §147 AO — dann Einschränkung statt
   Löschung, dem Antragsteller so mitteilen).
2. Auf der Datenbank-Maschine mit der OWNER-Rolle (nicht der
   Dienst-Rolle), `<LEAD>` ersetzt:

```sql
-- activities und drafts haengen mit ON DELETE CASCADE am Kontakt:
DELETE FROM sales.leads WHERE id = '<LEAD>';
```

3. Dateien nachziehen — physisch zu löschende Stellen:
   - `reports/` und `media/` auf Dateien zu dieser Person durchsehen und
     entfernen (auch die Auskunfts-Exporte).
   - **Terminkarten-Dateien** des Kontakts: `terminkarte-<kunde>-*.pdf` in `media-erzeugt`
     des Ladens — die Namen stehen in den Aktivitäten `terminkarte` des Kontakts. Gedruckte
     Karten beim Teamleiter sind Papier und gehören in die Rückfrage an ihn.
4. Sicherungen: die rotierenden Volume-Sicherungen (7 Tage) und
   DB-Sicherungen laufen aus; bis dahin gilt die Verarbeitung als
   eingestellt (Vermerk-Vollstopp). Nicht einzeln in Archive hineinoperieren.
5. Löschprotokoll führen OHNE Personenbezug: Datum, wer (beide Namen),
   Fundstellen geprüft ja/nein. Ablage beim Betreiber, nicht im Repo.

## Werbe-Einwilligung (§ 7 UWG, seit 31.08.2026)

Neben der DSGVO (Datenverarbeitung) gilt das UWG (Ansprache): elektronische
Werbung per WhatsApp/E-Mail braucht eine Einwilligung oder die
Bestandskunden-Ausnahme des § 7 Abs. 3 UWG.

- **Das Tor sitzt im Werkzeug:** `entwurf_erstellen` lehnt Erstansprachen
  (der Kontakt hat nie selbst geschrieben) ohne `consent_status`
  `opt_in`/`existing_customer` ab. Antworten auf eingehende Nachrichten
  und LinkedIn-Beiträge aufs eigene Profil bleiben frei.
- **Erfassen ist Menschensache:** `einwilligung_erfassen(lead_id, art,
  quelle, wortlaut)` — die Quelle ist Pflicht, alles landet als
  `werbe_einwilligung` im Protokoll (activities). Der Bot ruft es nur auf
  ausdrückliche Nennung durch den Betreiber auf, nie aus eigener Deutung.
- **Widerruf:** `einwilligung_widerrufen(lead_id, grund)` wirkt sofort;
  „keine Werbung mehr" im Chat zählt als Widerruf.
- **Abgrenzung:** die Zustimmung (`zustimmung_*`) erlaubt die automatische
  Antwort, die Einwilligung (`einwilligung_*`) die werbliche Ansprache
  überhaupt. Ein Löschantrag (oben) schlägt beides: Vollstopp.

Verträge: `sales-mcp/tests/test_uwg.py`.

## Kollegen-Kalender (Team-Sicht, seit 12.09.2026)

Ein Kollege kann seinen eigenen Kalender über eine geheime iCal-Adresse mit
`sales-claw` verbinden (`/team/kalender`), damit Terminvorschläge nicht mit
ihm kollidieren — Auslöser war der ausdrückliche Betreiber-Wunsch „dass
Ivans und meiner dann berücksichtigt wird".

**Wer sieht was, auf welcher Grundlage.**

- **Was verarbeitet wird:** Titel, Ort und Zeitraum jedes Termins im
  verbundenen Kalender des Kollegen — nicht mehr, als der Kalender selbst
  hergibt. Die Adresse (das Geheimnis, das den Zugriff trägt) wird
  gespeichert (`sales.kalender_quellen.url`), aber nie angezeigt oder
  geloggt (Spec §4, technisch durchgesetzt — siehe 08_TOMS.md).
- **Wer es sieht:** der Betreiber (Rolle `lesen`/`freigeben`) über
  `/kalender` — dort mit Kundenname, Thema und Ort, denn genau das braucht
  die Kollisionsprüfung und ist die vom Betreiber gewählte Sichtbarkeits-
  stufe „Alles — Kunde, Thema, Ort" (Spec §4). Der Kollege selbst (die
  eigens dafür geschaffene, schmale Rolle `kalender`) sieht denselben
  Kalender-Abschnitt — inklusive der Termine anderer Kollegen, denn die
  Kollisionsprüfung ist eine Team-Angelegenheit —, aber ausdrücklich
  **nicht** den übrigen Kundenstamm: `/kontakte`, `/posteingang` und
  innerhalb von `/kalender` auch offene Wiedervorlagen samt Notiz sowie
  rohe, noch nicht terminierte Anfragetexte bleiben ihr verborgen (W5,
  Schlussprüfung 13.09.2026 — das sind keine Termindaten). Vertrag:
  `sales-mcp/tests/test_kalender_verbinden.py::
  test_rolle_kalender_sieht_termine_aber_keine_wiedervorlagen_oder_anfragen`.
- **Rechtsgrundlage:** das Verbinden ist eine bewusste, selbst ausgeführte
  Handlung des Kollegen (er trägt die geheime Adresse selbst ein — kein
  automatischer Zugriff auf ein fremdes Konto), zum Zweck der internen
  Terminabstimmung zwischen Kollegen desselben Betriebs. Das trägt sich auf
  ein berechtigtes betriebliches Interesse (Art. 6 Abs. 1 lit. f DSGVO) an
  kollisionsfreier Terminplanung; eine betriebliche Anweisung/Einwilligung
  im Innenverhältnis ist die sauberere Grundlage, wo eine solche ohnehin
  vorliegt (z. B. Arbeitsvertrag, Betriebsvereinbarung) — das entscheidet
  der Betreiber, siehe „Grenze" unten.
- **Widerruf:** der Kollege setzt seine Adresse beim eigenen Anbieter
  jederzeit selbst zurück — der Zugriff endet damit sofort, ohne dass
  `sales-claw` etwas tun muss (die alte Adresse wird beim nächsten Abruf
  nur noch mit Fehler quittiert). Zusätzlich kann jede Quelle über
  `/team/kalender` aktiv entfernt werden (W3) — ein Gegen-Ereignis, kein
  Hard-Delete: die Zeile bleibt bestehen, aber die Adresse wird
  gelöscht (`aktiv = false, url = null`), damit `sales_app` (ohne
  DELETE-Recht auf jeder Tabelle) konsistent bleibt.
- **Aufbewahrung:** wie beim übrigen Bestand kein automatisches Ablaufdatum
  — eine entfernte Quelle bleibt als deaktivierte Zeile stehen (Nachweis,
  dass und wann sie entfernt wurde), ohne die Adresse selbst.

## Grenze

Dieses Dokument ist Betriebsanleitung, keine Rechtsberatung. Bei
Streitfällen (Auskunftsumfang, Aufbewahrungsfristen, Reichweite der
Bestandskunden-Ausnahme) entscheidet der Betreiber mit rechtlicher
Beratung — nicht Claude, nicht der Bot.
