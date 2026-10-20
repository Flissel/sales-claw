// Linke Spalte der Collage: Ebenen von oben nach unten (oberste zuerst), auswaehlen, nach oben/unten,
// loeschen; "Text", "Bild", "Form", "Knopf" fuegen hinzu (Bild ueber die Medienauswahl des
// Gestaltungsfensters), gesperrt bei 80 Ebenen.
import React, { useState } from 'react';

import { ArrowDownwardRounded, ArrowUpwardRounded, DeleteOutlineRounded } from '@mui/icons-material';
import { Box, Button, ButtonBase, IconButton, Typography } from '@mui/material';

import { MAX_EBENEN, neueEbene, type SeitenEbene } from '../../seite';
import { Medienauswahl } from '../Gestaltung/EbenenListe';
import { FARBE, FOKUS, ZEILE_HOEHE, uebergang } from '../Gestaltung/gestaltungStil';
import { quelleAnzeige } from '../Gestaltung/hilfen';

import type { SeiteZustand } from './useSeite';

export const VOLL_HINWEIS = `Höchstens ${MAX_EBENEN} Ebenen`;

export function ebenenName(e: SeitenEbene): string {
  if (e.art === 'bild') return e.quelle.replace(/^medien:/, '').replace(/\.[a-z]+$/i, '') || 'Bild';
  if (e.art === 'form') return e.form === 'kreis' ? 'Kreis' : 'Rechteck';
  const zeile = e.text.split('\n')[0].replace(/[*[\]]/g, '').trim();
  const kurz = [...zeile].length > 28 ? `${[...zeile].slice(0, 27).join('')}…` : zeile;
  return e.art === 'knopf' ? `Knopf: ${kurz}` : kurz || 'Text';
}

function Symbol({ e }: { e: SeitenEbene }) {
  const box = { width: 24, height: 24, borderRadius: '4px', flexShrink: 0, bgcolor: FARBE.feld } as const;
  if (e.art === 'bild') return <Box component="img" src={quelleAnzeige(e.quelle)} alt="" draggable={false} sx={{ ...box, objectFit: 'cover' }} />;
  if (e.art === 'form') {
    return (
      <Box sx={{ ...box, display: 'grid', placeItems: 'center' }}>
        <Box sx={{ width: 14, height: 14, bgcolor: e.farbe, borderRadius: e.form === 'kreis' ? '50%' : '3px' }} />
      </Box>
    );
  }
  if (e.art === 'knopf') {
    return (
      <Box sx={{ ...box, display: 'grid', placeItems: 'center' }}>
        <Box sx={{ width: 18, height: 10, bgcolor: e.farbe, borderRadius: '3px' }} />
      </Box>
    );
  }
  return <Box sx={{ ...box, display: 'grid', placeItems: 'center', color: FARBE.text, fontSize: 13 }}>Aa</Box>;
}

export default function SeiteEbenen({ z }: { z: SeiteZustand }) {
  const { seite: s, auswahl } = z;
  const [anker, setAnker] = useState<HTMLElement | null>(null);
  const voll = s.ebenen.length >= MAX_EBENEN;
  const liste = [...s.ebenen].reverse();
  const neu = (art: SeitenEbene['art']) => z.hinzufuegen(neueEbene(art, z.aktuell()));

  return (
    <Box>
      <Box sx={{ px: 2, pt: 2, pb: 1 }}>
        <Typography component="h3" sx={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft, mb: 1 }}>
          Hinzufügen
        </Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 1 }}>
          <Button variant="outlined" color="inherit" disabled={voll} onClick={() => neu('text')}>Text</Button>
          <Button variant="outlined" color="inherit" disabled={voll} onClick={(ev) => setAnker(ev.currentTarget)}>Bild</Button>
          <Button variant="outlined" color="inherit" disabled={voll} onClick={() => neu('form')}>Form</Button>
          <Button variant="outlined" color="inherit" disabled={voll} onClick={() => neu('knopf')}>Knopf</Button>
        </Box>
        {voll && <Typography role="status" sx={{ mt: 1, fontSize: 12, color: FARBE.warnung }}>{VOLL_HINWEIS}</Typography>}
      </Box>
      <Medienauswahl
        anker={anker}
        schliessen={() => setAnker(null)}
        waehlen={(name, verhaeltnis) => {
          setAnker(null);
          const e = neueEbene('bild', z.aktuell(), `medien:${name}`);
          z.hinzufuegen(verhaeltnis ? { ...e, hoehe: Math.round(e.breite / verhaeltnis) } : e);
        }}
      />
      <Typography component="h3" sx={{ px: 2, pt: 2, pb: 1, fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft }}>
        Ebenen ({s.ebenen.length})
      </Typography>
      <Box component="ul" aria-label="Ebenen" sx={{ listStyle: 'none', m: 0, p: 0, pb: 2 }}>
        {liste.map((e) => {
          const index = s.ebenen.indexOf(e);
          const an = e.id === auswahl;
          return (
            <Box component="li" key={e.id} sx={{ display: 'flex', alignItems: 'center', height: ZEILE_HOEHE, px: 1, bgcolor: an ? 'action.selected' : 'transparent', transition: uebergang('background-color'), '&:hover': { bgcolor: an ? 'action.selected' : FARBE.hover }, '&:hover .ebene-knoepfe, &:focus-within .ebene-knoepfe': { opacity: 1 } }}>
              <ButtonBase
                data-tasten
                aria-pressed={an}
                onClick={() => z.waehlen(e.id)}
                sx={{ flex: 1, minWidth: 0, height: '100%', justifyContent: 'flex-start', gap: 1, px: 1, borderRadius: '6px', '&.Mui-focusVisible': FOKUS }}
              >
                <Symbol e={e} />
                <Typography noWrap sx={{ fontSize: 13, color: FARBE.text }}>{ebenenName(e)}</Typography>
              </ButtonBase>
              <Box className="ebene-knoepfe" sx={{ display: 'flex', opacity: an ? 1 : 0.35, transition: uebergang('opacity') }}>
                <IconButton size="small" aria-label="Nach oben" disabled={index === s.ebenen.length - 1} onClick={() => z.nachOben(e.id)}>
                  <ArrowUpwardRounded sx={{ fontSize: 16 }} />
                </IconButton>
                <IconButton size="small" aria-label="Nach unten" disabled={index === 0} onClick={() => z.nachUnten(e.id)}>
                  <ArrowDownwardRounded sx={{ fontSize: 16 }} />
                </IconButton>
                <IconButton size="small" aria-label="Löschen" onClick={() => z.loeschen(e.id)}>
                  <DeleteOutlineRounded sx={{ fontSize: 16 }} />
                </IconButton>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
