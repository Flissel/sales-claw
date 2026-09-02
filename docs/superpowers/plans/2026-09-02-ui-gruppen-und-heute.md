# Plan: Oberfläche in vier Gruppen, Startseite „Heute“ (02.09.2026)

Betreiber-Entscheid 02.09.2026 nach drei Design-Iterationen (Canvas
„sales-claw Oberfläche“): „sonst ist's top und darf gebaut werden“.

Ziel: zehn gleichrangige Reiter werden zu vier Gruppen — **Aufgaben**
(Heute, Freigaben, Wiedervorlagen, Einordnung, Kalender), **Analyse**
(Kontakte, Pipeline, Ergebnisse, Posteingang), **Daten** (Medien),
**Monitoring** (WhatsApp). Freigaben getrennt nach Art (WhatsApp,
LinkedIn, E-Mail, Termine), jede Art mit eigenem Verlauf. Medien mit
Schalter „Bot darf senden“ und Herkunft.

Jeder Schritt: Vertrag zuerst (rot), dann Code (grün), Commit, CI,
Rollout nur `sales-ui` (`git pull --ff-only && docker compose up -d
--build sales-ui`), Abnahme grün, Browser-Blick.

- [ ] **1. Rahmen.** `_seite()` rendert eine Seitenleiste mit vier
  Gruppen statt der Reiterleiste; `_NAV` wird `_GRUPPEN`; Zähler aus
  denselben Abfragen wie die Seiten (`_zaehler()`, fällt leise aus);
  aktiver Menüpunkt über einen ContextVar aus `_gesichert_seite`.
  Tokens: hellere Fläche/Linie im dunklen Thema, `--aktiv`. Unter 768 px
  wird die Leiste wieder zur umbrechenden Zeile (Vier-Tab-Leiste kommt in
  Schritt 7). Verträge: `tests/test_seitenleiste.py`.
- [ ] **2. Startseite „Heute“.** Neue Route `/`, die Freigabe-Inbox
  zieht nach `/freigaben` (Umleitungen der Aktionen folgen). Blöcke:
  Freigaben je Art mit Zählern, Wiedervorlagen, Einordnung; rechte
  Spalte: Kalender (`kalender.termine_lesen`), WhatsApp-Zustand,
  Posteingang, Pipeline-Zähler. Verträge in `test_ui.py` ziehen von
  `/` auf `/freigaben` um, neue in `test_heute.py`.
- [ ] **3. Freigaben in vier Blöcken mit Verlauf.** `inbox()` teilt
  pending nach `channel`; Termine = offene Terminanfragen; Verlauf je
  Art (sent/failed/rejected; bei Terminen termin/termin_verschoben/
  termin_abgesagt), zwei Einträge im Block, volle Liste unter
  `/freigaben/verlauf/<art>`.
- [ ] **4. Medien.** Tabelle `medien_meta` (dateiname, bot_darf_senden,
  herkunft, gesendet_zuletzt); `medien_liste()` im Bot filtert;
  Eingang speichert Betreiber-Anhänge (nur eigene Nummer) nach
  `/media-erzeugt` mit Herkunft „Chat“.
- [ ] **5. Kontakte.** Tabelle ohne Formular je Zeile, Autonomie als
  Segment, Score-Spalte; Aktionen bleiben auf der Kontaktseite.
- [ ] **6. Monitoring.** Kette Handy → OpenWA → Webhook → Posteingang →
  Datenbank mit letztem Beweis je Station; Abnahme-Ergebnis aus
  `update-status.json`; Dashboard-Rahmen bleibt.
- [ ] **7. Handy.** Seitenleiste wird unter 768 px zur Vier-Tab-Leiste.

Bewusst nicht: Google-Fonts (CSP `default-src 'none'` lässt keine
fremden Schriften; Plex Sans nur, wenn wir sie selbst ausliefern —
eigener Schritt, falls gewünscht), Kalender-Neuzeichnung (Monatsgitter
bleibt).
