// Mitte des Gestaltungsfensters: die Flaeche als DOM-Vorschau in der 600er-Einheit,
// auf den freien Platz gezoomt. Ziehen verschiebt (mit Einrasten, Alt = frei),
// Scrollrad skaliert die Auswahl, Shift+Scrollrad dreht sie.
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { WarningAmberRounded } from '@mui/icons-material';
import { Box } from '@mui/material';

import { BREITE, drehen, Ebene, einrasten, hinweise, hoehe, Linie, schieben, skalieren, zoomFuer } from '../../gestaltung';
import { ebeneAlsKontext, pultStore } from '../../pultZustand';
import { SCHRIFT_FAMILIE } from '../../schemata';

import { quelleAnzeige } from './hilfen';
import { AUSSEN_MASKE, BUEHNE_RAND, FARBE, FLAECHE_SCHATTEN, uebergang } from './gestaltungStil';
import type { GestaltungZustand } from './useGestaltung';

type Masse = Record<string, { w: number; h: number }>;
type Zug = { id: string; px: number; py: number; start: Ebene; bewegt: boolean };

const AUSRICHTUNG = { links: 'left', mitte: 'center', rechts: 'right' } as const;

// Pixel je Scrollschritt: Zeilen- und Seitenmodus (Firefox) auf Pixel umrechnen.
function scrollPixel(e: WheelEvent): number {
  // Shift+Rad liefert in vielen Browsern deltaX statt deltaY.
  const d = e.deltaY !== 0 ? e.deltaY : e.deltaX;
  return e.deltaMode === 1 ? d * 16 : e.deltaMode === 2 ? d * 400 : d;
}

// Inhalt einer Ebene (auch fuer die Live-Vorschau im Canvas, FlaechenVorschau).
export function EbenenInhalt({ e }: { e: Ebene }) {
  if (e.art === 'bild') {
    return <img src={quelleAnzeige(e.quelle)} alt="" draggable={false} style={{ display: 'block', width: e.breite, height: 'auto' }} />;
  }
  return (
    <div
      style={{
        whiteSpace: 'pre',
        fontFamily: SCHRIFT_FAMILIE[e.schrift],
        fontWeight: e.gewicht,
        fontStyle: e.kursiv ? 'italic' : 'normal',
        fontSize: e.groesse,
        lineHeight: e.zeilenabstand,
        color: e.farbe,
        textAlign: AUSRICHTUNG[e.ausrichtung],
      }}
    >
      {e.text}
    </div>
  );
}

type Props = {
  z: GestaltungZustand;
  versteckt: Set<string>;
  onTextBearbeiten: (id: string) => void;
};

export default function Flaeche({ z, versteckt, onTextBearbeiten }: Props) {
  const { g, auswahl } = z;
  const h = hoehe(g.format);
  const buehne = useRef<HTMLDivElement | null>(null);
  const [platz, setPlatz] = useState({ w: 0, h: 0 });
  const [masse, setMasse] = useState<Masse>({});
  const [linien, setLinien] = useState<Linie[]>([]);
  const [hover, setHover] = useState<string | null>(null);
  const zug = useRef<Zug | null>(null);
  const elemente = useRef(new Map<string, HTMLDivElement>());
  const beobachter = useRef<ResizeObserver | null>(null);

  const zoom = platz.w > 0 ? zoomFuer(Math.max(1, platz.w - 2 * BUEHNE_RAND), Math.max(1, platz.h - 2 * BUEHNE_RAND), g.format) : 0;

  // Freier Platz der Buehne -> Zoom.
  useLayoutEffect(() => {
    const el = buehne.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPlatz({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setPlatz({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Groesse jeder Ebene in Einheiten (fuer Auswahlrahmen); Schriften und Bilder laden spaeter.
  const messen = useCallback(() => {
    const neu: Masse = {};
    elemente.current.forEach((el, id) => {
      neu[id] = { w: el.offsetWidth, h: el.offsetHeight };
    });
    setMasse((alt) => {
      const gleich = Object.keys(neu).length === Object.keys(alt).length && Object.entries(neu).every(([k, m]) => alt[k]?.w === m.w && alt[k]?.h === m.h);
      return gleich ? alt : neu;
    });
  }, []);
  useEffect(() => {
    beobachter.current = new ResizeObserver(messen);
    elemente.current.forEach((el) => beobachter.current?.observe(el));
    void document.fonts?.ready.then(messen);
    return () => beobachter.current?.disconnect();
  }, [messen]);
  useLayoutEffect(messen, [g, versteckt, messen]);

  // Ein stabiler Ref-Rueckruf je Ebene (sonst meldet React jedes Zeichnen ab und wieder an).
  const rueckrufe = useRef(new Map<string, (el: HTMLDivElement | null) => void>());
  const ebeneRef = (id: string) => {
    let f = rueckrufe.current.get(id);
    if (!f) {
      f = (el: HTMLDivElement | null) => {
        const m = elemente.current;
        const alt = m.get(id);
        if (alt) beobachter.current?.unobserve(alt);
        if (el) {
          m.set(id, el);
          beobachter.current?.observe(el);
        } else {
          m.delete(id);
          rueckrufe.current.delete(id);
        }
      };
      rueckrufe.current.set(id, f);
    }
    return f;
  };

  // Scrollrad: nur mit Auswahl; passive: false, damit preventDefault greift.
  const stand = useRef({ z, zoom, versteckt });
  stand.current = { z, zoom, versteckt };
  useEffect(() => {
    const el = buehne.current;
    if (!el) return;
    // drehen() rundet auf ganze Grad (20 px = 1 Grad); feine Touchpad-Schritte sammeln, sonst bewegt sich nichts.
    let rest = 0;
    const rad = (e: WheelEvent) => {
      const { z: zz, versteckt: aus } = stand.current;
      const id = zz.auswahl;
      // Nur mit sichtbarer Auswahl; Strg+Rad (Touchpad-Zoom) bleibt beim Browser.
      if (id === null || aus.has(id) || e.ctrlKey) return;
      e.preventDefault();
      const d = scrollPixel(e);
      if (!e.shiftKey) {
        zz.ebeneAendern(id, (eb) => skalieren(eb, d), 'gleiten');
        return;
      }
      rest += d;
      const schritt = Math.trunc(rest / 20) * 20;
      if (schritt === 0) return;
      rest -= schritt;
      zz.ebeneAendern(id, (eb) => drehen(eb, schritt), 'gleiten');
    };
    el.addEventListener('wheel', rad, { passive: false });
    return () => el.removeEventListener('wheel', rad);
  }, []);

  const sichtbar = g.ebenen.filter((e) => !versteckt.has(e.id));

  const runter = (ev: React.PointerEvent<HTMLDivElement>, e: Ebene) => {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    buehne.current?.focus({ preventScroll: true });
    // Ein wartender Scroll-/Tipp-Schritt wird jetzt sein eigener Schritt, nicht Teil des Ziehens.
    z.festschreiben();
    z.waehlen(e.id);
    ev.currentTarget.setPointerCapture(ev.pointerId);
    zug.current = { id: e.id, px: ev.clientX, py: ev.clientY, start: e, bewegt: false };
  };

  const ziehen = (ev: React.PointerEvent<HTMLDivElement>) => {
    const zg = zug.current;
    if (!zg || zoom === 0) return;
    const dxp = ev.clientX - zg.px;
    const dyp = ev.clientY - zg.py;
    if (!zg.bewegt && Math.hypot(dxp, dyp) < 3) return;
    zg.bewegt = true;
    let neu = schieben(zg.start, dxp / zoom, dyp / zoom);
    let l: Linie[] = [];
    if (!ev.altKey) {
      const andere = sichtbar.filter((o) => o.id !== zg.id);
      const r = einrasten(neu, masse[zg.id] ?? { w: 0, h: 0 }, andere, g.format, 6 / Math.max(zoom, 0.25));
      neu = { ...neu, x: r.x, y: r.y };
      l = r.linien;
    }
    const x = Math.round(neu.x * 10) / 10;
    const y = Math.round(neu.y * 10) / 10;
    z.ebeneAendern(zg.id, (e) => ({ ...e, x, y }), 'live');
    setLinien(l);
  };

  // Alt+Ziehen = frei schieben; Alt+Klick ohne Ziehen = Ebene als Kontext an den Chat (Spec 2026-10-06 §1).
  const los = (ev: React.PointerEvent<HTMLDivElement>) => {
    const zg = zug.current;
    if (zg?.bewegt) z.festschreiben();
    else if (zg && ev.altKey && ev.type === 'pointerup') {
      const flaeche = pultStore.getState().gestaltungOffen;
      if (flaeche !== null) ebeneAlsKontext(flaeche, zg.start);
    }
    zug.current = null;
    setLinien([]);
  };

  const rahmen = (id: string | null, stark: boolean) => {
    if (id === null) return null;
    const e = sichtbar.find((x) => x.id === id);
    const m = masse[id];
    if (!e || !m || zoom === 0) return null;
    const px = 1 / zoom;
    const griff = 8 / zoom;
    return (
      <div
        key={(stark ? 'a-' : 'h-') + id}
        style={{
          position: 'absolute',
          left: e.x,
          top: e.y,
          width: m.w,
          height: m.h,
          transform: `translate(-50%, -50%) rotate(${e.drehung}deg)`,
          outline: `${px}px solid ${stark ? FARBE.akzent : 'rgba(91,140,255,0.55)'}`,
          pointerEvents: 'none',
        }}
      >
        {stark &&
          [
            [0, 0],
            [1, 0],
            [0, 1],
            [1, 1],
          ].map(([gx, gy]) => (
            <div
              key={`${gx}${gy}`}
              style={{
                position: 'absolute',
                left: `calc(${gx * 100}% - ${griff / 2}px)`,
                top: `calc(${gy * 100}% - ${griff / 2}px)`,
                width: griff,
                height: griff,
                background: '#ffffff',
                border: `${px}px solid ${FARBE.akzent}`,
                borderRadius: 2 * px,
                boxSizing: 'border-box',
              }}
            />
          ))}
      </div>
    );
  };

  return (
    <Box
      ref={buehne}
      data-buehne
      tabIndex={-1}
      aria-label="Fläche"
      onPointerDown={() => {
        buehne.current?.focus({ preventScroll: true });
        z.waehlen(null);
      }}
      sx={{ position: 'relative', flex: 1, minHeight: 0, overflow: 'hidden', outline: 'none', bgcolor: FARBE.geruest, display: 'grid', placeItems: 'center', userSelect: 'none' }}
    >
      {zoom > 0 && (
        <div style={{ position: 'relative', width: BREITE * zoom, height: h * zoom, boxShadow: FLAECHE_SCHATTEN, borderRadius: 2 }}>
          <div style={{ position: 'absolute', left: 0, top: 0, width: BREITE, height: h, transform: `scale(${zoom})`, transformOrigin: '0 0' }}>
            <div style={{ position: 'absolute', inset: 0, background: g.hintergrund, transition: uebergang('background-color') }} />
            {sichtbar.map((e) => (
              <div
                key={e.id}
                ref={ebeneRef(e.id)}
                data-ebene={e.id}
                onPointerDown={(ev) => runter(ev, e)}
                onPointerMove={ziehen}
                onPointerUp={los}
                onPointerCancel={los}
                onPointerEnter={() => setHover(e.id)}
                onPointerLeave={() => setHover((x) => (x === e.id ? null : x))}
                onDoubleClick={() => e.art === 'text' && onTextBearbeiten(e.id)}
                style={{
                  position: 'absolute',
                  left: e.x,
                  top: e.y,
                  transform: `translate(-50%, -50%) rotate(${e.drehung}deg)`,
                  cursor: 'move',
                  touchAction: 'none',
                }}
              >
                <EbenenInhalt e={e} />
              </div>
            ))}
            {/* Ausserhalb der Flaeche abdunkeln: Anschnitt bleibt greifbar, liegt aber sichtbar "draussen". */}
            <div style={{ position: 'absolute', inset: 0, boxShadow: `0 0 0 100000px ${AUSSEN_MASKE}`, pointerEvents: 'none' }} />
            {hover !== auswahl && rahmen(hover, false)}
            {rahmen(auswahl, true)}
            {linien.map((l) => (
              <div
                key={l.achse + l.wert}
                style={{
                  position: 'absolute',
                  background: FARBE.akzent,
                  pointerEvents: 'none',
                  ...(l.achse === 'x'
                    ? { left: l.wert - 0.5 / zoom, top: 0, width: 1 / zoom, height: h }
                    : { top: l.wert - 0.5 / zoom, left: 0, height: 1 / zoom, width: BREITE }),
                }}
              />
            ))}
          </div>
        </div>
      )}
      <Box sx={{ position: 'absolute', right: 16, bottom: 12, fontSize: 11, color: FARBE.gedaempft, fontVariantNumeric: 'tabular-nums', pointerEvents: 'none' }}>
        {Math.round(zoom * 100)} %
      </Box>
    </Box>
  );
}

// Dezente Warnzeilen unter der Flaeche (Hinweise, keine Fehler). Feste Hoehe: nichts springt.
export function Hinweisleiste({ z, meldung }: { z: GestaltungZustand; meldung: React.ReactNode }) {
  const liste = hinweise(z.g);
  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{ height: 72, flexShrink: 0, overflowY: 'auto', px: 3, py: 1, display: 'grid', alignContent: 'start', gap: 0.5, bgcolor: FARBE.geruest }}
    >
      {meldung}
      {liste.map((t) => (
        <Box key={t} sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 12, color: FARBE.warnung, justifyContent: 'center' }}>
          <WarningAmberRounded sx={{ fontSize: 14 }} />
          {t}
        </Box>
      ))}
    </Box>
  );
}
