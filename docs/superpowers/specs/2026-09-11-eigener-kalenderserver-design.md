# Eigener Kalenderserver — SOGo aus dem vorhandenen Mailcow, auf der VM

**Datum:** 2026-09-11
**Status:** Design. Nachgelagertes Vorhaben.
**Auslöser:** Frage des Betreibers — *„Der Kalenderserver is der bei mailcow dabei?"* — und
die Entscheidung, dass er **auf die VM** gehört, nicht auf den Arbeitsrechner.

---

## 1. Der Befund

**Ja, Mailcow bringt einen Kalenderserver mit: SOGo.** Er kann CalDAV, Freigaben,
Frei/Belegt, eine Web-Oberfläche — und Einladungen per E-Mail, also genau die Mechanik aus
`2026-09-11-team-terminabstimmung-design.md`.

**Bei euch läuft er nicht.** Gemessen am 11.09.2026:

* Mailcow läuft — **zehn Container**, alle oben, Verzeichnis `/home/felix/mailcow-dockerized`.
* **Kein SOGo-Container.** Er ist abgewählt, nicht abwesend.
* Mailcow läuft **in WSL auf dem Arbeitsrechner des Betreibers**, nicht auf der VM.

Der zweite Punkt wiegt schwerer als der erste. Ein Kalenderserver für ein Team, der nur
läuft, während ein bestimmter Arbeitsrechner an ist, taugt nicht als gemeinsame Grundlage.

---

## 2. Warum das ein eigenes Vorhaben ist — und kein Schalter

SOGo einzuschalten ist eine Zeile in `mailcow.conf`. **Mailcow auf die VM zu ziehen ist ein
Mailserver-Umzug**, und der berührt:

* **DNS** — MX-, SPF-, DKIM- und DMARC-Einträge zeigen auf den bisherigen Betrieb.
* **Zertifikate** — der ACME-Container holt sie für den bisherigen Namen.
* **Daten** — Postfächer, Adressbücher, bestehende Termine.
* **Zustellbarkeit** — eine neue absendende Adresse ist für Empfänger zunächst unbekannt;
  falsch gemacht, landen Mails im Spam. Das trifft unmittelbar den Mailversand von
  sales-claw.
* **Ausfallzeit** — währenddessen kommt keine Post an.

Das ist nicht schwer, aber es ist unumkehrbar genug, um es nicht nebenbei zu tun.

---

## 3. Was gebaut wird

**Schritt 1 — SOGo einschalten, dort wo Mailcow heute läuft.** `SKIP_SOGO` abwählen,
Container hochziehen, ein Konto anlegen, mit einem Kalenderprogramm verbinden. Ergebnis:
belegtes Wissen, ob SOGo das kann, was der Entwurf von ihm erwartet — Freigaben zwischen
Konten und Einladungen — **bevor** irgendetwas umzieht. Das ist billig und reversibel.

**Schritt 2 — Mailcow auf die VM.** Umzug mit Vorlaufzeit für DNS, geprüfter Zustellbarkeit
und einem Rückweg, falls es klemmt.

**Schritt 3 — Kalender umziehen.** Die Konten der Teammitglieder wandern von PrivateEmail
nach SOGo; sales-claw bekommt die neuen Endpunkte in seine Quellenliste
(`2026-09-11-team-terminabstimmung-design.md` §2.1). **Weil die Quellen dort bereits eine
Liste austauschbarer Endpunkte sind, ist das eine Konfigurationsänderung, kein Umbau.**

---

## 4. Wann sich das lohnt — und wann nicht

**Dafür:**

* Unabhängigkeit von Namecheap. Heute hängt die Terminabstimmung daran, dass PrivateEmail
  Freigaben erlaubt — gemessen tut es das, aber es ist deren Entscheidung, nicht eure.
* Für den Vertrieb an Kunden: eine **Rückfallebene** für Kunden ohne brauchbaren Kalender
  oder mit einem Anbieter, der keine Freigaben kann.
* Volle Kontrolle über Rechte, Aufbewahrung und Sicherung — was die DSGVO-Dokumente
  einfacher macht.

**Dagegen:**

* Ein Mailserver ist Betriebsarbeit, dauerhaft. Zustellbarkeit, Sperrlisten, Zertifikate,
  Updates.
* Der Nutzen für die Terminabstimmung ist **null**, solange PrivateEmail mitspielt — die
  gemessenen Fähigkeiten reichen aus.

**Empfehlung:** Schritt 1 bald (billig, schafft Wissen), Schritte 2 und 3 erst, wenn ein
konkreter Anlass da ist — ein Kunde, dessen Anbieter nicht mitspielt, oder ein Ärgernis mit
Namecheap.

---

## 5. Nicht im Umfang

* **Ablösung von PrivateEmail als Mailanbieter** ohne Not.
* **Migration der Kundendaten aus sales-claw** — die liegen in Postgres und sind vom
  Kalenderserver unberührt.

---

## 6. Prüfung

1. SOGo antwortet auf CalDAV und meldet in den Fähigkeiten Freigabe **und** Einladungen.
2. Eine Freigabe zwischen zwei SOGo-Konten erscheint im Konto des Empfängers.
3. Eine Einladung von SOGo an ein fremdes Konto (z. B. PrivateEmail) kommt dort als
   annehmbare Einladung an — und umgekehrt.
4. Nach dem Umzug: Mail läuft, Zustellbarkeit geprüft (nicht im Spam), Termine vollständig.
5. sales-claw arbeitet nach einem Endpunktwechsel in der Quellenliste weiter, **ohne
   Codeänderung** — das ist zugleich die Probe auf §2.1 der Hauptspec.
