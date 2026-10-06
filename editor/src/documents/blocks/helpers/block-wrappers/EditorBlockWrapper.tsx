import React, { CSSProperties, useEffect, useRef, useState } from 'react';

import { CheckRounded } from '@mui/icons-material';
import { Box, ButtonBase } from '@mui/material';

import { blockAlsKontext, blockKontextUmschalten, pultStore } from '../../../../pultZustand';
import { useCurrentBlockId } from '../../../editor/EditorBlock';
import { setSelectedBlockId, useSelectedBlockId } from '../../../editor/EditorContext';

import TuneMenu from './TuneMenu';

type TEditorBlockWrapperProps = {
  children: JSX.Element;
};

// Live-Ansicht (Spec 2026-10-02-newsletter-agent-live §2.3): der zuletzt vom Agenten geaenderte
// Block leuchtet kurz in Akzentfarbe auf (600 ms, ruhig) und rollt sanft in die Sicht, falls er
// ausserhalb liegt. puls startet das Leuchten bei jedem neuen Zwischenstand neu.
const AKZENT = '#5b8cff';
const LEUCHTEN_MS = 600;

function inSicht(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  let rahmen = { top: 0, bottom: window.innerHeight };
  const buehne = el.closest('[data-canvas]');
  if (buehne) {
    const b = buehne.getBoundingClientRect();
    rahmen = { top: Math.max(0, b.top), bottom: Math.min(window.innerHeight, b.bottom) };
  }
  return r.top >= rahmen.top && r.bottom <= rahmen.bottom;
}

function Leuchten({ puls, ziel }: { puls: number; ziel: React.RefObject<HTMLDivElement> }) {
  useEffect(() => {
    const el = ziel.current;
    if (!el || inSicht(el)) return;
    const ruhig = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    el.scrollIntoView({ behavior: ruhig ? 'auto' : 'smooth', block: 'nearest' });
  }, [puls, ziel]);
  return (
    <Box
      key={puls}
      aria-hidden="true"
      sx={{
        position: 'absolute',
        inset: 0,
        zIndex: 1,
        pointerEvents: 'none',
        borderRadius: '2px',
        opacity: 0,
        '@keyframes blockLeuchten': {
          '0%': { opacity: 0, boxShadow: `inset 0 0 0 2px ${AKZENT}, 0 0 0 0 rgba(91,140,255,0.45)` },
          '25%': { opacity: 1, boxShadow: `inset 0 0 0 2px ${AKZENT}, 0 0 24px 4px rgba(91,140,255,0.35)` },
          '100%': { opacity: 0, boxShadow: `inset 0 0 0 2px ${AKZENT}, 0 0 32px 8px rgba(91,140,255,0)` },
        },
        animation: `blockLeuchten ${LEUCHTEN_MS}ms cubic-bezier(0.2, 0, 0, 1) forwards`,
      }}
    />
  );
}

// Kontext per Klick (Spec 2026-10-06 §1): am ausgewaehlten Block "+ Kontext" (nochmal: wieder heraus),
// Alt+Klick auf irgendeinen Block haengt ihn als Chip an den Chat. Waehrend der Agent arbeitet, ist
// der Canvas gesperrt (inert) - dann geht beides nicht.
function KontextKnopf({ blockId, drin }: { blockId: string; drin: boolean }) {
  return (
    <ButtonBase
      aria-label={drin ? 'Aus dem Kontext nehmen' : 'Als Kontext an den Chat hängen'}
      title={drin ? 'Ist im Chat-Kontext – klicken nimmt ihn heraus' : 'Als Kontext an den Chat hängen (oder Alt+Klick)'}
      onClick={(ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        blockKontextUmschalten(blockId);
      }}
      sx={{
        position: 'absolute',
        top: 6,
        right: 6,
        zIndex: 2,
        height: 24,
        px: 1,
        gap: 0.5,
        borderRadius: '12px',
        fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: 0,
        color: drin ? AKZENT : '#ffffff',
        bgcolor: drin ? '#ffffff' : AKZENT,
        border: `1px solid ${AKZENT}`,
        boxShadow: '0 1px 2px rgba(0,0,0,0.18), 0 4px 12px rgba(0,0,0,0.12)',
        transition: 'background-color 150ms ease-out, color 150ms ease-out',
        '&:hover': { bgcolor: drin ? '#eef3ff' : '#4a7bf0' },
        '&.Mui-focusVisible': { outline: `2px solid ${AKZENT}`, outlineOffset: 2 },
      }}
    >
      {drin && <CheckRounded sx={{ fontSize: 14 }} />}
      {drin ? 'Im Kontext' : '+ Kontext'}
    </ButtonBase>
  );
}

export default function EditorBlockWrapper({ children }: TEditorBlockWrapperProps) {
  const selectedBlockId = useSelectedBlockId();
  const [mouseInside, setMouseInside] = useState(false);
  const blockId = useCurrentBlockId();
  const puls = pultStore((p) => (p.zwischenstand?.leuchtet === blockId ? p.zwischenstand.puls : null));
  const ref = useRef<HTMLDivElement>(null);
  const imKontext = pultStore((p) => p.chatAuswahl.some((c) => c.art === 'block' && c.id === blockId));

  let outline: CSSProperties['outline'];
  if (selectedBlockId === blockId) {
    outline = '2px solid rgba(0,121,204, 1)';
  } else if (imKontext) {
    // Markiert fuer den Chat: ruhiger Akzent-Rahmen, gestrichelt (keine zweite Auswahl).
    outline = `2px dashed ${AKZENT}`;
  } else if (mouseInside) {
    outline = '2px solid rgba(0,121,204, 0.3)';
  }

  const renderMenu = () => {
    if (selectedBlockId !== blockId) {
      return null;
    }
    return <TuneMenu blockId={blockId} />;
  };

  return (
    <Box
      ref={ref}
      sx={{
        position: 'relative',
        maxWidth: '100%',
        outlineOffset: '-1px',
        outline,
      }}
      onMouseEnter={(ev) => {
        setMouseInside(true);
        ev.stopPropagation();
      }}
      onMouseLeave={() => {
        setMouseInside(false);
      }}
      onClick={(ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        if (ev.altKey) {
          blockAlsKontext(blockId);
          return;
        }
        setSelectedBlockId(blockId);
      }}
    >
      {renderMenu()}
      {selectedBlockId === blockId && <KontextKnopf blockId={blockId} drin={imKontext} />}
      {children}
      {puls !== null && <Leuchten puls={puls} ziel={ref} />}
    </Box>
  );
}
