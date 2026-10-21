// Befunde der Schönheitsprüfung (Freie Fläche Stufe 5) in der rechten Spalte: harte Befunde (blockieren das
// Einreichen) in der Fehlerfarbe, weiche (Hinweise) gedämpft. Ein Klick auf einen Befund wählt seine Ebene,
// wenn es sie auf der Seite gibt; Befunde zur ganzen Seite ("seite") sind nur Text.
import React from 'react';

import { CloseRounded } from '@mui/icons-material';
import { Box, ButtonBase, CircularProgress, IconButton, Typography } from '@mui/material';

import type { Befund } from '../../pult';
import { FARBE, FOKUS, uebergang } from '../Gestaltung/gestaltungStil';

// fassung: die geprüfte Fassung (die Liste nennt sie; ist die Seite seither anders, sagt sie es).
export type PruefStand =
  | { art: 'laedt' }
  | { art: 'befunde'; befunde: Befund[]; fassung: number }
  | { art: 'fehler'; grund: string };

export const KEINE_BEFUNDE = 'Keine Befunde – die Collage kann eingereicht werden.';

export function veraltetText(fassung: number): string {
  return `Die Seite wurde seither geändert – die Befunde gelten für Fassung ${fassung}. Bitte erneut prüfen.`;
}

// Gelten die Befunde nicht mehr für das, was man sieht? (ungespeichert oder inzwischen eine andere Fassung)
export function befundeVeraltet(stand: PruefStand, ungespeichert: boolean, basis: number): boolean {
  return stand.art === 'befunde' && (ungespeichert || stand.fassung !== basis);
}

// "2 harte, 1 Hinweis" - leer, wenn es nichts gibt.
export function befundZusammenfassung(befunde: Befund[]): string {
  const hart = befunde.filter((b) => b.schwere === 'hart').length;
  const weich = befunde.length - hart;
  const teile = [
    hart > 0 ? `${hart} ${hart === 1 ? 'harter Befund' : 'harte Befunde'}` : '',
    weich > 0 ? `${weich} ${weich === 1 ? 'Hinweis' : 'Hinweise'}` : '',
  ].filter(Boolean);
  return teile.join(', ');
}

// Harte zuerst, sonst in der Reihenfolge der Prüfung.
export function befundeOrdnen(befunde: Befund[]): Befund[] {
  return [...befunde.filter((b) => b.schwere === 'hart'), ...befunde.filter((b) => b.schwere !== 'hart')];
}

type Props = {
  stand: PruefStand;
  veraltet: boolean;
  ebenen: ReadonlySet<string>;
  onWaehlen: (id: string) => void;
  onSchliessen: () => void;
};

export default function SeitePruefung({ stand, veraltet, ebenen, onWaehlen, onSchliessen }: Props) {
  return (
    <Box component="section" aria-label="Prüfung" sx={{ px: 2, pt: 2, pb: 1.5, borderBottom: `1px solid ${FARBE.linie}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Typography component="h3" sx={{ flex: 1, fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft }}>
          {stand.art === 'befunde' ? `Prüfung · Fassung ${stand.fassung}` : 'Prüfung'}
        </Typography>
        <IconButton size="small" aria-label="Prüfung schließen" onClick={onSchliessen}>
          <CloseRounded sx={{ fontSize: 16 }} />
        </IconButton>
      </Box>
      {stand.art === 'laedt' && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: FARBE.gedaempft, fontSize: 13 }}>
          <CircularProgress size={14} color="inherit" /> Wird geprüft …
        </Box>
      )}
      {stand.art === 'befunde' && veraltet && (
        <Typography data-veraltet="" sx={{ fontSize: 12, color: FARBE.fehler, mb: 1 }}>
          {veraltetText(stand.fassung)}
        </Typography>
      )}
      {stand.art === 'fehler' && <Typography sx={{ fontSize: 13, color: FARBE.fehler }}>{stand.grund}</Typography>}
      {stand.art === 'befunde' && stand.befunde.length === 0 && (
        <Typography sx={{ fontSize: 13, color: FARBE.text }}>{KEINE_BEFUNDE}</Typography>
      )}
      {stand.art === 'befunde' && stand.befunde.length > 0 && (
        <>
          <Typography sx={{ fontSize: 12, color: FARBE.gedaempft, mb: 1 }}>{befundZusammenfassung(stand.befunde)}</Typography>
          <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'grid', gap: 0.5 }}>
            {befundeOrdnen(stand.befunde).map((b, i) => {
              const farbe = b.schwere === 'hart' ? FARBE.fehler : FARBE.gedaempft;
              const zeile = { display: 'block', width: '100%', textAlign: 'left', fontSize: 13, lineHeight: 1.4, color: farbe, px: 1, py: 0.5, borderRadius: '4px' } as const;
              return (
                <li key={i} data-befund={b.schwere}>
                  {ebenen.has(b.punkt) ? (
                    <ButtonBase
                      onClick={() => onWaehlen(b.punkt)}
                      title="Ebene auswählen"
                      sx={{ ...zeile, fontFamily: 'inherit', transition: uebergang('background-color'), '&:hover': { bgcolor: FARBE.hover }, '&.Mui-focusVisible': FOKUS }}
                    >
                      {b.satz}
                    </ButtonBase>
                  ) : (
                    <Box sx={zeile}>{b.satz}</Box>
                  )}
                </li>
              );
            })}
          </Box>
        </>
      )}
    </Box>
  );
}
