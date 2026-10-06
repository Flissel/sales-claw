// Stopp des laufenden Agenten (Spec 2026-10-02-newsletter-agent-live §3.2): fragt, was mit den
// bisherigen Schritten passieren soll. Behalten = letzter Zwischenstand wird Fassung (der Server
// prueft ihn wie jede Antwort), Verwerfen = keine neue Fassung. Stil wie das Gestaltungsfenster.
import React, { useMemo, useState } from 'react';

import { ErrorOutlineRounded, StopRounded } from '@mui/icons-material';
import { Box, Button, CircularProgress, Dialog, ThemeProvider } from '@mui/material';

import type { StoppArt } from '../../chat';
import { schrittText } from '../../live';
import { chatStoppen, pultStore } from '../../pultZustand';
import { FARBE, gestaltungThema, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

export default function StoppDialog({ offen, onClose }: { offen: boolean; onClose: () => void }) {
  const thema = useMemo(gestaltungThema, []);
  return (
    <ThemeProvider theme={thema}>
      <Dialog
        open={offen}
        onClose={onClose}
        maxWidth={false}
        aria-labelledby="stopp-titel"
        PaperProps={{ sx: { width: 440, maxWidth: 'calc(100vw - 32px)', bgcolor: FARBE.panel, backgroundImage: 'none', border: `1px solid ${FARBE.linie}`, borderRadius: '12px', fontFamily: UI_SCHRIFT } }}
      >
        {offen && <Inhalt onClose={onClose} />}
      </Dialog>
    </ThemeProvider>
  );
}

function Inhalt({ onClose }: { onClose: () => void }) {
  const zeile = pultStore((p) => schrittText(p.chat?.live ?? null));
  const [laeuft, setLaeuft] = useState<StoppArt | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const waehlen = async (art: StoppArt) => {
    if (laeuft) return;
    setLaeuft(art);
    setFehler(null);
    const grund = await chatStoppen(art);
    setLaeuft(null);
    if (grund) setFehler(grund);
    else onClose();
  };

  const knopfLaeuft = (art: StoppArt) => (laeuft === art ? <CircularProgress size={14} color="inherit" /> : undefined);

  return (
    <Box sx={{ color: FARBE.text, fontFamily: UI_SCHRIFT }}>
      <Box sx={{ px: 3, pt: 2.5, pb: 1, display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <StopRounded sx={{ fontSize: 18, color: FARBE.akzent }} />
        <Box component="h2" id="stopp-titel" sx={{ m: 0, fontSize: 16, fontWeight: 600 }}>
          Assistent stoppen?
        </Box>
      </Box>
      <Box sx={{ px: 3, pb: 2.5, fontSize: 13, lineHeight: 1.6, color: FARBE.gedaempft }}>
        {zeile ? (
          <>
            Zuletzt: <Box component="span" sx={{ color: FARBE.text }}>{zeile}</Box>.{' '}
          </>
        ) : (
          'Er hat noch keinen Schritt abgeschlossen. '
        )}
        Behältst du die bisherigen Schritte, werden sie als neue Fassung gespeichert.
      </Box>
      <Box sx={{ px: 3, py: 2, borderTop: `1px solid ${FARBE.linie}`, display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
        {fehler && (
          <Box role="alert" sx={{ display: 'flex', alignItems: 'center', gap: 0.75, fontSize: 12, color: FARBE.fehler, width: '100%', mb: 0.5 }}>
            <ErrorOutlineRounded sx={{ fontSize: 14 }} />
            {fehler}
          </Box>
        )}
        <Button onClick={onClose} color="inherit" autoFocus disabled={laeuft !== null} sx={{ color: FARBE.gedaempft, '&:hover': { color: FARBE.text, bgcolor: FARBE.hover } }}>
          Abbrechen
        </Button>
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            color="inherit"
            disabled={laeuft !== null}
            onClick={() => void waehlen('verwerfen')}
            startIcon={knopfLaeuft('verwerfen')}
            sx={{ borderColor: FARBE.linie, color: FARBE.text, '&:hover': { borderColor: FARBE.gedaempft, bgcolor: FARBE.hover } }}
          >
            Verwerfen
          </Button>
          <Button variant="contained" disableElevation disabled={laeuft !== null} onClick={() => void waehlen('behalten')} startIcon={knopfLaeuft('behalten')}>
            Bisherige Schritte behalten
          </Button>
        </Box>
      </Box>
    </Box>
  );
}
