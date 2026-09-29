import React, { useEffect, useState } from 'react';

import { ArrowBackOutlined, PhoneIphoneOutlined, SaveOutlined, MailOutlined } from '@mui/icons-material';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import { getDocument } from '../documents/editor/EditorContext';
import { fehlerText, speichern } from '../pult';
import { alsUngespeichert, pultStore } from '../pultZustand';

// Leiste oben: Betreff, Vorschautext, Speichern, Vorschau, Zurueck.
// Die Pruefung, ob der Inhalt erlaubt ist, macht das Pult beim Speichern.

type Meldung = { art: 'success' | 'error' | 'info'; text: string } | null;

export const PULT_LEISTE_HOEHE = 64;

export default function PultLeiste() {
  const start = pultStore((p) => p.start);
  const betreff = pultStore((p) => p.betreff);
  const vorschautext = pultStore((p) => p.vorschautext);
  const basis = pultStore((p) => p.basis);
  const ungespeichert = pultStore((p) => p.ungespeichert);

  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<Meldung>(null);
  const [konflikt, setKonflikt] = useState<string | null>(null);
  const [verlassen, setVerlassen] = useState(false);

  // Beim Schliessen des Tabs mit ungespeicherten Aenderungen warnt der Browser.
  useEffect(() => {
    const warnen = (ev: BeforeUnloadEvent) => {
      if (pultStore.getState().ungespeichert) {
        ev.preventDefault();
        ev.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warnen);
    return () => window.removeEventListener('beforeunload', warnen);
  }, []);

  if (!start) return null;

  const sichern = async (alsKopie: boolean) => {
    setLaeuft(true);
    const { betreff: b, vorschautext: v, basis: n } = pultStore.getState();
    const dokVorher = getDocument();
    const e = await speichern(start, dokVorher, b, v, n, alsKopie);
    setLaeuft(false);
    if (e.ok) {
      const nachher = pultStore.getState();
      // Nur als gespeichert markieren, wenn waehrend des Speicherns nichts geaendert wurde.
      const unveraendert = getDocument() === dokVorher && nachher.betreff === b && nachher.vorschautext === v;
      pultStore.setState({ basis: e.fassung, ungespeichert: !unveraendert });
      setKonflikt(null);
      setMeldung({
        art: 'success',
        text: alsKopie ? `Als Kopie gespeichert als Fassung ${e.fassung}` : `Gespeichert als Fassung ${e.fassung}`,
      });
      return;
    }
    if (e.konflikt && !alsKopie) {
      setKonflikt(e.grund);
      return;
    }
    setKonflikt(null);
    setMeldung({ art: 'error', text: fehlerText(e.grund) });
  };

  const vorschau = (format: 'mail' | 'handy') => {
    const trenner = start.vorschau_url.includes('?') ? '&' : '?';
    window.open(`${start.vorschau_url}${trenner}fassung=${basis}&format=${format}`, '_blank', 'noopener');
  };

  const zurueck = () => {
    if (ungespeichert) {
      setVerlassen(true);
      return;
    }
    window.location.href = start.zurueck_url;
  };

  const vorschauHinweis = ungespeichert ? 'Erst speichern – die Vorschau zeigt die gespeicherte Fassung' : '';

  return (
    <>
      <Stack
        direction="row"
        alignItems="center"
        spacing={1.5}
        sx={{
          height: PULT_LEISTE_HOEHE,
          px: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
          bgcolor: 'background.paper',
        }}
      >
        <Button size="small" startIcon={<ArrowBackOutlined />} onClick={zurueck} sx={{ flexShrink: 0 }}>
          Zurück zum Entwurf
        </Button>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, flexShrink: 0 }}>
          Newsletter
        </Typography>
        <TextField
          size="small"
          label="Betreff"
          value={betreff}
          onChange={(ev) => {
            pultStore.setState({ betreff: ev.target.value });
            alsUngespeichert();
          }}
          sx={{ flex: 2, minWidth: 160 }}
        />
        <TextField
          size="small"
          label="Vorschautext"
          value={vorschautext}
          onChange={(ev) => {
            pultStore.setState({ vorschautext: ev.target.value });
            alsUngespeichert();
          }}
          sx={{ flex: 2, minWidth: 140 }}
        />
        <Typography
          variant="body2"
          color={ungespeichert ? 'warning.main' : 'text.secondary'}
          sx={{ flexShrink: 0, minWidth: 190 }}
        >
          {ungespeichert ? `Fassung ${basis} · ungespeicherte Änderungen` : `Fassung ${basis} · gespeichert`}
        </Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<SaveOutlined />}
          disabled={laeuft}
          onClick={() => sichern(false)}
          sx={{ flexShrink: 0 }}
        >
          {laeuft ? 'Speichert …' : 'Speichern'}
        </Button>
        <Tooltip title={vorschauHinweis}>
          <span>
            <Button
              size="small"
              variant="outlined"
              startIcon={<MailOutlined />}
              disabled={ungespeichert || laeuft}
              onClick={() => vorschau('mail')}
              sx={{ flexShrink: 0 }}
            >
              Vorschau Mail
            </Button>
          </span>
        </Tooltip>
        <Tooltip title={vorschauHinweis}>
          <span>
            <Button
              size="small"
              variant="outlined"
              startIcon={<PhoneIphoneOutlined />}
              disabled={ungespeichert || laeuft}
              onClick={() => vorschau('handy')}
              sx={{ flexShrink: 0 }}
            >
              Vorschau Handy
            </Button>
          </span>
        </Tooltip>
      </Stack>

      <Dialog open={konflikt !== null} onClose={() => setKonflikt(null)}>
        <DialogTitle>Jemand anderes hat inzwischen gespeichert</DialogTitle>
        <DialogContent>
          <DialogContentText>{konflikt}</DialogContentText>
          <DialogContentText sx={{ mt: 2 }}>
            „Neu laden“ verwirft deine Änderungen und zeigt die neueste Fassung. „Als Kopie behalten“ speichert deine
            Fassung trotzdem als neueste.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              pultStore.setState({ ungespeichert: false });
              window.location.reload();
            }}
          >
            Neu laden
          </Button>
          <Button variant="contained" disabled={laeuft} onClick={() => sichern(true)}>
            Als Kopie behalten
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={verlassen} onClose={() => setVerlassen(false)}>
        <DialogTitle>Ungespeicherte Änderungen</DialogTitle>
        <DialogContent>
          <DialogContentText>Wenn du jetzt zurückgehst, sind deine Änderungen weg.</DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVerlassen(false)}>Hierbleiben</Button>
          <Button
            color="error"
            onClick={() => {
              pultStore.setState({ ungespeichert: false });
              window.location.href = start.zurueck_url;
            }}
          >
            Ohne Speichern zurück
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={meldung !== null}
        autoHideDuration={meldung?.art === 'error' ? null : 4000}
        onClose={(_, grund) => {
          if (grund !== 'clickaway') setMeldung(null);
        }}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {meldung ? (
          <Alert severity={meldung.art} onClose={() => setMeldung(null)} variant="filled">
            {meldung.text}
          </Alert>
        ) : (
          <span />
        )}
      </Snackbar>
    </>
  );
}
