// Denken und Schritte des Agenten (Spec 2026-10-09-agent-denken-sichtbar): live unter der
// Fortschritts-Linie, danach pro Verlaufseintrag aufklappbar. Nur Betreiber-Oberflaeche.
import React, { useEffect, useRef, useState } from 'react';
import { Box, ButtonBase } from '@mui/material';

import { denkAusschnitt, type ChatLive, type SpurSchritt } from '../../chat';
import { FARBE } from '../Gestaltung/gestaltungStil';

const SCHLUESSEL = 'vibemind.editor.gedanken';
const KENNUNG = 'Claudes Gedanken (zusammengefasst, englisch)';

export function gedankenSichtbarLesen(): boolean {
  try {
    return globalThis.localStorage?.getItem(SCHLUESSEL) !== 'aus';
  } catch {
    return true;
  }
}

export function gedankenSichtbarSchreiben(an: boolean): void {
  try {
    globalThis.localStorage?.setItem(SCHLUESSEL, an ? 'an' : 'aus');
  } catch {
    /* privates Fenster o. ae.: dann eben nicht gemerkt */
  }
}

export function useGedankenSichtbar(): [boolean, () => void] {
  const [an, setAn] = useState(gedankenSichtbarLesen);
  return [an, () => setAn((alt) => { gedankenSichtbarSchreiben(!alt); return !alt; })];
}

function Schritte({ schritte }: { schritte: SpurSchritt[] }) {
  if (schritte.length === 0) return null;
  return (
    <Box component="ol" sx={{ m: 0, pl: 2.5, fontSize: 12, color: FARBE.gedaempft, lineHeight: 1.6 }}>
      {schritte.map((s, i) => (
        <li key={i}>
          <Box component="span" sx={{ fontVariantNumeric: 'tabular-nums', mr: 0.75 }}>{s.zeit}</Box>
          {s.text}
        </li>
      ))}
    </Box>
  );
}

function Denken({ text, mitlaufen }: { text: string; mitlaufen: boolean }) {
  const ref = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    if (mitlaufen && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [text, mitlaufen]);
  if (!text.trim()) return null;
  return (
    <>
      <Box sx={{ fontSize: 11, color: FARBE.gedaempft, mt: 0.5 }}>{KENNUNG}</Box>
      <Box component="pre" ref={ref} sx={{ m: 0, mt: 0.25, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 11.5,
        lineHeight: 1.5, color: FARBE.gedaempft, maxHeight: mitlaufen ? 120 : 320, overflow: 'auto' }}>
        {text}
      </Box>
    </>
  );
}

export function GedankenLive({ live, sichtbar, umschalten }: { live: ChatLive; sichtbar: boolean; umschalten: () => void }) {
  if (!live.denken.trim() && live.schritte.length === 0) return null;
  return (
    <Box sx={{ ml: 1, pl: 1.25, borderLeft: `2px solid ${FARBE.linie}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: FARBE.gedaempft }}>
        <span>Denkt nach …</span>
        <ButtonBase onClick={umschalten} sx={{ fontSize: 11, color: FARBE.gedaempft, textDecoration: 'underline' }}>
          {sichtbar ? 'Gedanken ausblenden' : 'Gedanken einblenden'}
        </ButtonBase>
      </Box>
      {sichtbar && (
        <>
          <Schritte schritte={live.schritte.slice(-8)} />
          <Denken text={denkAusschnitt(live.denken, 1200)} mitlaufen />
        </>
      )}
    </Box>
  );
}

export function GedankenAufklapp({ denken, schritte }: { denken: string; schritte: SpurSchritt[] }) {
  const [offen, setOffen] = useState(false);
  if (!denken.trim() && schritte.length === 0) return null;
  return (
    <Box sx={{ mt: 0.75 }}>
      <ButtonBase onClick={() => setOffen((o) => !o)} sx={{ fontSize: 11, color: FARBE.gedaempft }}>
        {offen ? '▾' : '▸'} Gedanken & Schritte
      </ButtonBase>
      {offen && (
        <Box sx={{ mt: 0.5 }}>
          <Schritte schritte={schritte} />
          <Denken text={denken} mitlaufen={false} />
        </Box>
      )}
    </Box>
  );
}
