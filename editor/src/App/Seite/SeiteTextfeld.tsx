// Textfeld genau ueber einer Text- oder Knopf-Ebene (Doppelklick auf der Flaeche): gleiche Lage,
// Drehung und Schrift wie die Ebene. Strg+Enter oder ein Klick daneben uebernimmt, Esc verwirft.
import React, { useEffect, useRef, useState } from 'react';

import type { KnopfEbeneS, Seite, TextEbeneS } from '../../seite';
import { FARBE } from '../Gestaltung/gestaltungStil';

import { aussehen } from './seiteStil';

type Props = {
  seite: Seite;
  e: TextEbeneS | KnopfEbeneS;
  hoehe: number;
  rand: number;
  // null = verworfen
  fertig: (text: string | null) => void;
};

export default function SeiteTextfeld({ seite, e, hoehe, rand, fertig }: Props) {
  const [text, setText] = useState(e.text);
  const feld = useRef<HTMLTextAreaElement | null>(null);
  const erledigt = useRef(false);
  useEffect(() => {
    feld.current?.focus();
    feld.current?.select();
  }, []);

  const ende = (wert: string | null) => {
    if (erledigt.current) return;
    erledigt.current = true;
    // Ein Knopf hat eine Zeile; leerer Text wird nicht uebernommen.
    const t = wert === null ? null : e.art === 'knopf' ? wert.replace(/\s*\n\s*/g, ' ') : wert;
    fertig(t !== null && t.trim() !== '' ? t : null);
  };

  const stil = aussehen(seite, e, 10);
  return (
    <textarea
      ref={feld}
      aria-label="Text bearbeiten"
      value={text}
      onChange={(ev) => setText(ev.target.value)}
      onPointerDown={(ev) => ev.stopPropagation()}
      onBlur={() => ende(text)}
      onKeyDown={(ev) => {
        if (ev.key === 'Escape') {
          ev.preventDefault();
          ende(null);
        } else if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
          ev.preventDefault();
          ende(text);
        }
      }}
      style={{
        ...stil,
        height: hoehe,
        minHeight: undefined,
        opacity: undefined,
        display: 'block',
        margin: 0,
        padding: 0,
        border: 'none',
        resize: 'none',
        overflow: 'hidden',
        outline: `${2 * rand}px solid ${FARBE.akzent}`,
        background: stil.background ?? 'transparent',
        // Knopf: eine Zeile, senkrecht mittig wie im Knopf.
        lineHeight: e.art === 'knopf' ? `${hoehe}px` : stil.lineHeight,
        whiteSpace: e.art === 'knopf' ? 'nowrap' : 'pre-wrap',
        userSelect: 'text',
        pointerEvents: 'auto',
      }}
    />
  );
}
