# Terminbuchung durch Kunden — Buchungsseite fürs LinkedIn-Profil

**Datum:** 2026-09-11
**Status:** Design. Nachgelagertes Vorhaben — setzt die Terminabstimmung voraus.
**Auslöser:** *„Terminbuchung durch Kunden wäre noch interessant für linkedin profil"* —
ein Link im Profil, über den Interessenten selbst einen Termin buchen.

---

## 1. Warum das zuletzt kommt

Dieses Vorhaben ist das einzige, das **nach außen sichtbar** ist. Ein Fehler hier sieht
nicht der Betreiber, sondern ein Interessent: eine Seite, die belegte Zeiten anbietet, ein
Termin, der nie ankommt, oder — schlimmer — ein Kalender, der mehr preisgibt als gedacht.

Es setzt zweierlei voraus, das vorher stehen muss:

* **Verlässliche Frei/Belegt-Auskunft.** Wer freie Zeiten anbietet, muss alle Termine
  kennen — auch private, auch die der Kollegen, wenn gemeinsam beraten wird. Das ist genau
  `2026-09-11-team-terminabstimmung-design.md` §2.1/§2.2.
* **Einladungen, die funktionieren.** Eine Buchung ist nichts anderes als eine Einladung,
  die der Kunde auslöst statt der Betreiber (§2.3 derselben Spec).

Ohne beides wäre die Buchungsseite ein Versprechen, das die Technik dahinter nicht hält.

---

## 2. Was gebaut wird

**Eine öffentlich erreichbare Seite** mit einer Adresse, die ins LinkedIn-Profil passt. Sie
zeigt **freie Zeitfenster** — keine Termine, keine Namen, keine Themen. Nur: hier ist Platz.

**Der Weg einer Buchung:**

1. Interessent wählt ein Fenster, gibt Name, Kontaktweg und Anliegen an.
2. Das System prüft **erneut** gegen den Kalender (zwischen Anzeige und Klick kann sich
   etwas belegt haben).
3. Es entsteht ein **Termin-Entwurf**, kein gebuchter Termin.
4. **Der Betreiber gibt frei** — wie bei jeder ausgehenden Nachricht. Erst danach geht die
   Bestätigung samt Kalendereinladung an den Interessenten.

**Schritt 4 ist der Kern und nicht verhandelbar.** Eine Seite, über die Fremde ungefiltert
Zeit im Kalender des Betreibers belegen, ist ein offenes Scheunentor — für Werbung, für
Belästigung, für versehentliche Doppelbuchungen. Das Freigabe-Gate, das bei jeder Nachricht
gilt, gilt hier genauso.

**Was die Seite ausdrücklich nicht zeigt:** keine bestehenden Termine, keine Kundennamen,
keine Kalenderstruktur. Nur freie Fenster innerhalb von Regeln, die der Betreiber setzt —
Wochentage, Uhrzeiten, Vorlaufzeit, maximale Termine je Tag, Puffer zwischen Terminen.

---

## 3. Was zu bedenken ist

**Missbrauch.** Eine offene Buchungsseite wird gefunden. Nötig sind mindestens: Begrenzung
je Absender und Zeitraum, Pflichtangaben, und die Möglichkeit, einen Eintrag folgenlos zu
verwerfen. Ein Abwehrmechanismus gegen automatisierte Einträge ist zu erwägen — mit dem
Vorbehalt, dass die gängigen Verfahren Daten an Dritte geben, was hier begründet werden
müsste.

**Datenschutz.** Die Seite erhebt personenbezogene Daten von Menschen, die noch keine
Kunden sind. Sie braucht eine Datenschutzerklärung und einen Zweck, und die Angaben
gehören in `docs/06_DSGVO.md`. Was mit Buchungen geschieht, die der Betreiber ablehnt,
ist festzulegen — im Zweifel: löschen.

**Erreichbarkeit von außen.** Alles Bisherige läuft hinter Tailscale und ist damit nicht
öffentlich. Eine Buchungsseite muss aus dem offenen Netz erreichbar sein. Das ist ein
**neuer Angriffspfad** auf ein System, das Kundendaten hält — die Seite gehört deshalb
getrennt vom Rest, mit eigenem, minimalem Zugriff auf die Termindaten und **ohne** Zugriff
auf die Kundendatenbank.

**Die Oberfläche ist skriptfrei.** Die bestehende Oberfläche kommt bewusst ohne JavaScript
aus. Für eine öffentliche Buchungsseite ist das erst recht angebracht: weniger Angriffsfläche,
funktioniert überall. Eine Terminauswahl lässt sich als Formular bauen.

---

## 4. Nicht im Umfang

* **Bezahlung** oder Anzahlung bei Buchung.
* **Wiederkehrende Termine.**
* **Mehrere buchbare Personen** in einer Seite — das käme mit den Team-Instanzen.
* **Automatische Bestätigung ohne Freigabe.**

---

## 5. Prüfung

1. Die Seite zeigt nur Fenster, in denen **tatsächlich** frei ist — geprüft gegen einen
   Kalender mit privaten und geschäftlichen Terminen.
2. Sie gibt **nichts** über bestehende Termine preis: kein Titel, kein Name, keine Anzahl.
   Auch nicht im Quelltext der Seite.
3. Eine Buchung erzeugt einen Entwurf und **keinen** Kalendereintrag.
4. Ohne Freigabe des Betreibers geht **nichts** an den Interessenten.
5. Nach der Freigabe erhält er eine Bestätigung mit annehmbarer Kalendereinladung.
6. Zwei Buchungen desselben Fensters kurz hintereinander führen nicht zur Doppelbelegung.
7. Die Seite ist aus dem offenen Netz erreichbar — und von dort aus ist **kein** anderer
   Teil des Systems erreichbar.
