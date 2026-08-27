# 05 — Bedienung für Menschen

Fünf Handgriffe. Mehr braucht der Alltag nicht; alles andere steht in
[04_BETRIEB_MINIPC.md](04_BETRIEB_MINIPC.md) und ist für Claude gedacht.

| Was du willst | Was du tust |
|---|---|
| **Geht es dem System gut?** | Doppelklick auf `scripts/status-server.ps1`. Steht überall „ok" und unten „ALLE PRUEFUNGEN GRUEN" — ja. |
| **Update einspielen** | Doppelklick auf `scripts/update-server.ps1` — ODER dem Bot schreiben: „spiel das Update ein". Er bestellt es und meldet das Ergebnis. |
| **LinkedIn-Post raus** | Erst in der Oberfläche freigeben, dann dem Bot schreiben: „post den freigegebenen LinkedIn-Beitrag". Freigeben allein versendet nie. |
| **Oberfläche öffnen** | `http://<VM-Tailscale-IP>:8791` — funktioniert auch vom Handy, sobald es im Tailscale-Netz ist. *(IP wird beim Cutover hier eingetragen.)* |
| **Etwas ist kaputt** | Status-Doppelklick, die ROTEN Zeilen kopieren und Claude geben. Nicht raten, nicht neustarten — die Zeilen sagen, wo es klemmt. |
| **Notfall: Update zurückrollen** | Kapitel „Rückfahrkarte" in 04 — vier Zeilen zum Kopieren. Passiert bei rotem Update auch automatisch. |

Drei Dinge, die man wissen muss:

1. **Nachts um 04:35 sichert sich die Anlage selbst** (die letzten 7 Stände
   werden aufgehoben). Updates passieren dagegen NIE von selbst — nur wenn
   du sie anstößt.
2. **Während eines Updates schweigt der Bot kurz** (unter einer Minute).
   Er verbindet sich von selbst wieder.
3. **Der Bot kann bestellen, aber nie ausführen.** Updates führt das
   Wirtssystem aus, Freigaben erteilst du, die Zugriffsliste ändert nur
   ein Mensch.
