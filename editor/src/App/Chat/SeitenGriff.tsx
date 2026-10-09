// Ziehgriff am linken Rand der rechten Leiste (Spec 2026-10-09 §2): Zeiger ziehen oder Pfeiltasten, gemerkt beim
// Loslassen bzw. je Tastendruck.
import React, { useCallback, useEffect, useState } from 'react';

import { Box } from '@mui/material';

import { BREITE_MIN, breiteBegrenzen, breiteLesen, breiteSchreiben, fensterBreite } from './breite';

const SCHRITT = 16;

export function useSeitenBreite(): [number, (px: number) => void] {
  const [breite, setBreite] = useState(() => breiteLesen(fensterBreite()));
  useEffect(() => {
    const anpassen = () => setBreite((b) => breiteBegrenzen(b, fensterBreite()));
    window.addEventListener('resize', anpassen);
    return () => window.removeEventListener('resize', anpassen);
  }, []);
  const setzen = useCallback((px: number) => setBreite(breiteBegrenzen(px, fensterBreite())), []);
  return [breite, setzen];
}

export default function SeitenGriff({ breite, onBreite }: { breite: number; onBreite: (px: number) => void }) {
  const ziehen = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    const start = e.clientX;
    let zuletzt = breite;
    el.setPointerCapture(e.pointerId);
    const bewegen = (ev: PointerEvent) => {
      zuletzt = breiteBegrenzen(breite + (start - ev.clientX), fensterBreite());
      onBreite(zuletzt);
    };
    const ende = () => {
      el.removeEventListener('pointermove', bewegen);
      el.removeEventListener('pointerup', ende);
      el.removeEventListener('pointercancel', ende);
      breiteSchreiben(zuletzt);
    };
    el.addEventListener('pointermove', bewegen);
    el.addEventListener('pointerup', ende);
    el.addEventListener('pointercancel', ende);
  };
  const tasten = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const neu = breiteBegrenzen(breite + (e.key === 'ArrowLeft' ? SCHRITT : -SCHRITT), fensterBreite());
    onBreite(neu);
    breiteSchreiben(neu);
  };
  return (
    <Box
      role="separator"
      aria-orientation="vertical"
      aria-label="Breite der Seitenleiste"
      aria-valuenow={breite}
      aria-valuemin={BREITE_MIN}
      tabIndex={0}
      onPointerDown={ziehen}
      onKeyDown={tasten}
      sx={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, zIndex: 2, cursor: 'col-resize', touchAction: 'none',
        transition: 'background-color 150ms ease-out',
        '&:hover, &:focus-visible': { bgcolor: 'rgba(91,140,255,0.45)', outline: 'none' },
      }}
    />
  );
}
