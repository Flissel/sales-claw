// Sperre waehrend der Agent (oder der Newsletter-Export am PC) arbeitet: Text der Sperre,
// Schreib-Indikator (drei Punkte im 150-ms-Takt) und die Schicht ueber gesperrten Bereichen.
// Im Chat-Lauf ist die Schicht durchsichtig: man sieht dem Agenten zu (Live-Ansicht), eine
// ruhige Schritt-Zeile unten nennt, was er gerade tut.
import React, { useEffect, useRef, useState } from 'react';

import { Box } from '@mui/material';

import { laufendeRunden, sperrText } from '../../chat';
import { schrittText } from '../../live';
import { LIEGT_ZUR_FREIGABE as LIEGT, pultStore } from '../../pultZustand';
import { FARBE, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

// Text der Sperre, solange ein Auftrag offen ist (null = frei).
export function useAgentArbeitet(): string | null {
  return pultStore((p) => sperrText(p.chat));
}

// Liegt zur Freigabe: der Editor ist nur lesend (Zurueckziehen hebt es auf).
export const LIEGT_ZUR_FREIGABE = LIEGT;
export function useNurLesen(): boolean {
  return pultStore((p) => p.nurLesen);
}

// Gesperrt, wenn der Agent arbeitet ODER der Newsletter zur Freigabe liegt. Beide Hooks laufen immer
// (nie in `||`/`&&` aufrufen - sonst aendert sich die Hook-Reihenfolge zwischen den Renderings).
export function useGesperrt(): boolean {
  const arbeitet = useAgentArbeitet();
  const nurLesen = useNurLesen();
  return arbeitet !== null || nurLesen;
}

// Schrittzeile der Sperrschicht (null = keine Chat-Runde laeuft, z. B. Export). Bei mehreren Runden die Anzahl.
export function useLiveZeile(): string | null {
  return pultStore((p) => {
    const runden = laufendeRunden(p.chat).filter((e) => e.status !== 'wartet');
    if (runden.length === 0) return null;
    if (p.chatGetrennt) return 'Verbindung …';
    if (runden.length > 1) return `${runden.length} Runden laufen …`;
    const r = runden[0];
    if (r.stopp) return 'Wird gestoppt …';
    return schrittText(r) ?? (r.status === 'offen' ? 'Wartet auf den Assistenten …' : 'Agent denkt nach …');
  });
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
  const live = useLiveZeile();
  const arbeitet = useAgentArbeitet();
  const sperre = live ?? arbeitet;
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

// Die Schicht laesst Rad, Touch und Klicks durch: gesperrt wird der Inhalt per inert, die
// Scroll-Rahmen darunter bleiben scrollbar. Nur sie selbst ist fuer Zeiger unsichtbar.
export function schichtLage(lage: React.CSSProperties): React.CSSProperties {
  return { ...lage, pointerEvents: 'none' };
}

// Legt sich ueber gesperrte Bereiche (Canvas, Flaeche); lage = Position des Aufrufers.
// Im Chat-Lauf durchsichtig mit der Schritt-Zeile unten, sonst abgedunkelt mit dem Text in der Mitte.
export function SperrSchicht({ text, lage }: { text: string; lage: React.CSSProperties }) {
  const live = useLiveZeile();
  if (live !== null) {
    return (
      <Box aria-hidden="true" style={schichtLage(lage)} sx={{ cursor: 'default' }}>
        <Box
          sx={{
            position: 'absolute',
            left: '50%',
            bottom: 24,
            transform: 'translateX(-50%)',
            maxWidth: 'calc(100% - 48px)',
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
            boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
            '@keyframes zeileAuf': { from: { opacity: 0, transform: 'translate(-50%, 8px)' }, to: { opacity: 1, transform: 'translate(-50%, 0)' } },
            animation: 'zeileAuf 240ms cubic-bezier(0.2, 0, 0, 1)',
            '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
          }}
        >
          <Punkte farbe={FARBE.akzent} />
          <Box
            key={live}
            component="span"
            sx={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              '@keyframes zeileText': { from: { opacity: 0 }, to: { opacity: 1 } },
              animation: 'zeileText 200ms ease-out',
              '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
            }}
          >
            {live}
          </Box>
        </Box>
      </Box>
    );
  }
  return (
    <Box
      aria-hidden="true"
      style={schichtLage(lage)}
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
