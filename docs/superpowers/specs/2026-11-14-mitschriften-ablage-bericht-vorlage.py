"""Einmal-Bericht (intern) zu einem Termin: Auswertung, Bilder je Thema, Transkript.
Laeuft im Container sales-termine, uid aus Umgebung U, HTML auf stdout.
Nur lesend. Bilder verkleinert (max 1000 px, JPEG q70) und eingebettet."""
import base64
import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

import bildschirm
import server
import ui_termin

UID = os.environ["U"]
TZ = ZoneInfo("Europe/Berlin")
MAX_JE_THEMA = 6

e = ui_termin._e
a = server._q("select titel, thema, beginn, ende, plattform, bilder_uebersprungen "
              "from termin_akten where uid = %s", (UID,))[0]
m = server._q("select segmente, auswertung_md, auswertung_json from termin_mitschriften "
              "where uid = %s", (UID,))[0]
seg = m["segmente"] if isinstance(m["segmente"], list) else json.loads(m["segmente"] or "[]")
aj = m["auswertung_json"]
aj = json.loads(aj) if isinstance(aj, str) else (aj or {})
bilder = bildschirm.bilder(UID)


def zeit(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(TZ).strftime("%H:%M:%S")
    except ValueError:
        return ""


def bild_data_uri(bid):
    roh = bildschirm.bild_daten(UID, bid)
    if not roh:
        return None
    im = Image.open(io.BytesIO(roh)).convert("RGB")
    im.thumbnail((1000, 1000))
    puffer = io.BytesIO()
    im.save(puffer, "JPEG", quality=70, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(puffer.getvalue()).decode()


nach_id = {str(b["id"]): b for b in bilder}
themen = []
for v in aj.get("verlauf") or []:
    if not isinstance(v, dict):
        continue
    von, bis = v.get("von"), v.get("bis")
    if not (isinstance(von, int) and isinstance(bis, int) and 0 <= von <= bis < len(seg)):
        continue
    ids = bildschirm.bilder_zu_abschnitt(seg, von, bis, bilder)
    if len(ids) > MAX_JE_THEMA:  # gleichmaessig ausduennen
        schritt = len(ids) / MAX_JE_THEMA
        ids = [ids[int(i * schritt)] for i in range(MAX_JE_THEMA)]
    karten = []
    for bid in ids:
        uri = bild_data_uri(bid)
        if not uri:
            continue
        b = nach_id[bid]
        unter = e(b["aufgenommen_am"].astimezone(TZ).strftime("%H:%M"))
        if b.get("beschreibung"):
            unter += " – " + e(b["beschreibung"][:220])
        karten.append(f'<figure><img src="{uri}" alt="Bildschirm"><figcaption>{unter}</figcaption></figure>')
    themen.append(f'<section class="thema"><h3>{e(v.get("thema") or "Thema")}</h3>'
                  f'<p class="meta">Segmente {von}–{bis}</p>'
                  + (f'<div class="bilder">{"".join(karten)}</div>' if karten else "") + "</section>")

zeilen = "".join(
    f'<tr><td class="z">{e(zeit(s.get("beginn")))}</td><td class="s">{e(s.get("sprecher") or "?")}</td>'
    f'<td>{e(s.get("text"))}</td></tr>' for s in seg if isinstance(s, dict))

titel = a["titel"] or a["thema"] or "Termin"
datum = a["beginn"].astimezone(TZ).strftime("%d.%m.%Y, %H:%M") if a["beginn"] else ""
html = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terminbericht – {e(titel)}</title>
<style>
:root {{ --schrift:#1d1d1f; --blass:#6b6b70; --linie:#e2e2e6; --flaeche:#f6f6f8; }}
body {{ font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--schrift);
  background: #fff; max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.6rem; margin: 0 0 .2rem; }} h2 {{ margin-top: 2.2rem; border-bottom: 1px solid var(--linie); padding-bottom: .3rem; }}
.meta {{ color: var(--blass); font-size: .9rem; margin: .1rem 0 .6rem; }}
.intern {{ display:inline-block; background:#fff3cd; border:1px solid #e6c65c; padding:.15rem .5rem; border-radius:4px; font-size:.85rem; }}
.thema {{ break-inside: avoid; margin-bottom: 1.4rem; }}
.bilder {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
figure {{ margin: 0; border: 1px solid var(--linie); border-radius: 6px; overflow: hidden; background: var(--flaeche); break-inside: avoid; }}
figure img {{ width: 100%; display: block; }}
figcaption {{ font-size: .8rem; color: var(--blass); padding: .4rem .55rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
td {{ border-top: 1px solid var(--linie); padding: .3rem .4rem; vertical-align: top; }}
td.z {{ color: var(--blass); white-space: nowrap; font-variant-numeric: tabular-nums; }}
td.s {{ font-weight: 600; white-space: nowrap; }}
@media print {{ body {{ max-width: none; padding: 0; }} h2 {{ break-after: avoid; }} }}
</style></head><body>
<p class="intern">Intern – enthält Kundendaten, nicht weitergeben</p>
<h1>{e(titel)}</h1>
<p class="meta">{e(datum)} · {e(a["plattform"] or "")} · {len(seg)} Segmente · {len(bilder)} Standbilder
 · {int(a["bilder_uebersprungen"] or 0)} heikle Bildschirme nicht gespeichert</p>
<h2>Auswertung</h2>
<div>{ui_termin._md(m["auswertung_md"] or "")}</div>
<h2>Bilder je Thema</h2>
<p class="meta">Höchstens {MAX_JE_THEMA} Bilder je Thema, verkleinert.</p>
{"".join(themen) or '<p class="meta">Keine Bilder.</p>'}
<h2>Transkript</h2>
<p class="meta">Bereinigt; „?“ = Sprecher nicht erkannt. Zeiten in Berliner Zeit.</p>
<table>{zeilen}</table>
<p class="meta">Erstellt {datetime.now(TZ).strftime("%d.%m.%Y %H:%M")} aus sales-claw.</p>
</body></html>"""
print(html)
