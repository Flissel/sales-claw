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

3. Dateien nachziehen: `reports/` und `media/` auf Dateien zu dieser
   Person durchsehen und entfernen (auch die Auskunfts-Exporte).
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

## Grenze

Dieses Dokument ist Betriebsanleitung, keine Rechtsberatung. Bei
Streitfällen (Auskunftsumfang, Aufbewahrungsfristen, Reichweite der
Bestandskunden-Ausnahme) entscheidet der Betreiber mit rechtlicher
Beratung — nicht Claude, nicht der Bot.
