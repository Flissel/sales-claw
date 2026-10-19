import React, { useEffect, useState } from 'react';

import {
  ArrowBackOutlined,
  PhoneIphoneOutlined,
  PictureAsPdfOutlined,
  SaveOutlined,
  MailOutlined,
  SendOutlined,
  VisibilityOutlined,
} from '@mui/icons-material';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import { fehlerText, firmaEtikett } from '../pult';
import { alsUngespeichert, einreichenAuftrag, newsletterSichern, pultStore } from '../pultZustand';

import { useAgentArbeitet } from './Chat/Sperre';
import { LiegtBand, MarkeBand, RueckmeldungBand } from './FreigabeBand';

// Leiste oben: Betreff, Vorschautext, Speichern, Vorschau, Zurueck.
// Die Pruefung, ob der Inhalt erlaubt ist, macht das Pult beim Speichern.

type Meldung = { art: 'success' | 'error' | 'info'; text: string } | null;

// Zwei Zeilen (Design-Review 19.10.): in einer Zeile brauchte die Leiste 1316 px und lief
// bis 1920 px Fensterbreite ueber ("Vorschau Handy" abgeschnitten). Oben Status und Aktionen,
// unten Betreff und Vorschautext.
const ZEILE = 52;
export const PULT_LEISTE_HOEHE = 2 * ZEILE;

export default function PultLeiste() {
  const start = pultStore((p) => p.start);
  const etikett = firmaEtikett(start?.mandant);
  const betreff = pultStore((p) => p.betreff);
  const vorschautext = pultStore((p) => p.vorschautext);
  const basis = pultStore((p) => p.basis);
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const stand = pultStore((p) => p.stand);
  const neuesBild = pultStore((p) => p.meldung);
  const nurLesen = pultStore((p) => p.nurLesen);
  // Waehrend der Agent arbeitet, lehnt der Server Handspeichern ab ("Der Assistent arbeitet gerade").
  const agent = useAgentArbeitet();

  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<Meldung>(null);
  const [konflikt, setKonflikt] = useState<string | null>(null);
  const [verlassen, setVerlassen] = useState(false);
  const [reicht, setReicht] = useState(false);
  const [vorschauMenue, setVorschauMenue] = useState<HTMLElement | null>(null);

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
    const e = await newsletterSichern(alsKopie);
    setLaeuft(false);
    if (e.ok) {
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

  const einreichenKlick = async () => {
    setReicht(true);
    const grund = await einreichenAuftrag();
    setReicht(false);
    if (grund === null) {
      setKonflikt(null);
      setMeldung({ art: 'success', text: 'Zur Freigabe eingereicht' });
    } else {
      setMeldung({ art: 'error', text: grund });
    }
  };

  const vorschau = (format: 'mail' | 'handy' | 'pdf') => {
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

  const neueFassung = stand !== null && stand.fassung > basis ? stand.fassung : null;
  // Ohne ungespeicherte Aenderungen direkt neu laden, sonst ueber den Konflikt-Dialog.
  const neueFassungLaden = () => {
    if (pultStore.getState().ungespeichert) {
      setKonflikt(
        'Der Agent hat eine neue Fassung gespeichert, du hast aber ungespeicherte Änderungen. Neue Bilder vom Agenten liegen auch in den Medien.',
      );
      return;
    }
    window.location.reload();
  };

  const standText = agent
    ? `Fassung ${basis} · ${agent}`
    : ungespeichert
      ? `Fassung ${basis} · ungespeicherte Änderungen`
      : `Fassung ${basis} · gespeichert`;
  const vorschauHinweis = ungespeichert ? 'Erst speichern – die Vorschau zeigt die gespeicherte Fassung' : '';

  return (
    <>
      <Box sx={{ height: PULT_LEISTE_HOEHE, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ height: ZEILE, px: 1, minWidth: 0 }}>
          <Tooltip title="Zurück zum Entwurf">
            <IconButton size="small" aria-label="Zurück zum Entwurf" onClick={zurueck}>
              <ArrowBackOutlined fontSize="small" />
            </IconButton>
          </Tooltip>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, flexShrink: 0 }}>
            Newsletter
          </Typography>
          {etikett !== null && (
            <Tooltip title="Firma dieses Newsletters">
              <Chip size="small" variant="outlined" label={etikett} sx={{ flexShrink: 0 }} />
            </Tooltip>
          )}
          <Typography
            variant="body2"
            noWrap
            title={standText}
            color={ungespeichert ? 'warning.main' : 'text.secondary'}
            sx={{ flex: 1, minWidth: 0 }}
          >
            {standText}
          </Typography>
          <Tooltip title={agent ? 'Gesperrt, bis der Assistent fertig ist' : ''}>
            <span>
              <Button
                variant="contained"
                size="small"
                startIcon={<SaveOutlined />}
                disabled={laeuft || agent !== null || nurLesen}
                onClick={() => sichern(false)}
                sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
              >
                {laeuft ? 'Speichert …' : 'Speichern'}
              </Button>
            </span>
          </Tooltip>
          {start.einreichen_url && !nurLesen && (
            <Tooltip title={agent ? 'Gesperrt, bis der Assistent fertig ist' : 'Zur Freigabe einreichen'}>
              <span>
                <Button
                  variant="outlined"
                  size="small"
                  color="success"
                  startIcon={<SendOutlined />}
                  disabled={reicht || laeuft || agent !== null}
                  onClick={() => void einreichenKlick()}
                  sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
                >
                  {reicht ? 'Reicht ein …' : 'Einreichen'}
                </Button>
              </span>
            </Tooltip>
          )}
          <Tooltip title={vorschauHinweis}>
            <span>
              <Button
                size="small"
                variant="outlined"
                startIcon={<VisibilityOutlined />}
                disabled={ungespeichert || laeuft}
                onClick={(ev) => setVorschauMenue(ev.currentTarget)}
                sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
              >
                Vorschau
              </Button>
            </span>
          </Tooltip>
          <Menu anchorEl={vorschauMenue} open={vorschauMenue !== null} onClose={() => setVorschauMenue(null)}>
            <MenuItem
              onClick={() => {
                setVorschauMenue(null);
                vorschau('mail');
              }}
            >
              <ListItemIcon>
                <MailOutlined fontSize="small" />
              </ListItemIcon>
              Vorschau Mail
            </MenuItem>
            <MenuItem
              onClick={() => {
                setVorschauMenue(null);
                vorschau('handy');
              }}
            >
              <ListItemIcon>
                <PhoneIphoneOutlined fontSize="small" />
              </ListItemIcon>
              Vorschau Handy
            </MenuItem>
            {/* Paket C3 (19.10.2026): derselbe Newsletter als A4-PDF, von der API mit Chromium gesetzt */}
            <MenuItem
              onClick={() => {
                setVorschauMenue(null);
                vorschau('pdf');
              }}
            >
              <ListItemIcon>
                <PictureAsPdfOutlined fontSize="small" />
              </ListItemIcon>
              Als PDF
            </MenuItem>
          </Menu>
        </Stack>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ height: ZEILE, px: 1.5 }}>
          <TextField
            size="small"
            label="Betreff"
            value={betreff}
            disabled={agent !== null}
            onChange={(ev) => {
              pultStore.setState({ betreff: ev.target.value });
              alsUngespeichert();
            }}
            sx={{ flex: 1, minWidth: 0 }}
          />
          <TextField
            size="small"
            label="Vorschautext"
            value={vorschautext}
            disabled={agent !== null}
            onChange={(ev) => {
              pultStore.setState({ vorschautext: ev.target.value });
              alsUngespeichert();
            }}
            sx={{ flex: 1, minWidth: 0 }}
          />
        </Stack>
      </Box>
      <RueckmeldungBand />
      <LiegtBand />
      <MarkeBand />
      {neueFassung !== null && (
        <Alert
          severity="info"
          data-testid="neue-fassung"
          sx={{ borderRadius: 0 }}
          action={
            <Button color="inherit" size="small" onClick={neueFassungLaden}>
              Laden
            </Button>
          }
        >
          Neue Fassung vom Agenten ({neueFassung}) – laden
        </Alert>
      )}

      {neuesBild !== null && (
        <Alert
          severity="success"
          data-testid="neues-bild"
          sx={{ borderRadius: 0 }}
          onClose={() => pultStore.setState({ meldung: null })}
        >
          {neuesBild.text}
        </Alert>
      )}

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
          <Button variant="contained" disabled={laeuft || agent !== null} onClick={() => sichern(true)}>
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

