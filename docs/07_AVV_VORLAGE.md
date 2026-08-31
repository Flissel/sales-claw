# 07 — AVV-Vorlage (Auftragsverarbeitung, Art. 28 DSGVO)

**Vorlage, keine Rechtsberatung.** Gedacht für den Fall aus Teil E: der
Betreiber führt den Assistenten zentral und verarbeitet dabei Kontaktdaten
für weitere Berater (Team-Mitglieder). Dann ist das Team-Mitglied
Verantwortlicher für seine Kontakte und der Betreiber Auftragsverarbeiter.
Vor der ersten Nutzung durch ein Team-Mitglied ausfüllen, von beiden
unterschreiben, Ablage beim Betreiber. Platzhalter in ⟨spitzen Klammern⟩.

## 1. Parteien

- Verantwortlicher: ⟨Name, Anschrift des Team-Mitglieds⟩
- Auftragsverarbeiter: ⟨Name, Anschrift des Betreibers⟩

## 2. Gegenstand und Dauer

Betrieb eines KI-gestützten Vertriebsassistenten (Kontaktpflege,
Gesprächsentwürfe, Terminvorbereitung) auf Infrastruktur des Betreibers.
Dauer: ab Unterschrift bis zur Beendigung der Zusammenarbeit; bei
Offboarding gilt Ziffer 8.

## 3. Art und Zweck der Verarbeitung, Datenarten, Betroffene

- Zweck: Anbahnung und Pflege von Kundenbeziehungen des Verantwortlichen.
- Datenarten: Name, Telefonnummer, E-Mail, Chatverläufe (WhatsApp/E-Mail),
  Gesprächsnotizen, Bedarfsangaben, Pipeline-Status, Einwilligungsnachweise.
- Betroffene: Interessenten, Kunden und Geschäftskontakte des
  Verantwortlichen.

## 4. Weisungen

Der Betreiber verarbeitet nur auf dokumentierte Weisung (Konfiguration,
Freigaben, Werkzeugaufrufe des Verantwortlichen im System gelten als
Weisung). Hält er eine Weisung für rechtswidrig, informiert er
unverzüglich.

## 5. Technische und organisatorische Maßnahmen

Es gelten die Maßnahmen aus [08_TOMS.md](08_TOMS.md) in der jeweils
dokumentierten Fassung. Wesentliche Änderungen teilt der Betreiber mit.

## 6. Unterauftragsverarbeiter

Allgemeine Genehmigung für die folgende Liste; Änderungen werden vorab
angekündigt (Widerspruchsrecht):

| Dienst | Zweck | Ort/Garantie |
|---|---|---|
| Anthropic (Claude API) | Sprachmodell des Assistenten | USA — ⟨DPF/SCC prüfen und eintragen⟩ |
| Meta Platforms (WhatsApp) | Nachrichtenkanal | ⟨Status eintragen⟩ |
| ⟨E-Mail-Anbieter, z. B. GMX⟩ | E-Mail-Versand | DE/EU |
| ⟨Hosting, falls nicht eigene Hardware⟩ | Infrastruktur | ⟨eintragen⟩ |

GitHub hält nur Code und Konfiguration, keine Kontaktdaten, und steht
deshalb nicht in der Liste.

## 7. Betroffenenrechte und Mitwirkung

Der Betreiber unterstützt mit den eingebauten Verfahren: Auskunft über
`kontakt_auskunft` (Export, Übergabe durch Menschen), Löschbegehren über
`loeschantrag_vermerken` (sofortiger Vollstopp) und das Löschverfahren aus
[06_DSGVO.md](06_DSGVO.md). Meldung von Datenpannen an den
Verantwortlichen unverzüglich, spätestens binnen 48 Stunden nach
Kenntnis.

## 8. Löschung und Rückgabe

Bei Vertragsende erhält der Verantwortliche seine Daten als Export;
anschließend Löschung nach dem Verfahren aus 06 (inklusive Auslauf der
Sicherungen). Offboarding-Details regelt Teil E des Betriebsplans.

## 9. Nachweise

Der Verantwortliche kann die Einhaltung prüfen: Testabdeckung und
CI-Läufe sind öffentlich im Repository einsehbar, Betriebsprotokolle
stellt der Betreiber auf Anfrage bereit.

---

Ort, Datum, Unterschriften: ⟨Verantwortlicher⟩ / ⟨Auftragsverarbeiter⟩
