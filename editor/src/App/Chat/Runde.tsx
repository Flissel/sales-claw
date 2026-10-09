// Ein Eintrag im Chat-Verlauf (Spec 2026-10-09-editor-parallele-runden §2): jede Runde mit eigener Schrittzeile,
// eigenen Gedanken und eigenem Stopp; wartende Runden "wartet auf freien Platz"; Hinweise (uebersprungene
// Aenderungen, gescheiterte Bilder) am Eintrag. Rueckgaengig nur an der Runde mit der neuesten Fassung.
import React from 'react';

import { ErrorOutlineRounded, HourglassEmptyRounded, IosShareRounded, PhotoLibraryOutlined, StopRounded, UndoRounded } from '@mui/icons-material';
import { Box, Button, CircularProgress, Tooltip } from '@mui/material';

import { ChatEintrag, ExportAuswahl, exportVorschlag } from '../../chat';
import { schrittText } from '../../live';
import { FARBE } from '../Gestaltung/gestaltungStil';

import { GedankenAufklapp, GedankenLive } from './Gedanken';
import { Punkte } from './Sperre';

export const WARTET_TEXT = 'wartet auf freien Platz';

export type RundenAktionen = {
  rueckSperre: string | null;
  // Die eine Runde, die sich rueckgaengig machen laesst (rueckgaengigFuer).
  rueckId: string | null;
  rueckLaeuft: string | null;
  // Fehler an einem Eintrag (Rueckgaengig oder Stopp einer wartenden Runde).
  fehlerAn: { id: string; grund: string } | null;
  onRueckgaengig: (id: string) => void;
  onExport: (v: ExportAuswahl) => void;
  onStopp: (e: ChatEintrag) => void;
  nurLesen: boolean;
  getrennt: boolean;
  gedankenSichtbar: boolean;
  gedankenUmschalten: () => void;
};

const laeuftNoch = (e: ChatEintrag) => e.status === 'offen' || e.status === 'in_arbeit' || e.status === 'wartet';

export function rundenZeile(e: ChatEintrag, getrennt: boolean): string {
  if (e.status === 'wartet') return WARTET_TEXT;
  if (getrennt) return 'Verbindung …';
  if (e.stopp) return 'Wird gestoppt …';
  return schrittText(e) ?? (e.status === 'offen' ? 'Wartet auf den Assistenten …' : 'Agent denkt nach …');
}

const kleinerKnopf = { height: 24, px: 1, fontSize: 12, fontWeight: 500, color: FARBE.gedaempft, minWidth: 0, '&:hover': { color: FARBE.text, bgcolor: FARBE.hover } } as const;

function Blase({ ich, fehler, children }: { ich: boolean; fehler?: boolean; children: React.ReactNode }) {
  return (
    <Box
      sx={{
        alignSelf: ich ? 'flex-end' : 'flex-start', maxWidth: '88%', px: 1.5, py: 1,
        borderRadius: ich ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
        bgcolor: ich ? FARBE.akzent : FARBE.panel, color: ich ? '#ffffff' : fehler ? FARBE.fehler : FARBE.text,
        border: ich ? 'none' : `1px solid ${FARBE.linie}`, fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      }}
    >
      {children}
    </Box>
  );
}

// Laufende Runde: Punkte, Schrittzeile und eine ruhig wandernde Linie; wartend: Sanduhr, ohne Linie.
function LaufBlase({ text, wartet }: { text: string; wartet: boolean }) {
  return (
    <Box
      sx={{
        position: 'relative', overflow: 'hidden', minWidth: 0, display: 'flex', alignItems: 'center', gap: 1, px: 1.5,
        minHeight: 36, py: 0.75, borderRadius: '12px 12px 12px 4px', bgcolor: FARBE.panel,
        border: `1px ${wartet ? 'dashed' : 'solid'} ${FARBE.linie}`,
      }}
    >
      {wartet ? <HourglassEmptyRounded sx={{ fontSize: 14, color: FARBE.gedaempft }} /> : <Punkte />}
      <Box
        key={text}
        component="span"
        sx={{
          fontSize: 12, lineHeight: 1.4, color: wartet ? FARBE.gedaempft : FARBE.text, fontVariantNumeric: 'tabular-nums',
          '@keyframes schrittAuf': { from: { opacity: 0, transform: 'translateY(3px)' }, to: { opacity: 1, transform: 'none' } },
          animation: 'schrittAuf 220ms cubic-bezier(0.2, 0, 0, 1)', '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      >
        {text}
      </Box>
      {!wartet && (
        <Box
          aria-hidden="true"
          sx={{
            position: 'absolute', left: 0, right: 0, bottom: 0, height: '2px',
            background: `linear-gradient(90deg, transparent 0%, ${FARBE.akzent} 50%, transparent 100%)`,
            backgroundSize: '50% 100%', backgroundRepeat: 'no-repeat', opacity: 0.7,
            '@keyframes schrittLinie': { from: { backgroundPosition: '-100% 0' }, to: { backgroundPosition: '200% 0' } },
            animation: 'schrittLinie 1.8s ease-in-out infinite',
            '@media (prefers-reduced-motion: reduce)': { animation: 'none', opacity: 0.35, backgroundSize: '100% 100%' },
          }}
        />
      )}
    </Box>
  );
}

export function Eintrag({ e, a }: { e: ChatEintrag; a: RundenAktionen }) {
  if (e.art === 'export') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, fontSize: 12, color: e.status === 'fehler' ? FARBE.fehler : FARBE.gedaempft, textAlign: 'center', px: 2 }}>
        <PhotoLibraryOutlined sx={{ fontSize: 14, flexShrink: 0 }} />
        {laeuftNoch(e) ? (
          <>
            <span>Newsletter-Bilder werden am PC gerechnet</span>
            <Punkte />
          </>
        ) : (
          <span>{e.antwort || (e.status === 'fertig' ? 'Export fertig' : 'Export fehlgeschlagen')}</span>
        )}
      </Box>
    );
  }
  const vorschlag = e.status === 'fertig' ? exportVorschlag(e) : null;
  const mitFassung = e.status === 'fertig' && e.fassung_nachher !== null;
  const kannZurueck = mitFassung && a.rueckId === e.id;
  const hinweise = [...e.hinweise, ...e.bild_hinweise];
  const wartet = e.status === 'wartet';
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {e.nachricht && <Blase ich>{e.nachricht}</Blase>}
      {laeuftNoch(e) ? (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, alignSelf: 'flex-start', maxWidth: '100%' }}>
            <LaufBlase text={rundenZeile(e, a.getrennt)} wartet={wartet} />
            {!a.nurLesen && (
              <Tooltip title={wartet ? 'Aus der Warteschlange nehmen' : e.stopp ? 'Wird gestoppt …' : 'Diese Runde anhalten'}>
                <span>
                  <Button
                    size="small"
                    aria-label={`Stopp: ${e.nachricht}`}
                    disabled={e.stopp !== null}
                    onClick={() => a.onStopp(e)}
                    startIcon={<StopRounded sx={{ fontSize: 14 }} />}
                    sx={kleinerKnopf}
                  >
                    Stopp
                  </Button>
                </span>
              </Tooltip>
            )}
          </Box>
          {!wartet && <GedankenLive live={e} sichtbar={a.gedankenSichtbar} umschalten={a.gedankenUmschalten} />}
        </>
      ) : (
        <Blase ich={false} fehler={e.status === 'fehler'}>
          {e.status === 'fehler' && <ErrorOutlineRounded sx={{ fontSize: 14, mr: 0.75, verticalAlign: '-2px' }} />}
          {e.antwort || (e.status === 'fehler' ? 'Das hat nicht geklappt.' : 'Erledigt.')}
          {hinweise.length > 0 && (
            <Box component="ul" sx={{ m: 0, mt: 1, pl: 2, color: FARBE.gedaempft, fontSize: 12, lineHeight: 1.5, '& li::marker': { color: FARBE.warnung } }}>
              {hinweise.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </Box>
          )}
          <GedankenAufklapp denken={e.denken} schritte={e.schritte} />
        </Blase>
      )}
      {(mitFassung || vorschlag) && (
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5, mt: -0.5 }}>
          {e.fassung_nachher !== null && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, mr: 0.5, fontVariantNumeric: 'tabular-nums' }}>
              Fassung {e.fassung_nachher}
              {e.ergebnis.notiz ? ` · ${e.ergebnis.notiz}` : ''}
            </Box>
          )}
          {mitFassung && !kannZurueck && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, fontStyle: 'italic' }}>
              · Spätere Änderungen vorhanden
            </Box>
          )}
          {kannZurueck && (
            <Tooltip title={a.rueckSperre ?? 'Legt die Fassung davor als neue Fassung an'}>
              <span>
                <Button
                  size="small"
                  disabled={a.rueckSperre !== null || a.rueckLaeuft !== null}
                  onClick={() => a.onRueckgaengig(e.id)}
                  startIcon={a.rueckLaeuft === e.id ? <CircularProgress size={12} color="inherit" /> : <UndoRounded sx={{ fontSize: 14 }} />}
                  sx={kleinerKnopf}
                >
                  Rückgängig
                </Button>
              </span>
            </Tooltip>
          )}
          {vorschlag && !a.nurLesen && (
            <Button size="small" onClick={() => a.onExport(vorschlag)} startIcon={<IosShareRounded sx={{ fontSize: 14 }} />} sx={{ ...kleinerKnopf, color: FARBE.akzent }}>
              Exportieren…
            </Button>
          )}
        </Box>
      )}
      {a.fehlerAn?.id === e.id && <Box sx={{ fontSize: 12, color: FARBE.fehler }}>{a.fehlerAn.grund}</Box>}
    </Box>
  );
}
