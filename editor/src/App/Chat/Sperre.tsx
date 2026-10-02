// Sperre waehrend der Agent (oder der Newsletter-Export am PC) arbeitet: Text der Sperre,
// Schreib-Indikator (drei Punkte im 150-ms-Takt) und die Schicht ueber gesperrten Bereichen.
import React from 'react';

import { Box } from '@mui/material';

import type { ChatEintrag } from '../../chat';
import { pultStore } from '../../pultZustand';
import { FARBE, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

const laeuftNoch = (e: ChatEintrag) => e.status === 'offen' || e.status === 'in_arbeit';

// Text der Sperre, solange ein Auftrag offen ist (null = frei).
export function useAgentArbeitet(): string | null {
  return pultStore((p) => {
    if (!p.chat?.laeuft) return null;
    return p.chat.verlauf.some((e) => e.art === 'export' && laeuftNoch(e)) ? 'Newsletter-Bilder werden gerechnet …' : 'Agent arbeitet …';
  });
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
      role="status"
      aria-live="polite"
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
