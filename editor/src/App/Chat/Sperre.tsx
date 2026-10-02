// Sperre waehrend der Agent (oder der Newsletter-Export am PC) arbeitet: Text der Sperre,
// Schreib-Indikator (drei Punkte im 150-ms-Takt) und die Schicht ueber gesperrten Bereichen.
import React, { useEffect, useRef, useState } from 'react';

import { Box } from '@mui/material';

import { sperrText } from '../../chat';
import { pultStore } from '../../pultZustand';
import { FARBE, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

// Text der Sperre, solange ein Auftrag offen ist (null = frei).
export function useAgentArbeitet(): string | null {
  return pultStore((p) => sperrText(p.chat));
}

const UNSICHTBAR = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  margin: '-1px',
  padding: 0,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

// Ansagen fuer Screenreader, einmal je Seite eingehaengt: Regionen sind von Anfang an da
// (leer) und werden erst gefuellt - so wird die Aenderung angesagt. Angesagt werden die Sperre
// und nur die jeweils neueste Antwort, die in dieser Sitzung fertig geworden ist.
export function Ansagen() {
  const sperre = useAgentArbeitet();
  const letzter = pultStore((p) => {
    const v = p.chat?.verlauf ?? [];
    return v.length > 0 ? v[v.length - 1] : null;
  });
  const [antwort, setAntwort] = useState('');
  const vorher = useRef<{ id: string; lief: boolean } | null>(null);
  useEffect(() => {
    if (!letzter) return;
    const lief = letzter.status === 'offen' || letzter.status === 'in_arbeit';
    const war = vorher.current;
    if (war && war.id === letzter.id && war.lief && !lief) {
      setAntwort(letzter.antwort || (letzter.status === 'fehler' ? 'Das hat nicht geklappt.' : 'Erledigt.'));
    }
    vorher.current = { id: letzter.id, lief };
  }, [letzter]);
  return (
    <>
      <Box role="status" aria-live="polite" sx={UNSICHTBAR}>
        {sperre ?? ''}
      </Box>
      <Box aria-live="polite" sx={UNSICHTBAR}>
        {antwort}
      </Box>
    </>
  );
}

// Drei Punkte, je 150 ms hell (Schreib-Indikator).
export function Punkte({ farbe = FARBE.gedaempft }: { farbe?: string }) {
  return (
    <Box
      component="span"
      aria-hidden="true"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        height: 16,
        '@keyframes chatPunkt': { '0%': { opacity: 1 }, '33.333%': { opacity: 0.3 } },
        '& > span': { width: 6, height: 6, borderRadius: '50%', bgcolor: farbe, opacity: 0.3, animation: 'chatPunkt 450ms steps(1, end) infinite' },
        '& > span:nth-of-type(2)': { animationDelay: '150ms' },
        '& > span:nth-of-type(3)': { animationDelay: '300ms' },
        '@media (prefers-reduced-motion: reduce)': { '& > span': { animation: 'none', opacity: 0.6 } },
      }}
    >
      <span />
      <span />
      <span />
    </Box>
  );
}

// Legt sich ueber gesperrte Bereiche (Canvas, Flaeche); lage = Position des Aufrufers.
export function SperrSchicht({ text, lage }: { text: string; lage: React.CSSProperties }) {
  return (
    <Box
      aria-hidden="true"
      style={lage}
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'rgba(15,15,17,0.55)',
        backdropFilter: 'blur(2px)',
        cursor: 'progress',
        '@keyframes sperreAuf': { from: { opacity: 0 }, to: { opacity: 1 } },
        animation: 'sperreAuf 150ms ease-out',
        '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2,
          height: 40,
          borderRadius: '20px',
          bgcolor: FARBE.panel,
          border: `1px solid ${FARBE.linie}`,
          color: FARBE.text,
          fontFamily: UI_SCHRIFT,
          fontSize: 13,
          fontWeight: 500,
          boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
        }}
      >
        <Punkte farbe={FARBE.akzent} />
        {text}
      </Box>
    </Box>
  );
}
