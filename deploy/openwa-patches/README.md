# OpenWA — lokale Patches am Upstream

`openwa/upstream/` ist ein gitignoriertes Nested-Repo (Pin `97cba60`).
Bis zum 02.09.2026 lag der einzige Patch (Dockerfile) **nur als
unversionierte Arbeitskopie** darin — ein `git checkout` dort hätte ihn
still verloren. Seitdem liegen alle Patches hier als Dateien und werden
mit `deploy/openwa-patch-anwenden.sh` eingespielt.

| Patch | Was | Warum |
|---|---|---|
| `0001-dockerfile-apt-gpg.patch` | Dockerfile: PGDG-Schlüssel dearmoren | Debian-bookworm-apt lehnt den ASCII-Schlüssel ab (gemessen 18.08.2026) |
| `0002-dashboard-embed.patch` | `src/main.ts`: `DASHBOARD_FRAME_ANCESTORS` erweitert CSP `frame-ancestors`; Dashboard: Schlüssel in `localStorage` statt `sessionStorage` — in **allen vier** Stellen: `App.tsx` (Login), `services/api.ts` (jede API-Anfrage), `hooks/useWebSocket.ts` (Events) | Das Dashboard soll im WhatsApp-Tab von sales-ui eingebettet und dort dauerhaft angemeldet sein (Betreiber-Wunsch 02.09.2026). Lehre vom selben Tag: die erste Fassung stellte nur das Login um — Anfragen lasen weiter aus `sessionStorage`, schickten keinen Schlüssel und liefen in 401; die Drossel (429) verdeckte das zunächst. Vertrag: `scripts/tests/test_openwa_patches.py` |

## Einspielen (nach frischem Klon oder Upstream-Wechsel)

```bash
bash deploy/openwa-patch-anwenden.sh          # setzt auf den Pin zurück, prüft (--check), wendet an
docker compose -f docker-compose.openwa.yml build openwa
docker compose -f docker-compose.openwa.yml up -d openwa
```

Der Bau enthält den Dashboard-Build (Vite) — Patch 0002 wirkt erst nach
einem Neubau des Images. Ein Neustart von openwa kann die
WhatsApp-Session kosten (gemessen 01.09.2026: Chromium-Startfehler →
Neukopplung per Pairing-Code); deshalb Image erst fertig bauen, dann
einmal `up -d`.

Das Skript stellt IMMER „Pin + Patches“ her: nachgeführte Änderungen im
Nested-Repo werden zuerst auf den Pin zurückgesetzt. So greift auch ein
geänderter Patch (sonst wäre er weder rückwärts noch vorwärts anwendbar,
und ein „übersprungen“ versteckte den Fehler).

## Beim Upstream-Update

`git -C openwa/upstream fetch && git checkout <neuer Pin>`, dann das
Skript. Schlägt `--check` fehl, ist der Patch mit dem neuen Stand zu
verheiraten — genau dafür stehen die Diffs hier und nicht nur im Kopf.

## Sicherheitsnotiz zu 0002

`localStorage` hält den OpenWA-API-Schlüssel dauerhaft im Browser des
Betreibers (vorher: nur bis der Tab zuging). Das Deployment ist
tailnet-only, der Schlüssel bleibt auf seinem eigenen Gerät, Abmelden
löscht ihn. `DASHBOARD_FRAME_ANCESTORS` nennt ausschließlich die
sales-ui-Origin; leer = Upstream-Verhalten.
