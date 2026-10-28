// Fester Fuss unter der Seite (Newsletter-Runde 28.10.2026): Impressum, Vermittlerangaben und Abmeldehinweis
// der Marke, wie Uebersicht und PDF sie zeigen (claw/seite_html.py). Nicht verschiebbar, nicht bearbeitbar -
// gepflegt wird er an der Marke. So sieht man im Editor, was wirklich mit rausgeht.
import React from 'react';

import type { Seite } from '../../seite';
import { familieFuer } from '../../seite';

export type Pflichtteil = { impressum: string; abmelde_hinweis: string; vermittlerangaben: string };

export const IMPRESSUM_FEHLT = 'Impressum fehlt – in der Marke hinterlegen';

// Wie seite_html._fuss_farbe: auf hellem Grund grau, auf dunklem weiss.
export function fussFarbe(hintergrund: string): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hintergrund.trim());
  if (!m) return '#666666';
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.35 ? '#ffffff' : '#666666';
}

export default function SeitenFuss({ s, p, zoom }: { s: Seite; p: Pflichtteil; zoom: number }) {
  const impressum = p.impressum.trim();
  const vermittler = p.vermittlerangaben.trim();
  const hinweis = p.abmelde_hinweis.replace(/\{abmeldelink\}/g, '[Abmeldelink]').trim();
  return (
    <div
      aria-label="Impressum (fest, aus der Marke)"
      title="Kommt aus der Marke und geht so mit raus – ändern unter Marketing → Marke"
      style={{
        width: s.breite * zoom, margin: `0 auto ${24 * zoom}px`, padding: `${16 * zoom}px 0`, boxSizing: 'border-box',
        textAlign: 'center', fontSize: 11 * zoom, lineHeight: 1.5, whiteSpace: 'pre-line', userSelect: 'none',
        color: fussFarbe(s.hintergrund.farbe), background: s.hintergrund.farbe, fontFamily: familieFuer('TEXT', s),
      }}
    >
      {impressum ? <div>{impressum}</div> : <strong style={{ color: '#ef4444' }}>{IMPRESSUM_FEHLT}</strong>}
      {vermittler && <div>{vermittler}</div>}
      {hinweis && <div>{hinweis}</div>}
    </div>
  );
}
