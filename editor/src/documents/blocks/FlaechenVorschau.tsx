// Live-Ansicht (Spec 2026-10-02-newsletter-agent-live §2.3): eine Gestaltungsflaeche, die der
// Agent im laufenden Zwischenstand veraendert hat, erscheint im Canvas als DOM-Vorschau - gleiche
// Darstellung wie im Gestaltungsfenster. Das Serverbild kommt erst mit der Fassung.
import React, { useLayoutEffect, useRef, useState } from 'react';

import { EbenenInhalt } from '../../App/Gestaltung/Flaeche';
import { BREITE, Gestaltung, hoehe } from '../../gestaltung';
import { gleich } from '../../live';
import { pultStore } from '../../pultZustand';
import { GestaltungSchema, ImageDaten } from '../../schemata';
import { useCurrentBlockId } from '../editor/EditorBlock';

import { VorlagenImage } from './Vorlagentext';

function polster(p: { top: number; right: number; bottom: number; left: number } | null | undefined): string | undefined {
  return p ? `${p.top}px ${p.right}px ${p.bottom}px ${p.left}px` : undefined;
}

function Vorschau({ g, daten }: { g: Gestaltung; daten: ImageDaten }) {
  const rahmen = useRef<HTMLDivElement>(null);
  const [breite, setBreite] = useState(0);
  useLayoutEffect(() => {
    const el = rahmen.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBreite(el.clientWidth));
    ro.observe(el);
    setBreite(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const h = hoehe(g.format);
  const style = daten.style;
  const w = daten.props?.width;
  return (
    <div style={{ padding: polster(style?.padding), backgroundColor: style?.backgroundColor ?? undefined, textAlign: style?.textAlign ?? undefined }}>
      <div
        ref={rahmen}
        role="img"
        aria-label={daten.props?.alt ?? ''}
        style={{
          display: 'inline-block',
          verticalAlign: 'middle',
          position: 'relative',
          overflow: 'hidden',
          width: typeof w === 'number' && w > 0 ? w : '100%',
          maxWidth: '100%',
          aspectRatio: `${BREITE} / ${h}`,
        }}
      >
        {breite > 0 && (
          <div style={{ position: 'absolute', left: 0, top: 0, width: BREITE, height: h, transform: `scale(${breite / BREITE})`, transformOrigin: '0 0', background: g.hintergrund }}>
            {g.ebenen.map((e) => (
              <div key={e.id} style={{ position: 'absolute', left: e.x, top: e.y, transform: `translate(-50%, -50%) rotate(${e.drehung}deg)` }}>
                <EbenenInhalt e={e} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Bild-Block im Canvas: waehrend eines Zwischenstands eine vom Agenten geaenderte Flaeche als
// Vorschau, sonst das Bild wie immer.
export default function BildOderVorschau(daten: ImageDaten) {
  const id = useCurrentBlockId();
  const roh = daten.props?.gestaltung;
  const geaendert = pultStore((p) => {
    const echt = p.zwischenstand?.echt[id];
    if (!p.zwischenstand || !roh) return false;
    const vorher = echt?.type === 'Image' ? echt.data.props?.gestaltung : undefined;
    return !gleich(vorher ?? null, roh);
  });
  const g = geaendert ? GestaltungSchema.safeParse(roh) : null;
  if (g?.success) return <Vorschau g={g.data as Gestaltung} daten={daten} />;
  return <VorlagenImage {...daten} />;
}
