// Mitte der Collage: die Seite 1:1 wie seite_html (Vorschau/PDF), auf die freie Breite skaliert.
// Klick waehlt, Ziehen verschiebt (Einrasten mit Hilfslinien, Alt = frei), acht Griffe skalieren
// (Umschalt = Verhaeltnis), der Drehgriff oben dreht (Umschalt = 15 Grad), Doppelklick auf Text
// oder Knopf oeffnet ein Textfeld genau ueber der Ebene, der Griff unten zieht die Seitenhoehe.
// Geometrie nur aus seiteGeometrie (Task 4); waehrend des Ziehens 'live', beim Loslassen festschreiben.
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { Box } from '@mui/material';

import type { SeitenEbene } from '../../seite';
import { drehenAmGriff, einrastenSeite, griffZiehen, type Griff, type Linie } from '../../seiteGeometrie';
import { SeiteText } from '../../seiteText';
import { quelleAnzeige } from '../Gestaltung/hilfen';
import { FARBE, FLAECHE_SCHATTEN } from '../Gestaltung/gestaltungStil';

import { aussehen, bildPassung, seitenStil } from './seiteStil';
import SeitenFuss, { type Pflichtteil } from './SeitenFuss';
import SeiteTextfeld from './SeiteTextfeld';
import type { SeiteZustand } from './useSeite';

const RAND = 48;
type Zug =
  | { art: 'schieben' | 'drehen'; id: string; px: number; py: number; start: SeitenEbene; bewegt: boolean }
  | { art: 'griff'; id: string; griff: Griff; px: number; py: number; start: SeitenEbene; bewegt: boolean }
  | { art: 'hoehe'; px: number; py: number; startHoehe: number; bewegt: boolean };

const GRIFFE: Array<[Griff, number, number, string]> = [
  ['nw', 0, 0, 'nwse-resize'], ['n', 0.5, 0, 'ns-resize'], ['no', 1, 0, 'nesw-resize'], ['o', 1, 0.5, 'ew-resize'],
  ['so', 1, 1, 'nwse-resize'], ['s', 0.5, 1, 'ns-resize'], ['sw', 0, 1, 'nesw-resize'], ['w', 0, 0.5, 'ew-resize'],
];

// Ganze Einheiten: die Zahlenfelder rechts zeigen ganze Zahlen und runden sonst schon beim Verlassen.
const ganz = Math.round;
// Im Browser vor dem Zeichnen messen; beim Server-Rendern (Tests) nichts tun und nicht warnen.
const useMessEffekt = typeof window === 'undefined' ? useEffect : useLayoutEffect;

function EbenenInhalt({ e }: { e: SeitenEbene }) {
  if (e.art === 'bild') return <img src={quelleAnzeige(e.quelle)} alt="" draggable={false} style={bildPassung(e)} />;
  if (e.art === 'text') return <SeiteText text={e.text} />;
  if (e.art === 'knopf') return <>{e.text}</>;
  return null;
}

// gesperrt (der Assistent arbeitet, die Flaeche zeigt evtl. seinen Zwischenstand, oder der Newsletter liegt zur
// Freigabe): ein laufendes Ziehen endet,
// ein offenes Textfeld schliesst ohne zu schreiben - nichts aus der Anzeige landet in der echten Seite.
export default function SeiteFlaeche({ z, gesperrt = false, pflichtteil = null }: { z: SeiteZustand; gesperrt?: boolean; pflichtteil?: Pflichtteil | null }) {
  const { seite: s, auswahl } = z;
  const buehne = useRef<HTMLDivElement | null>(null);
  const blatt = useRef<HTMLDivElement | null>(null);
  const elemente = useRef(new Map<string, HTMLDivElement>());
  const zug = useRef<Zug | null>(null);
  const [zoom, setZoom] = useState(1);
  const [linien, setLinien] = useState<Linie[]>([]);
  const [hoeheGemessen, setHoeheGemessen] = useState<number | null>(null);
  const [bearbeitet, setBearbeitet] = useState<string | null>(null);
  const gesperrtRef = useRef(gesperrt);
  gesperrtRef.current = gesperrt;
  const zRef = useRef(z);
  zRef.current = z;
  useEffect(() => {
    if (!gesperrt) return;
    // Was bis eben gezogen wurde, gehoerte noch zur echten Seite: festschreiben, dann loslassen.
    if (zug.current?.bewegt) zRef.current.festschreiben();
    zug.current = null;
    setLinien([]);
    setBearbeitet(null);
  }, [gesperrt]);

  // Freie Breite der Buehne -> Zoom (vor dem Messen 1:1, so rendert auch der Server).
  useMessEffekt(() => {
    const el = buehne.current;
    if (!el) return;
    const messen = () => setZoom(Math.min(1.5, Math.max(0.25, (el.clientWidth - 2 * RAND) / s.breite)));
    const ro = new ResizeObserver(messen);
    ro.observe(el);
    messen();
    return () => ro.disconnect();
  }, [s.breite]);

  // Text waechst ueber hoehe hinaus (min-height): der Auswahlrahmen nimmt die echte Hoehe.
  useMessEffekt(() => {
    const el = auswahl ? elemente.current.get(auswahl) : undefined;
    setHoeheGemessen(el ? el.offsetHeight : null);
  }, [s, auswahl]);

  const gewaehlt = s.ebenen.find((e) => e.id === auswahl) ?? null;
  const editiert = s.ebenen.find((e) => e.id === bearbeitet && (e.art === 'text' || e.art === 'knopf')) ?? null;

  const seitenPunkt = (ev: React.PointerEvent) => {
    const r = blatt.current?.getBoundingClientRect();
    return r ? { x: (ev.clientX - r.left) / zoom, y: (ev.clientY - r.top) / zoom } : { x: 0, y: 0 };
  };

  const fangen = (ev: React.PointerEvent<HTMLElement>, neu: Zug) => {
    if (ev.button !== 0 || gesperrtRef.current) return false;
    ev.stopPropagation();
    ev.preventDefault();
    buehne.current?.focus({ preventScroll: true });
    // Ein wartender Tipp-Schritt wird jetzt sein eigener Schritt, nicht Teil des Ziehens.
    z.festschreiben();
    ev.currentTarget.setPointerCapture(ev.pointerId);
    zug.current = neu;
    return true;
  };

  const bewegen = (ev: React.PointerEvent<HTMLElement>) => {
    const zg = zug.current;
    if (!zg || gesperrtRef.current) return;
    if (!zg.bewegt && Math.hypot(ev.clientX - zg.px, ev.clientY - zg.py) < 3) return;
    zg.bewegt = true;
    const dx = (ev.clientX - zg.px) / zoom;
    const dy = (ev.clientY - zg.py) / zoom;
    if (zg.art === 'hoehe') {
      z.hoeheSetzen(zg.startHoehe + dy, 'live');
      return;
    }
    if (zg.art === 'schieben') {
      const ziel = { ...zg.start, x: zg.start.x + dx, y: zg.start.y + dy };
      const r = ev.altKey ? { x: ziel.x, y: ziel.y, linien: [] } : einrastenSeite(ziel, z.aktuell().ebenen, s.hoehe, 6 / zoom);
      // Eingerastete Achse exakt lassen (Kante an Kante), sonst auf ganze Einheiten.
      const x = r.linien.some((l) => l.art === 'senkrecht') ? r.x : ganz(r.x);
      const y = r.linien.some((l) => l.art === 'waagrecht') ? r.y : ganz(r.y);
      z.ebeneAendern(zg.id, { x, y }, 'live');
      setLinien(r.linien);
    } else if (zg.art === 'griff') {
      const n = griffZiehen(zg.start, zg.griff, dx, dy, ev.shiftKey);
      z.ebeneAendern(zg.id, { x: ganz(n.x), y: ganz(n.y), breite: ganz(n.breite), hoehe: ganz(n.hoehe) }, 'live');
    } else {
      const p = seitenPunkt(ev);
      z.ebeneAendern(zg.id, { drehung: ganz(drehenAmGriff(zg.start, p.x, p.y, ev.shiftKey).drehung ?? 0) }, 'live');
    }
  };

  const los = () => {
    if (zug.current?.bewegt) z.festschreiben();
    zug.current = null;
    setLinien([]);
  };
  const zugGriffe = { onPointerMove: bewegen, onPointerUp: los, onPointerCancel: los };

  const merken = (id: string) => (el: HTMLDivElement | null) => {
    if (el) elemente.current.set(id, el);
    else elemente.current.delete(id);
  };

  const px = 1 / zoom;
  const rahmenHoehe = gewaehlt ? Math.max(gewaehlt.hoehe, gewaehlt.art === 'text' ? hoeheGemessen ?? 0 : 0) : 0;

  return (
    <Box
      ref={buehne}
      data-buehne
      tabIndex={-1}
      aria-label="Seite"
      onPointerDown={() => {
        buehne.current?.focus({ preventScroll: true });
        z.waehlen(null);
      }}
      sx={{ flex: 1, minHeight: 0, overflow: 'auto', scrollbarGutter: 'stable', outline: 'none', bgcolor: FARBE.geruest, userSelect: 'none' }}
    >
      <div style={{ position: 'relative', width: s.breite * zoom, height: s.hoehe * zoom, margin: `${RAND}px auto ${pflichtteil ? 0 : RAND}px`, boxShadow: FLAECHE_SCHATTEN }}>
        <div ref={blatt} style={{ position: 'absolute', left: 0, top: 0, width: s.breite, height: s.hoehe, transform: `scale(${zoom})`, transformOrigin: '0 0' }}>
          {/* Die Seite wie seite_html; Links in Texten fuehren im Editor nirgendwohin. */}
          <div data-seite style={seitenStil(s)} onClickCapture={(ev) => ev.preventDefault()}>
            {s.ebenen.map((e, i) => (
              <div
                key={e.id}
                ref={merken(e.id)}
                data-ebene={e.id}
                onPointerDown={(ev) => {
                  if (fangen(ev, { art: 'schieben', id: e.id, px: ev.clientX, py: ev.clientY, start: e, bewegt: false })) z.waehlen(e.id);
                }}
                {...zugGriffe}
                onDoubleClick={() => !gesperrtRef.current && (e.art === 'text' || e.art === 'knopf') && setBearbeitet(e.id)}
                style={{ ...aussehen(s, e, i), cursor: 'move', touchAction: 'none', visibility: e.id === editiert?.id ? 'hidden' : undefined }}
              >
                <EbenenInhalt e={e} />
              </div>
            ))}
          </div>
          {gewaehlt && !editiert && (
            <div
              style={{
                position: 'absolute', left: gewaehlt.x - gewaehlt.breite / 2, top: gewaehlt.y - gewaehlt.hoehe / 2,
                width: gewaehlt.breite, height: rahmenHoehe, transform: gewaehlt.drehung ? `rotate(${gewaehlt.drehung}deg)` : undefined,
                outline: `${px}px solid ${FARBE.akzent}`, pointerEvents: 'none', zIndex: 2,
              }}
            >
              <div style={{ position: 'absolute', left: '50%', top: -24 * px, width: px, height: 24 * px, background: FARBE.akzent }} />
              <div
                aria-label="Drehen"
                {...zugGriffe}
                onPointerDown={(ev) => fangen(ev, { art: 'drehen', id: gewaehlt.id, px: ev.clientX, py: ev.clientY, start: gewaehlt, bewegt: false })}
                style={{
                  position: 'absolute', left: `calc(50% - ${6 * px}px)`, top: -30 * px, width: 12 * px, height: 12 * px, borderRadius: '50%',
                  background: '#ffffff', border: `${px}px solid ${FARBE.akzent}`, boxSizing: 'border-box', cursor: 'grab', pointerEvents: 'auto', touchAction: 'none',
                }}
              />
              {GRIFFE.map(([g, gx, gy, cursor]) => (
                <div
                  key={g}
                  aria-label={`Größe ${g}`}
                  {...zugGriffe}
                  onPointerDown={(ev) => fangen(ev, { art: 'griff', griff: g, id: gewaehlt.id, px: ev.clientX, py: ev.clientY, start: gewaehlt, bewegt: false })}
                  style={{
                    position: 'absolute', left: `calc(${gx * 100}% - ${5 * px}px)`, top: `calc(${gy * 100}% - ${5 * px}px)`,
                    width: 10 * px, height: 10 * px, background: '#ffffff', border: `${px}px solid ${FARBE.akzent}`,
                    borderRadius: 2 * px, boxSizing: 'border-box', cursor, pointerEvents: 'auto', touchAction: 'none',
                  }}
                />
              ))}
            </div>
          )}
          {linien.map((l) => (
            <div
              key={l.art + l.wert}
              style={{
                position: 'absolute', background: FARBE.akzent, pointerEvents: 'none', zIndex: 3,
                ...(l.art === 'senkrecht'
                  ? { left: l.wert - px / 2, top: 0, width: px, height: s.hoehe }
                  : { top: l.wert - px / 2, left: 0, height: px, width: s.breite }),
              }}
            />
          ))}
          {editiert && (editiert.art === 'text' || editiert.art === 'knopf') && (
            <SeiteTextfeld
              key={editiert.id}
              seite={s}
              e={editiert}
              hoehe={Math.max(editiert.hoehe, hoeheGemessen ?? 0)}
              rand={px}
              fertig={(text) => {
                setBearbeitet(null);
                if (gesperrtRef.current) return;
                if (text !== null && text !== editiert.text) z.ebeneAendern(editiert.id, { text }, 'sofort');
              }}
            />
          )}
        </div>
        {/* Seitenhoehe: Griff am unteren Rand (gesperrt - Assistent oder zur Freigabe - kein Griff) */}
        {!gesperrt && (
          <Box
            role="slider"
            aria-label="Seitenhöhe"
            aria-valuenow={s.hoehe}
            aria-valuemin={400}
            aria-valuemax={6000}
            title="Seitenhöhe ziehen"
            {...zugGriffe}
            onPointerDown={(ev: React.PointerEvent<HTMLElement>) => fangen(ev, { art: 'hoehe', px: ev.clientX, py: ev.clientY, startHoehe: s.hoehe, bewegt: false })}
            sx={{
              position: 'absolute', left: '50%', bottom: -14, transform: 'translateX(-50%)', width: 64, height: 10, borderRadius: 5,
              bgcolor: FARBE.linie, border: `1px solid ${FARBE.gedaempft}`, cursor: 'ns-resize', touchAction: 'none',
              '&:hover': { bgcolor: FARBE.akzent },
            }}
          />
        )}
      </div>
      {pflichtteil && <SeitenFuss s={s} p={pflichtteil} zoom={zoom} />}
    </Box>
  );
}

