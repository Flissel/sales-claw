// Chips ueber dem Chat-Eingabefeld (Spec 2026-10-06 §1, §2.1): markierte Bloecke/Ebenen auf der
// Akzentflaeche, Anhaenge auf der neutralen Feldflaeche mit Vorschaubild bzw. Dateisymbol und
// Fortschrittsring; Fehler mit Grund am Chip. Jeder Chip mit ✕.
import React from 'react';

import { CloseRounded, DescriptionOutlined, ErrorOutlineRounded, ImageOutlined, LayersOutlined, ViewDayOutlined } from '@mui/icons-material';
import { Box, ButtonBase, CircularProgress, IconButton, Tooltip } from '@mui/material';

import { AnhangChip, AUS_LETZTER, AuswahlChip, MAX_AUSWAHL } from '../../chatKontext';
import { ANZEIGE } from '../../pult';
import { anhangEntfernen, anhangVorschau, auswahlAuffrischen, auswahlEntfernen, chipAuffrischenAuftrag, pultStore } from '../../pultZustand';
import { FARBE, FOKUS, uebergang } from '../Gestaltung/gestaltungStil';

const HOEHE = 28;

const chipRahmen = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.75,
  height: HOEHE,
  maxWidth: '100%',
  minWidth: 0,
  pl: 0.75,
  pr: 0.25,
  borderRadius: '8px',
  fontSize: 12,
  lineHeight: 1,
  '@keyframes chipAuf': { from: { opacity: 0, transform: 'scale(0.96)' }, to: { opacity: 1, transform: 'none' } },
  animation: 'chipAuf 160ms cubic-bezier(0.2, 0, 0, 1)',
  '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
} as const;

function Weg({ titel, onClick }: { titel: string; onClick: () => void }) {
  return (
    <IconButton
      size="small"
      aria-label={`Entfernen: ${titel}`}
      onClick={onClick}
      sx={{ width: 20, height: 20, borderRadius: '6px', flexShrink: 0, color: FARBE.gedaempft, '&:hover': { color: FARBE.text, bgcolor: 'rgba(255,255,255,0.06)' }, '&.Mui-focusVisible': FOKUS }}
    >
      <CloseRounded sx={{ fontSize: 14 }} />
    </IconButton>
  );
}

function Auswahl({ c }: { c: AuswahlChip }) {
  const Symbol = c.art === 'ebene' ? LayersOutlined : ViewDayOutlined;
  return (
    <Box
      role="listitem"
      title={c.alt ? `${c.kurz} – ${AUS_LETZTER}` : c.kurz}
      sx={{
        ...chipRahmen,
        bgcolor: c.alt ? 'transparent' : 'rgba(91,140,255,0.14)',
        border: c.alt ? `1px dashed ${FARBE.linie}` : '1px solid rgba(91,140,255,0.45)',
        color: c.alt ? FARBE.gedaempft : FARBE.text,
      }}
    >
      {c.alt ? (
        <ButtonBase onClick={() => chipAuffrischenAuftrag(c)} aria-label={`Wieder mitschicken: ${c.kurz}`} sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, minWidth: 0, fontSize: 12, color: 'inherit', borderRadius: '6px', '&.Mui-focusVisible': FOKUS }}>
          <Symbol sx={{ fontSize: 14, flexShrink: 0, opacity: 0.6 }} />
          <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {c.kurz} · {AUS_LETZTER}
          </Box>
        </ButtonBase>
      ) : (
        <>
          <Symbol sx={{ fontSize: 14, color: FARBE.akzent, flexShrink: 0 }} />
          <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {c.kurz}
          </Box>
        </>
      )}
      <Weg titel={c.kurz} onClick={() => auswahlEntfernen(c)} />
    </Box>
  );
}

// Die Einzelauswahl der letzten Nachricht: ausgegraut, Anklicken schickt sie wieder mit.
function Liegengeblieben({ kurz }: { kurz: string }) {
  return (
    <ButtonBase
      role="listitem"
      onClick={auswahlAuffrischen}
      aria-label={`Wieder mitschicken: ${kurz}`}
      sx={{ ...chipRahmen, pr: 0.75, border: `1px dashed ${FARBE.linie}`, color: FARBE.gedaempft, fontSize: 12, '&.Mui-focusVisible': FOKUS }}
    >
      <ViewDayOutlined sx={{ fontSize: 14, flexShrink: 0, opacity: 0.6 }} />
      <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {kurz} · {AUS_LETZTER}
      </Box>
    </ButtonBase>
  );
}

// Kleines Bild links im Chip; waehrend des Uploads liegt der Fortschrittsring darum.
function Kopf({ a }: { a: AnhangChip }) {
  const fertigBild = a.art === 'bild' && a.status === 'fertig' ? ANZEIGE + encodeURIComponent(a.name) : undefined;
  const bild = a.vorschau ?? fertigBild;
  return (
    <Box sx={{ position: 'relative', width: 20, height: 20, flexShrink: 0, display: 'grid', placeItems: 'center' }}>
      {a.status === 'fehler' ? (
        <ErrorOutlineRounded sx={{ fontSize: 16, color: FARBE.fehler }} />
      ) : bild ? (
        <Box component="img" src={bild} alt="" sx={{ width: 20, height: 20, borderRadius: '4px', objectFit: 'cover', opacity: a.status === 'laedt' ? 0.55 : 1, transition: uebergang('opacity') }} />
      ) : a.art === 'bild' ? (
        <ImageOutlined sx={{ fontSize: 16, color: FARBE.gedaempft }} />
      ) : (
        <DescriptionOutlined sx={{ fontSize: 16, color: FARBE.gedaempft }} />
      )}
      {a.status === 'laedt' && (
        <>
          <CircularProgress
            variant="determinate"
            value={100}
            size={24}
            thickness={3}
            aria-hidden="true"
            sx={{ position: 'absolute', inset: -2, color: 'rgba(255,255,255,0.12)' }}
          />
          <CircularProgress
            variant="determinate"
            value={Math.max(4, Math.round(a.fortschritt * 100))}
            size={24}
            thickness={3}
            aria-label={`${a.name} wird hochgeladen`}
            sx={{ position: 'absolute', inset: -2, color: FARBE.akzent, '& circle': { transition: 'stroke-dashoffset 200ms ease-out' } }}
          />
        </>
      )}
    </Box>
  );
}

function Anhang({ a }: { a: AnhangChip }) {
  const fehler = a.status === 'fehler';
  const text = fehler ? `${a.name} – ${a.grund ?? 'nicht hochgeladen'}` : a.name;
  return (
    <Tooltip title={fehler ? (a.grund ?? '') : a.status === 'laedt' ? `Wird hochgeladen … ${Math.round(a.fortschritt * 100)} %` : ''}>
      <Box
        role="listitem"
        sx={{
          ...chipRahmen,
          bgcolor: FARBE.feld,
          border: `1px solid ${fehler ? 'rgba(255,139,139,0.45)' : FARBE.linie}`,
          color: fehler ? FARBE.fehler : FARBE.text,
        }}
      >
        <Kopf a={a} />
        <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
          {text}
        </Box>
        <Weg titel={a.name} onClick={() => anhangEntfernen(a.id)} />
      </Box>
    </Tooltip>
  );
}

export default function KontextChips({ altform = null }: { altform?: { kurz: string } | null }) {
  const auswahl = pultStore((p) => p.chatAuswahl);
  const anhaenge = pultStore((p) => p.chatAnhaenge);
  if (auswahl.length === 0 && anhaenge.length === 0 && !altform) return null;
  return (
    <Box role="list" aria-label="Kontext für die nächste Nachricht" sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, px: 0.5, pb: 1 }}>
      {altform && <Liegengeblieben kurz={altform.kurz} />}
      {auswahl.map((c) => (
        <Auswahl key={`${c.art}:${c.flaeche ?? ''}:${c.id}`} c={c} />
      ))}
      {anhaenge.map((a) => (
        <Anhang key={a.id} a={a} />
      ))}
      {auswahl.length >= MAX_AUSWAHL && (
        <Box component="span" sx={{ alignSelf: 'center', fontSize: 11, color: FARBE.gedaempft }}>
          Höchstens {MAX_AUSWAHL} markierte Elemente je Nachricht
        </Box>
      )}
    </Box>
  );
}

// Vorschaubild ohne blob:-Adresse (die Seite erlaubt nur 'self' und data:): klein gerechnet als data:.
export async function vorschauErzeugen(id: string, datei: File) {
  if (!/^image\/(png|jpeg|webp)$/.test(datei.type) || typeof createImageBitmap !== 'function') return;
  try {
    const bmp = await createImageBitmap(datei);
    const kante = 48;
    const f = Math.min(1, kante / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(bmp.width * f));
    c.height = Math.max(1, Math.round(bmp.height * f));
    c.getContext('2d')?.drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    anhangVorschau(id, c.toDataURL('image/jpeg', 0.8));
  } catch {
    /* ohne Vorschau: Bildsymbol */
  }
}
