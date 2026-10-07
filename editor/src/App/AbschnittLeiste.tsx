import React from 'react';

import { Box, Button, Card, CardContent, Drawer, Typography, useTheme } from '@mui/material';

import { ABSCHNITTE, AbschnittSchluessel, DRAG_TYP, einfuegen } from '../abschnitte';
import { getDocument, setDocument, setSelectedBlockId } from '../documents/editor/EditorContext';

import { useGesperrt } from './Chat/Sperre';
import { useInert } from './Chat/sperren';

export const ABSCHNITT_LEISTE_BREITE = 240;

// Fuegt den Abschnitt ein und waehlt den neuen obersten Block aus
// (seine id ergibt sich aus dem Unterschied der root-childrenIds).
export function abschnittEinsetzen(schluessel: AbschnittSchluessel, index: number) {
  const vorher = getDocument();
  const neu = einfuegen(vorher, schluessel, index);
  setDocument(neu as ReturnType<typeof getDocument>);
  const ids = (d: typeof neu) => ((d.root as { data?: { childrenIds?: string[] } }).data?.childrenIds ?? []) as string[];
  const alt = new Set(ids(vorher));
  const id = ids(neu).find((k) => !alt.has(k));
  if (id) setSelectedBlockId(id);
}

function Skizze({ schluessel }: { schluessel: AbschnittSchluessel }) {
  const { palette } = useTheme();
  const bildFarbe = palette.primary.main;
  const linie = palette.text.disabled;
  const rand = palette.divider;
  const B = (x: number, y: number, w: number, h: number) => (
    <rect x={x} y={y} width={w} height={h} rx={2} fill={bildFarbe} opacity={0.45} />
  );
  const L = (x: number, y: number, w: number, dick = 3) => (
    <rect x={x} y={y} width={w} height={dick} rx={1.5} fill={linie} />
  );
  let inhalt: React.ReactNode;
  switch (schluessel) {
    case 'kopfbild':
      inhalt = <>{B(8, 6, 184, 40)}{L(8, 54, 110, 5)}{L(8, 64, 170)}{L(8, 71, 140)}</>;
      break;
    case 'bild_text':
      inhalt = <>{B(8, 10, 84, 60)}{L(102, 14, 60, 5)}{L(102, 26, 88)}{L(102, 33, 80)}{L(102, 40, 86)}</>;
      break;
    case 'zwei_spalten':
      inhalt = (
        <>
          {B(8, 8, 88, 40)}{L(8, 56, 60, 4)}{L(8, 65, 84)}
          {B(104, 8, 88, 40)}{L(104, 56, 60, 4)}{L(104, 65, 84)}
        </>
      );
      break;
    case 'drei_spalten':
      inhalt = (
        <>
          {B(8, 8, 56, 40)}{L(8, 56, 40, 4)}{L(8, 65, 54)}
          {B(72, 8, 56, 40)}{L(72, 56, 40, 4)}{L(72, 65, 54)}
          {B(136, 8, 56, 40)}{L(136, 56, 40, 4)}{L(136, 65, 54)}
        </>
      );
      break;
    case 'zitat':
      inhalt = <><rect x={8} y={8} width={184} height={64} rx={6} fill={rand} />{L(20, 24, 150, 4)}{L(20, 34, 120, 4)}{L(20, 54, 50)}</>;
      break;
    case 'grosse_zahl':
      inhalt = <><rect x={8} y={8} width={184} height={64} rx={6} fill={rand} /><rect x={66} y={18} width={68} height={16} rx={3} fill={bildFarbe} />{L(56, 46, 88)}{L(70, 56, 60)}</>;
      break;
    case 'knopfleiste':
      inhalt = <>{L(20, 22, 160, 4)}{L(40, 32, 120, 4)}<rect x={64} y={48} width={72} height={18} rx={9} fill={bildFarbe} /></>;
      break;
    case 'fussgruss':
      inhalt = <><rect x={8} y={14} width={184} height={1.5} fill={rand} />{L(8, 26, 90, 4)}{L(8, 36, 60, 4)}<rect x={8} y={54} width={70} height={3} rx={1.5} fill={bildFarbe} /></>;
      break;
  }
  return (
    <svg width="100%" viewBox="0 0 200 80" role="img" aria-hidden="true" style={{ display: 'block' }}>
      <rect x={0.5} y={0.5} width={199} height={79} rx={4} fill="none" stroke={rand} />
      {inhalt}
    </svg>
  );
}

export default function AbschnittLeiste() {
  const inertRef = useInert<HTMLDivElement>(useGesperrt());
  return (
    <Drawer
      variant="permanent"
      anchor="left"
      sx={{
        width: ABSCHNITT_LEISTE_BREITE,
        flexShrink: 0,
        '& .MuiDrawer-paper': { width: ABSCHNITT_LEISTE_BREITE, boxSizing: 'border-box' },
      }}
    >
      <Box sx={{ p: 2, overflow: 'auto', height: '100%' }}>
        <Box ref={inertRef}>
        <Typography variant="h6" sx={{ mb: 0.5 }}>
          Abschnitte
        </Typography>
        <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 1.5 }}>
          In den Newsletter ziehen oder per Knopf ans Ende setzen.
        </Typography>
        {ABSCHNITTE.map((a) => (
          <Card
            key={a.schluessel}
            variant="outlined"
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData(DRAG_TYP, a.schluessel);
              e.dataTransfer.effectAllowed = 'copy';
            }}
            sx={{ mb: 1.5, cursor: 'grab' }}
          >
            <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Skizze schluessel={a.schluessel} />
              <Typography variant="subtitle2" sx={{ mt: 1 }}>
                {a.titel}
              </Typography>
              <Typography variant="caption" color="text.secondary" component="p">
                {a.beschreibung}
              </Typography>
              <Button size="small" sx={{ mt: 0.5 }} onClick={() => abschnittEinsetzen(a.schluessel, Infinity)}>
                Einfügen
              </Button>
            </CardContent>
          </Card>
        ))}
        <Box component="details" sx={{ mt: 2 }}>
          <Typography component="summary" variant="subtitle2" sx={{ cursor: 'pointer' }}>
            Einzelbausteine
          </Typography>
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.5 }}>
            Einzelne Blöcke fügst du über „+“ im Newsletter ein.
          </Typography>
        </Box>
        </Box>
      </Box>
    </Drawer>
  );
}
