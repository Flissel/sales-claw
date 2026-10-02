// Linke Spalte: Ebenen (oberste zuerst), Umsortieren per Ziehen, Auge, Loeschen,
// "+ Bild" (Medienauswahl, freigestellte zuerst) und "+ Text".
import React, { useEffect, useState } from 'react';

import { AddPhotoAlternateOutlined, DeleteOutlineRounded, TextFieldsRounded, VisibilityOffOutlined, VisibilityOutlined } from '@mui/icons-material';
import { Box, Button, ButtonBase, IconButton, Popover, Tooltip, Typography } from '@mui/material';

import { getDocument } from '../../documents/editor/EditorContext';
import { Ebene, neueId } from '../../gestaltung';
import { ANZEIGE } from '../../pult';
import { medienLaden, pultStore } from '../../pultZustand';
import { SCHRIFT_FAMILIE } from '../../schemata';

import { ebenenName, istFreigestellt, medienFuerEbenen, neueBildEbene, neueTextEbene, quelleAnzeige } from './hilfen';
import { FARBE, FOKUS, SCHACHBRETT, ZEILE_HOEHE, uebergang } from './gestaltungStil';
import type { GestaltungZustand } from './useGestaltung';

const MAX_EBENEN = 20;
const DRAG_TYP = 'application/x-vibemind-ebene';

type Props = {
  z: GestaltungZustand;
  versteckt: Set<string>;
  umschalten: (id: string) => void;
};

function Vorschau({ e }: { e: Ebene }) {
  const box = { width: 24, height: 24, borderRadius: '4px', flexShrink: 0 } as const;
  if (e.art === 'bild') {
    return <Box component="img" src={quelleAnzeige(e.quelle)} alt="" draggable={false} sx={{ ...box, ...SCHACHBRETT, backgroundSize: '6px 6px', objectFit: 'cover' }} />;
  }
  return (
    <Box sx={{ ...box, display: 'grid', placeItems: 'center', bgcolor: FARBE.feld, color: FARBE.text, fontFamily: SCHRIFT_FAMILIE[e.schrift], fontSize: 14, lineHeight: 1 }}>
      Aa
    </Box>
  );
}

function Medienauswahl({ anker, schliessen, waehlen }: { anker: HTMLElement | null; schliessen: () => void; waehlen: (name: string, verhaeltnis?: number) => void }) {
  const medien = pultStore((p) => p.medien);
  useEffect(() => {
    if (anker) medienLaden(true);
  }, [anker]);
  const liste = medienFuerEbenen(medien ?? []);
  const gruppen: Array<[string, string[]]> = [
    ['Freigestellt', liste.filter(istFreigestellt)],
    ['Medien', liste.filter((n) => !istFreigestellt(n))],
  ];
  return (
    <Popover
      open={anker !== null}
      anchorEl={anker}
      onClose={schliessen}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
      slotProps={{ paper: { sx: { mt: 1, width: 344, maxHeight: 440, p: 2, bgcolor: FARBE.panel } } }}
    >
      <Typography sx={{ fontSize: 13, fontWeight: 600, mb: 0.5 }}>Bild aus den Medien</Typography>
      <Typography sx={{ fontSize: 12, color: FARBE.gedaempft, mb: 2 }}>Freigestellte Bilder liegen ohne Hintergrund auf der Fläche.</Typography>
      {medien === null && <Typography sx={{ fontSize: 12, color: FARBE.gedaempft }}>Medien werden geladen …</Typography>}
      {medien !== null && liste.length === 0 && (
        <Typography sx={{ fontSize: 12, color: FARBE.gedaempft }}>Keine Bilder in den Medien. Bilder im Pult unter Medien hochladen.</Typography>
      )}
      {gruppen.map(([titel, namen]) =>
        namen.length === 0 ? null : (
          <Box key={titel} sx={{ mb: 2 }}>
            <Typography sx={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft, mb: 1 }}>
              {titel}
            </Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1 }}>
              {namen.map((n) => (
                <ButtonBase
                  key={n}
                  title={n}
                  aria-label={`${n} einfügen`}
                  onClick={(ev) => {
                    const img = ev.currentTarget.querySelector('img');
                    const v = img && img.naturalHeight > 0 ? img.naturalWidth / img.naturalHeight : undefined;
                    waehlen(n, v);
                  }}
                  sx={{
                    aspectRatio: '1 / 1',
                    borderRadius: '6px',
                    overflow: 'hidden',
                    ...(istFreigestellt(n) ? SCHACHBRETT : { bgcolor: FARBE.feld }),
                    boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.06)',
                    transition: uebergang('box-shadow', 'transform'),
                    '&:hover': { boxShadow: `0 0 0 2px ${FARBE.akzent}` },
                    '&.Mui-focusVisible': FOKUS,
                  }}
                >
                  <Box
                    component="img"
                    src={ANZEIGE + encodeURIComponent(n)}
                    alt=""
                    loading="lazy"
                    sx={{ width: '100%', height: '100%', objectFit: istFreigestellt(n) ? 'contain' : 'cover', display: 'block' }}
                  />
                </ButtonBase>
              ))}
            </Box>
          </Box>
        )
      )}
    </Popover>
  );
}

export default function EbenenListe({ z, versteckt, umschalten }: Props) {
  const { g, auswahl } = z;
  const [anker, setAnker] = useState<HTMLElement | null>(null);
  const [gezogen, setGezogen] = useState<number | null>(null);
  const [ziel, setZiel] = useState<number | null>(null); // Einfuegestelle in der Liste (0 = ganz oben)
  const n = g.ebenen.length;
  const liste = [...g.ebenen].reverse();
  const voll = n >= MAX_EBENEN;
  const ids = () => g.ebenen.map((e) => e.id);

  const fallen = () => {
    if (gezogen !== null && ziel !== null) {
      const p = gezogen < ziel ? ziel - 1 : ziel;
      if (p !== gezogen) z.verschieben(n - 1 - gezogen, n - 1 - p);
    }
    setGezogen(null);
    setZiel(null);
  };

  return (
    <Box component="aside" aria-label="Ebenen" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <Box sx={{ px: 2, pt: 2, pb: 1.5, display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Typography component="h2" sx={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft }}>
          Ebenen
        </Typography>
        <Typography sx={{ fontSize: 11, color: FARBE.gedaempft, fontVariantNumeric: 'tabular-nums' }}>
          {n}/{MAX_EBENEN}
        </Typography>
      </Box>
      <Box sx={{ px: 2, pb: 2, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
        <Button variant="outlined" color="inherit" disabled={voll} startIcon={<AddPhotoAlternateOutlined sx={{ fontSize: 16 }} />} onClick={(e) => setAnker(e.currentTarget)} sx={{ borderColor: FARBE.linie, color: FARBE.text }}>
          Bild
        </Button>
        <Button
          variant="outlined"
          color="inherit"
          disabled={voll}
          startIcon={<TextFieldsRounded sx={{ fontSize: 16 }} />}
          onClick={() => z.ebeneHinzufuegen(neueTextEbene(neueId(ids()), z.aktuell(), getDocument().root))}
          sx={{ borderColor: FARBE.linie, color: FARBE.text }}
        >
          Text
        </Button>
      </Box>
      <Medienauswahl
        anker={anker}
        schliessen={() => setAnker(null)}
        waehlen={(name, v) => {
          setAnker(null);
          z.ebeneHinzufuegen(neueBildEbene(neueId(ids()), z.aktuell(), name, v));
        }}
      />

      <Box
        role="list"
        sx={{ flex: 1, minHeight: 0, overflowY: 'auto', px: 1, pb: 2, borderTop: `1px solid ${FARBE.linie}`, pt: 1 }}
        onDragOver={(ev) => {
          if (gezogen !== null) ev.preventDefault();
        }}
        onDrop={(ev) => {
          ev.preventDefault();
          fallen();
        }}
      >
        {n === 0 && (
          <Typography sx={{ fontSize: 12, color: FARBE.gedaempft, px: 1, py: 2, lineHeight: 1.6 }}>
            Noch leer. Füge ein Bild oder einen Text hinzu – danach ziehen, scrollen und drehen direkt auf der Fläche.
          </Typography>
        )}
        {liste.map((e, i) => {
          const an = e.id === auswahl;
          const aus = versteckt.has(e.id);
          return (
            <Box
              key={e.id}
              role="listitem"
              draggable
              onDragStart={(ev) => {
                ev.dataTransfer.effectAllowed = 'move';
                ev.dataTransfer.setData(DRAG_TYP, e.id);
                setGezogen(i);
              }}
              onDragOver={(ev) => {
                if (gezogen === null) return;
                ev.preventDefault();
                const r = ev.currentTarget.getBoundingClientRect();
                setZiel(ev.clientY < r.top + r.height / 2 ? i : i + 1);
              }}
              onDragEnd={() => {
                setGezogen(null);
                setZiel(null);
              }}
              sx={{ position: 'relative' }}
            >
              {ziel !== null && gezogen !== null && (ziel === i || (ziel === i + 1 && i === liste.length - 1)) && (
                <Box sx={{ position: 'absolute', left: 8, right: 8, height: 2, borderRadius: 1, bgcolor: FARBE.akzent, top: ziel === i ? -1 : 'auto', bottom: ziel === i ? 'auto' : -1, zIndex: 1 }} />
              )}
              <Box
                tabIndex={0}
                aria-selected={an}
                onClick={() => z.waehlen(e.id)}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    z.waehlen(e.id);
                  }
                }}
                sx={{
                  height: ZEILE_HOEHE,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  pl: 1,
                  pr: 0.5,
                  borderRadius: '6px',
                  cursor: 'grab',
                  opacity: gezogen === i ? 0.4 : 1,
                  bgcolor: an ? 'rgba(91,140,255,0.16)' : 'transparent',
                  transition: uebergang('background-color', 'opacity'),
                  '&:hover': { bgcolor: an ? 'rgba(91,140,255,0.2)' : FARBE.hover },
                  '&:hover .ebene-knopf, &:focus-within .ebene-knopf': { opacity: 1 },
                  '&:focus-visible': FOKUS,
                }}
              >
                <Box sx={{ opacity: aus ? 0.4 : 1, display: 'flex', transition: uebergang('opacity') }}>
                  <Vorschau e={e} />
                </Box>
                <Typography noWrap sx={{ flex: 1, minWidth: 0, fontSize: 13, color: aus ? FARBE.gedaempft : FARBE.text, fontWeight: an ? 600 : 400 }}>
                  {ebenenName(e)}
                </Typography>
                <Tooltip title={aus ? 'Einblenden (nur hier im Fenster)' : 'Ausblenden (nur hier im Fenster)'}>
                  <IconButton
                    size="small"
                    className="ebene-knopf"
                    aria-label={aus ? 'Einblenden' : 'Ausblenden'}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      umschalten(e.id);
                    }}
                    sx={{ opacity: aus || an ? 1 : 0, transition: uebergang('opacity', 'background-color', 'color') }}
                  >
                    {aus ? <VisibilityOffOutlined sx={{ fontSize: 16 }} /> : <VisibilityOutlined sx={{ fontSize: 16 }} />}
                  </IconButton>
                </Tooltip>
                <Tooltip title="Ebene löschen (Entf)">
                  <IconButton
                    size="small"
                    className="ebene-knopf"
                    aria-label="Ebene löschen"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      z.ebeneLoeschen(e.id);
                    }}
                    sx={{ opacity: an ? 1 : 0, transition: uebergang('opacity', 'background-color', 'color'), '&:hover': { color: FARBE.fehler } }}
                  >
                    <DeleteOutlineRounded sx={{ fontSize: 16 }} />
                  </IconButton>
                </Tooltip>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
