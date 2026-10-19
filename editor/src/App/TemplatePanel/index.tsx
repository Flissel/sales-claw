import React, { useEffect } from 'react';

import { MonitorOutlined, PhoneIphoneOutlined, RedoOutlined, UndoOutlined } from '@mui/icons-material';
import { Alert, Box, IconButton, Stack, SxProps, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';

import EditorBlock from '../../documents/editor/EditorBlock';
import {
  rueckgaengig,
  setSelectedScreenSize,
  useKannRueckgaengig,
  useKannWiederholen,
  useSelectedScreenSize,
  wiederholen,
} from '../../documents/editor/EditorContext';
import { verlaufTaste } from '../../verlaufTasten';
import ToggleInspectorPanelButton from '../InspectorDrawer/ToggleInspectorPanelButton';
import { alterWegHinweis } from '../../pult';
import { pultStore } from '../../pultZustand';
import PultLeiste from '../PultLeiste';
import { useGesperrt } from '../Chat/Sperre';
import { useInert } from '../Chat/sperren';

// Gegenueber dem Beispiel entfernt: Reiter Vorschau/HTML/JSON, JSON-Import und
// -Download, "Share" und die Vorlagen-Seitenleiste. Die massgebliche Vorschau
// ist die des Pults (Knoepfe "Vorschau Mail"/"Vorschau Handy").
const WERKZEUG_HOEHE = 49;

// Ein Zwischenstand des Agenten ist nicht vom Validator geprueft: laesst er sich trotz Vorpruefung
// nicht zeichnen, bleibt der Editor stehen und zeigt einen ruhigen Hinweis bis zum naechsten Stand.
class ZwischenstandFang extends React.Component<{ puls: number; children: React.ReactNode }, { fehler: boolean }> {
  state = { fehler: false };

  static getDerivedStateFromError() {
    return { fehler: true };
  }

  componentDidUpdate(vorher: { puls: number }) {
    if (vorher.puls !== this.props.puls && this.state.fehler) this.setState({ fehler: false });
  }

  render() {
    if (!this.state.fehler) return this.props.children;
    return (
      <Typography variant="body2" color="text.secondary" sx={{ p: 4, textAlign: 'center' }}>
        Dieser Stand lässt sich nicht anzeigen – der Assistent arbeitet weiter.
      </Typography>
    );
  }
}

export default function TemplatePanel() {
  const selectedScreenSize = useSelectedScreenSize();
  const start = pultStore((p) => p.start);
  // Waehrend der Agent arbeitet: Werkzeugleiste und Canvas auch per Tastatur gesperrt.
  const gesperrt = useGesperrt();
  const leisteRef = useInert<HTMLDivElement>(gesperrt);
  const canvasRef = useInert<HTMLDivElement>(gesperrt);
  const puls = pultStore((p) => p.zwischenstand?.puls ?? 0);
  // Wie die Entwurfsseite: der alte Freigabeweg (Telegram -> n8n) laeuft unabhaengig weiter.
  const alterWeg = start ? alterWegHinweis(start) : null;
  // Rueckgaengig/Wiederholen (E11): gesperrt umfasst Assistent und "liegt zur Freigabe".
  const zurueckDa = useKannRueckgaengig();
  const vorDa = useKannWiederholen();
  const kannZurueck = zurueckDa && !gesperrt;
  const kannVor = vorDa && !gesperrt;
  useEffect(() => {
    const taste = (ev: KeyboardEvent) => {
      const { nurLesen, gestaltungOffen } = pultStore.getState();
      // Im Gestaltungsfenster gelten dessen eigene Tasten.
      const aktion = verlaufTaste(ev, gesperrt || nurLesen || gestaltungOffen !== null);
      if (!aktion) return;
      ev.preventDefault();
      if (aktion === 'rueckgaengig') rueckgaengig();
      else wiederholen();
    };
    window.addEventListener('keydown', taste);
    return () => window.removeEventListener('keydown', taste);
  }, [gesperrt]);

  let mainBoxSx: SxProps = {
    my: 3,
    mx: 'auto',
    borderRadius: 2,
    boxShadow: 3,
    overflow: 'hidden',
    backgroundColor: 'background.paper',
  };
  if (selectedScreenSize === 'mobile') {
    mainBoxSx = {
      ...mainBoxSx,
      width: 370,
      height: 800,
    };
  }

  const handleScreenSizeChange = (_: unknown, value: unknown) => {
    switch (value) {
      case 'mobile':
      case 'desktop':
        setSelectedScreenSize(value);
        return;
      default:
        setSelectedScreenSize('desktop');
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <Box sx={{ flexShrink: 0, zIndex: 'appBar' }}>
        <PultLeiste />
        <Stack
          ref={leisteRef}
          sx={{
            height: WERKZEUG_HOEHE,
            borderBottom: 1,
            borderColor: 'divider',
            backgroundColor: 'background.paper',
            px: 1,
          }}
          direction="row"
          justifyContent="space-between"
          alignItems="center"
        >
          <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>
            Abschnitte links hineinziehen, Block anklicken zum Bearbeiten.
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Tooltip title="Rückgängig (Strg+Z)">
                <span>
                  <IconButton size="small" aria-label="Rückgängig (Strg+Z)" disabled={!kannZurueck} onClick={() => rueckgaengig()}>
                    <UndoOutlined fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="Wiederholen (Strg+Umschalt+Z)">
                <span>
                  <IconButton
                    size="small"
                    aria-label="Wiederholen (Strg+Umschalt+Z)"
                    disabled={!kannVor}
                    onClick={() => wiederholen()}
                  >
                    <RedoOutlined fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </Stack>
            <ToggleButtonGroup value={selectedScreenSize} exclusive size="small" onChange={handleScreenSizeChange}>
              <ToggleButton value="desktop">
                <Tooltip title="Breite Ansicht">
                  <MonitorOutlined fontSize="small" />
                </Tooltip>
              </ToggleButton>
              <ToggleButton value="mobile">
                <Tooltip title="Schmale Ansicht (Handy)">
                  <PhoneIphoneOutlined fontSize="small" />
                </Tooltip>
              </ToggleButton>
            </ToggleButtonGroup>
            <ToggleInspectorPanelButton />
          </Stack>
        </Stack>
        {alterWeg && (
          <Alert severity="warning" data-testid="alter-weg" sx={{ borderRadius: 0 }}>
            {alterWeg}
          </Alert>
        )}
      </Box>
      <Box
        data-canvas
        sx={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          minWidth: 370,
          bgcolor: 'background.default',
        }}
      >
        {/* inert nur auf dem Inhalt: der Rahmen bleibt per Rad/Touch/Scrollbalken scrollbar. */}
        <Box ref={canvasRef} data-canvas-inhalt>
          <Box sx={mainBoxSx}>
            <ZwischenstandFang puls={puls}>
              <EditorBlock id="root" />
            </ZwischenstandFang>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
