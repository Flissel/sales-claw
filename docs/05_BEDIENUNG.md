# 05 — Bedienung für Menschen

Fünf Handgriffe. Mehr braucht der Alltag nicht; alles andere steht in
[04_BETRIEB_MINIPC.md](04_BETRIEB_MINIPC.md) und ist für Claude gedacht.

| Was du willst | Was du tust |
|---|---|
| **Geht es dem System gut?** | Doppelklick auf `scripts/status-server.ps1`. Steht überall „ok" und unten „ALLE PRUEFUNGEN GRUEN" — ja. |
| **Update einspielen** | Doppelklick auf `scripts/update-server.ps1` — ODER dem Bot schreiben: „spiel das Update ein". Er bestellt es und meldet das Ergebnis. |
| **LinkedIn-Post raus** | Freigeben — mehr nicht. Der Beitrag geht binnen einer Minute raus, höchstens einer pro Tag (der Rest folgt an den nächsten Tagen). Freigabe geht in der Oberfläche oder über den Bot. |
| **Oberfläche öffnen** | `https://vibemind-offload-1.tail6c7d61.ts.net` — verschlüsselt, gültiges Zertifikat, funktioniert von jedem Gerät im Tailscale-Netz (auch Handy). Ersatzweise `http://100.67.177.45:8791`. |
| **Etwas ist kaputt** | Status-Doppelklick, die ROTEN Zeilen kopieren und Claude geben. Nicht raten, nicht neustarten — die Zeilen sagen, wo es klemmt. |
| **Notfall: Update zurückrollen** | Kapitel „Rückfahrkarte" in 04 — vier Zeilen zum Kopieren. Passiert bei rotem Update auch automatisch. |
| **Neuen Kontakt anschreiben** | Erst die Grundlage nennen: dem Bot schreiben „<Name> ist Bestandskunde" oder „<Name> hat auf der Messe eingewilligt" (mit Quelle). Ohne das verweigert das System die Erstansprache — § 7 UWG, kein Fehler. Wer selbst schreibt, darf immer beantwortet werden. |
| **Oberfläche mit Anmeldung sichern** | Einmal auf der VM: `bash ~/sales-claw/deploy/benutzer-anlegen.sh` — fragt Name, Rolle und Passwort. Ab dann verlangt die Oberfläche eine Anmeldung; derselbe Aufruf setzt später Passwörter zurück oder legt Team-Mitglieder an (Rolle `lesen` = nur ansehen). |
| **Sich in der Oberfläche zurechtfinden** | Seit 02.09.2026 vier Gruppen statt zehn Reiter: **Aufgaben** (Heute, Freigaben, Wiedervorlagen, Einordnung, Kalender), **Analyse** (Kontakte, Pipeline, Ergebnisse, Posteingang), **Daten** (Medien), **Monitoring** (WhatsApp). Die Startseite **Heute** zeigt links alles, was eine Entscheidung braucht, rechts Kalender, WhatsApp-Zustand, Posteingang und Pipeline. Die Zahl am Menü ist dieselbe wie auf der Seite. |
| **Freigaben ordnen** | Unter *Freigaben* stehen vier Blöcke — WhatsApp, LinkedIn, E-Mail, Termine — jeder mit seinen offenen Entwürfen und darunter seinem eigenen Verlauf (gesendet, abgelehnt; bei Terminen bestätigt, verschoben, abgesagt). „Ganzer Verlauf“ öffnet die volle Liste dieser einen Art. |
| **Datei für den Bot bereitstellen** | Entweder unter *Medien* hochladen — oder die Datei per WhatsApp **an dich selbst** schicken (dein eigener Chat): sie liegt danach in den Medien mit Herkunft „chat“. Erlaubt: PDF, JPG, PNG, MP3, OGG, MP4, bis 15 MB. Der Schalter **„Bot darf senden“** je Datei entscheidet, ob der Bot sie an Kunden hängen darf; „Aus“ nennt er dem Bot als gesperrt. |
| **Am Handy** | Unten eine Leiste mit den vier Gruppen, oben nur die Seiten der gerade offenen Gruppe. Alle Knöpfe sind daumengroß; die Freigabe-Karten sind dieselben wie am Desktop. |
| **E-Mail schreiben lassen** | Dem Bot sagen: „schreib eine Mail an bewerbung@beispiel.de, Betreff X" — er legt den Entwurf in die Freigabe, deine Freigabe versendet über dein Mailkonto. Auch: „was ist im Postfach?" — er liest die INBOX (nur lesen, nichts wird verändert). |

Drei Dinge, die man wissen muss:

1. **Nachts um 04:35 sichert sich die Anlage selbst** (die letzten 7 Stände
   werden aufgehoben). Updates passieren dagegen NIE von selbst — nur wenn
   du sie anstößt.
2. **Während eines Updates schweigt der Bot kurz** (unter einer Minute).
   Er verbindet sich von selbst wieder.
3. **Der Bot kann bestellen, aber nie ausführen.** Updates führt das
   Wirtssystem aus, Freigaben erteilst du, die Zugriffsliste ändert nur
   ein Mensch.
