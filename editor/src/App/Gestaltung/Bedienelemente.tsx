// Kleine Bedienelemente des Gestaltungsfensters (Zahlenfeld, Farbfeld, Abschnitt),
// gemeinsam genutzt von Kopfleiste und Eigenschaften.
import React, { useEffect, useRef, useState } from 'react';
import { HexColorInput, HexColorPicker } from 'react-colorful';

import { Box, ButtonBase, Popover, Typography } from '@mui/material';

import type { Art } from './useGestaltung';
import { FARBE, FOKUS, RASTER, uebergang } from './gestaltungStil';

export function Abschnitt({ titel, children, rechts }: { titel: string; children: React.ReactNode; rechts?: React.ReactNode }) {
  return (
    <Box component="section" sx={{ px: 2, py: 2, borderBottom: `1px solid ${FARBE.linie}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5, minHeight: 16 }}>
        <Typography component="h3" sx={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: FARBE.gedaempft }}>
          {titel}
        </Typography>
        {rechts}
      </Box>
      <Box sx={{ display: 'grid', gap: 1 }}>{children}</Box>
    </Box>
  );
}

// Beschriftete Zeile: Label links (88 px), Steuerung rechts.
export function Zeile({ label, children, htmlFor }: { label: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '88px 1fr', alignItems: 'center', gap: 1, minHeight: 32 }}>
      <Typography component="label" htmlFor={htmlFor} sx={{ fontSize: 12, color: FARBE.gedaempft }}>
        {label}
      </Typography>
      <Box sx={{ minWidth: 0 }}>{children}</Box>
    </Box>
  );
}

const runden = (v: number, schritt: number) => {
  const stellen = schritt < 1 ? Math.max(0, -Math.floor(Math.log10(schritt))) : 0;
  return Number(v.toFixed(stellen));
};

type ZahlProps = {
  label: string;
  wert: number;
  min: number;
  max: number;
  schritt?: number;
  einheit?: string;
  onChange: (v: number, art: Art) => void;
};

// Zahlenfeld im Framer-Stil: das Kuerzel links laesst sich waagerecht ziehen ("scrubben"),
// das Feld nimmt Tippen und Pfeiltasten (Shift = zehnfach).
export function Zahl({ label, wert, min, max, schritt = 1, einheit, onChange }: ZahlProps) {
  const [text, setText] = useState(String(runden(wert, schritt)));
  const [fokus, setFokus] = useState(false);
  const zug = useRef<{ x: number; start: number } | null>(null);
  useEffect(() => {
    if (!fokus) setText(String(runden(wert, schritt)));
  }, [wert, schritt, fokus]);

  const klemmen = (v: number) => runden(Math.min(max, Math.max(min, v)), schritt);

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        height: 32,
        borderRadius: '6px',
        bgcolor: FARBE.feld,
        border: '1px solid transparent',
        transition: uebergang('border-color'),
        '&:hover': { borderColor: FARBE.linie },
        '&:focus-within': { borderColor: FARBE.akzent },
      }}
    >
      <Box
        aria-hidden
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          zug.current = { x: e.clientX, start: wert };
        }}
        onPointerMove={(e) => {
          if (!zug.current) return;
          onChange(klemmen(zug.current.start + Math.round((e.clientX - zug.current.x) / 2) * schritt), 'live');
        }}
        onPointerUp={() => {
          if (zug.current) onChange(wert, 'sofort');
          zug.current = null;
        }}
        sx={{
          px: 1,
          alignSelf: 'stretch',
          display: 'flex',
          alignItems: 'center',
          fontSize: 11,
          fontWeight: 600,
          color: FARBE.gedaempft,
          cursor: 'ew-resize',
          userSelect: 'none',
          touchAction: 'none',
          minWidth: 24,
        }}
      >
        {label}
      </Box>
      <Box
        component="input"
        aria-label={label}
        inputMode="decimal"
        value={text}
        onFocus={() => setFokus(true)}
        onBlur={() => {
          setFokus(false);
          const v = Number(text.replace(',', '.'));
          if (Number.isFinite(v)) onChange(klemmen(v), 'sofort');
          setText(String(klemmen(Number.isFinite(v) ? v : wert)));
        }}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
          setText(e.target.value);
          const v = Number(e.target.value.replace(',', '.'));
          if (e.target.value.trim() !== '' && Number.isFinite(v) && v >= min && v <= max) onChange(runden(v, schritt), 'gleiten');
        }}
        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
          e.preventDefault();
          const d = (e.key === 'ArrowUp' ? 1 : -1) * schritt * (e.shiftKey ? 10 : 1);
          const v = klemmen(wert + d);
          setText(String(v));
          onChange(v, 'gleiten');
        }}
        sx={{
          flex: 1,
          minWidth: 0,
          height: '100%',
          border: 'none',
          outline: 'none',
          bgcolor: 'transparent',
          color: FARBE.text,
          font: 'inherit',
          fontSize: 13,
          fontVariantNumeric: 'tabular-nums',
          px: 0.5,
        }}
      />
      {einheit && <Box sx={{ pr: 1, fontSize: 12, color: FARBE.gedaempft }}>{einheit}</Box>}
    </Box>
  );
}

type FarbFeldProps = {
  wert: string;
  laden: string[];
  benutzt: string[];
  onChange: (v: string, art: Art) => void;
  label: string;
  kompakt?: boolean;
};

function Muster({ farbe, an, onClick }: { farbe: string; an: boolean; onClick: () => void }) {
  return (
    <ButtonBase
      aria-label={farbe}
      title={farbe}
      onClick={onClick}
      sx={{
        width: 24,
        height: 24,
        borderRadius: '6px',
        bgcolor: farbe,
        boxShadow: an ? `0 0 0 2px ${FARBE.panel}, 0 0 0 4px ${FARBE.akzent}` : 'inset 0 0 0 1px rgba(255,255,255,0.12)',
        transition: uebergang('box-shadow', 'transform'),
        '&:hover': { transform: 'scale(1.08)' },
        '&.Mui-focusVisible': FOKUS,
      }}
    />
  );
}

// Farbfeld: Muster + Hex; im Aufklapper Farbwaehler, Ladenfarben und benutzte Farben.
export function FarbFeld({ wert, laden, benutzt, onChange, label, kompakt }: FarbFeldProps) {
  const [anker, setAnker] = useState<HTMLElement | null>(null);
  const gross = wert.toUpperCase();
  const gruppen: Array<[string, string[]]> = [
    ['Ladenfarben', laden],
    ['Benutzt', benutzt],
  ];
  return (
    <>
      <ButtonBase
        aria-label={`${label}: ${gross}`}
        onClick={(e) => setAnker(e.currentTarget)}
        sx={{
          height: 32,
          px: 0.5,
          pr: kompakt ? 0.5 : 1,
          gap: 1,
          borderRadius: '6px',
          bgcolor: FARBE.feld,
          border: '1px solid transparent',
          justifyContent: 'flex-start',
          width: kompakt ? 'auto' : '100%',
          transition: uebergang('border-color'),
          '&:hover': { borderColor: FARBE.linie },
          '&.Mui-focusVisible': FOKUS,
        }}
      >
        <Box sx={{ width: 24, height: 24, borderRadius: '4px', bgcolor: wert, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.14)' }} />
        {!kompakt && <Box sx={{ fontSize: 13, color: FARBE.text, fontVariantNumeric: 'tabular-nums' }}>{gross}</Box>}
      </ButtonBase>
      <Popover
        open={anker !== null}
        anchorEl={anker}
        onClose={() => setAnker(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{ paper: { sx: { mt: 1, p: 2, width: 248, bgcolor: FARBE.panel } } }}
      >
        <Box
          sx={{
            '.react-colorful': { width: '100%', height: 160 },
            '.react-colorful__saturation': { borderRadius: '6px 6px 0 0' },
            '.react-colorful__last-control': { borderRadius: '0 0 6px 6px', height: 12 },
            '.react-colorful__pointer': { width: 16, height: 16 },
          }}
        >
          <HexColorPicker color={wert} onChange={(c) => onChange(c.toUpperCase(), 'gleiten')} />
        </Box>
        <Box
          sx={{
            mt: 1.5,
            display: 'flex',
            alignItems: 'center',
            height: 32,
            px: 1,
            borderRadius: '6px',
            bgcolor: FARBE.feld,
            '&:focus-within': { boxShadow: `inset 0 0 0 1px ${FARBE.akzent}` },
            input: { border: 'none', outline: 'none', bgcolor: 'transparent', color: FARBE.text, font: 'inherit', fontSize: 13, width: '100%', textTransform: 'uppercase' },
          }}
        >
          <Box sx={{ color: FARBE.gedaempft, fontSize: 13, mr: 0.5 }}>#</Box>
          <HexColorInput aria-label="Hex-Farbe" color={wert} onChange={(c) => onChange(c.toUpperCase(), 'gleiten')} />
        </Box>
        {gruppen.map(([titel, liste]) =>
          liste.length === 0 ? null : (
            <Box key={titel} sx={{ mt: 2 }}>
              <Typography sx={{ fontSize: 11, color: FARBE.gedaempft, mb: 1 }}>{titel}</Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: `${RASTER}px` }}>
                {liste.map((f) => (
                  <Muster key={f} farbe={f} an={f === gross} onClick={() => onChange(f, 'sofort')} />
                ))}
              </Box>
            </Box>
          )
        )}
      </Popover>
    </>
  );
}
