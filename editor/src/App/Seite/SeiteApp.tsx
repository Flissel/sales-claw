// Collage-Editor (Freie Fläche Stufe 2, Spec 4.6): Leiste oben, Ebenen links, Seite in der Mitte,
// Eigenschaften rechts. Kein Assistent und kein Einreichen für Collagen (die API sperrt beides).
// Am Handy (unter HANDY_GRENZE) nur die Vorschau der gespeicherten Fassung.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ArrowBackRounded, PictureAsPdfOutlined, RedoRounded, SaveOutlined, UndoRounded } from '@mui/icons-material';
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle,
  IconButton, Snackbar, TextField, ThemeProvider, Tooltip, Typography, useMediaQuery,
} from '@mui/material';

import { HANDY_GRENZE } from '../../handy';
import { fehlerText, type Start } from '../../pult';
import { speicherGrund, type Seite } from '../../seite';
import { seiteSpeichern } from '../../seitePult';
import { HandyAnsicht } from '../Handy/HandyApp';
import { FARBE, gestaltungThema, KOPF_HOEHE, LINKS_BREITE, RECHTS_BREITE, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import SeiteEbenen from './SeiteEbenen';
import SeiteEigenschaften from './SeiteEigenschaften';
import SeiteFlaeche from './SeiteFlaeche';
import { useSeiteTasten } from './seiteTasten';
import { useSeite } from './useSeite';

export const ASSISTENT_HINWEIS = 'Der Assistent kommt für Collage-Newsletter in der nächsten Stufe.';
export const KONFLIKT_TITEL = 'Inzwischen gibt es eine neuere Fassung';

type Meldung = { art: 'success' | 'error'; text: string } | null;

export function pdfAdresse(vorschauUrl: string, basis: number): string {
  const trenner = vorschauUrl.includes('?') ? '&' : '?';
  return `${vorschauUrl}${trenner}fassung=${basis}&format=pdf`;
}

export default function SeiteApp({ start }: { start: Start }) {
  const handy = useMediaQuery(HANDY_GRENZE);
  const thema = useMemo(gestaltungThema, []);
  const seite = start.seite;
  // Basis hier oben: am Handy zeigt die Vorschau die zuletzt gespeicherte Fassung.
  const [basis, setBasis] = useState(start.basis_fassung);
  if (!seite) {
    return (
      <Typography sx={{ p: 4 }}>
        Die Collage konnte nicht geladen werden. Bitte die Seite neu laden oder zurück zum Entwurf gehen.
      </Typography>
    );
  }
  // Der Arbeitsplatz bleibt auch am Handy montiert (nur versteckt): ein schmaleres Fenster
  // verwirft keine ungespeicherten Änderungen.
  return (
    <>
      {handy && <HandyAnsicht start={start} basis={basis} betreff={start.betreff} ohneAssistent />}
      <ThemeProvider theme={thema}>
        <Arbeitsplatz start={start} anfang={seite} basis={basis} setBasis={setBasis} versteckt={handy} />
      </ThemeProvider>
    </>
  );
}

type ArbeitsplatzProps = { start: Start; anfang: Seite; basis: number; setBasis: (b: number) => void; versteckt: boolean };

function Arbeitsplatz({ start, anfang, basis, setBasis, versteckt }: ArbeitsplatzProps) {
  const z = useSeite(anfang);
  const [betreff, setBetreff] = useState(start.betreff ?? '');
  const [vorschautext, setVorschautext] = useState(start.vorschautext ?? '');
  const [gesichert, setGesichert] = useState({ betreff: start.betreff ?? '', vorschautext: start.vorschautext ?? '' });
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldungRoh] = useState<Meldung>(null);
  const [meldungOffen, setMeldungOffen] = useState(false);
  const setMeldung = (m: Meldung) => {
    if (m) setMeldungRoh(m);
    setMeldungOffen(m !== null);
  };
  const [konflikt, setKonflikt] = useState(false);
  const ungespeichert = z.geaendert || betreff !== gesichert.betreff || vorschautext !== gesichert.vorschautext;

  useSeiteTasten(z, !versteckt);

  // Tab schliessen oder weggehen mit ungespeicherten Änderungen: der Browser fragt nach.
  const ungespeichertRef = useRef(ungespeichert);
  ungespeichertRef.current = ungespeichert;
  const verlassenErlaubt = useRef(false);
  useEffect(() => {
    const warnen = (ev: BeforeUnloadEvent) => {
      if (ungespeichertRef.current && !verlassenErlaubt.current) {
        ev.preventDefault();
        ev.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warnen);
    return () => window.removeEventListener('beforeunload', warnen);
  }, []);

  const sichern = async (alsKopie: boolean) => {
    if (laeuft) return;
    z.festschreiben();
    const s = z.aktuell();
    const grund = speicherGrund(s);
    if (grund) {
      setMeldung({ art: 'error', text: fehlerText(grund) });
      return;
    }
    setLaeuft(true);
    const stand = { betreff, vorschautext };
    const r = await seiteSpeichern(start, s, stand.betreff, stand.vorschautext, basis, alsKopie);
    setLaeuft(false);
    if (r.ok) {
      setKonflikt(false);
      setBasis(r.fassung);
      setGesichert(stand);
      // Nur wenn seither nichts mehr geändert wurde, gilt der Stand als gespeichert.
      if (z.aktuell() === s) z.gespeichert();
      setMeldung({ art: 'success', text: alsKopie ? `Als Kopie gespeichert als Fassung ${r.fassung}` : `Gespeichert als Fassung ${r.fassung}` });
    } else if ('konflikt' in r) {
      setKonflikt(true);
    } else {
      setKonflikt(false);
      setMeldung({ art: 'error', text: fehlerText(r.grund) });
    }
  };

  return (
    <Box
      data-tasten
      tabIndex={-1}
      aria-label="Collage bearbeiten"
      sx={{
        position: 'fixed', inset: 0, display: versteckt ? 'none' : 'grid', outline: 'none',
        gridTemplateColumns: `${LINKS_BREITE}px minmax(0, 1fr) ${RECHTS_BREITE}px`,
        gridTemplateRows: `${KOPF_HOEHE}px minmax(0, 1fr)`,
        bgcolor: FARBE.geruest, color: FARBE.text, fontFamily: UI_SCHRIFT,
      }}
    >
      <Box component="header" sx={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 1.5, px: 1, bgcolor: FARBE.panel, borderBottom: `1px solid ${FARBE.linie}`, minWidth: 0 }}>
        <Button href={start.zurueck_url} color="inherit" startIcon={<ArrowBackRounded sx={{ fontSize: 18 }} />} sx={{ flex: 'none', '&:hover': { bgcolor: FARBE.hover } }}>
          Zurück
        </Button>
        <TextField
          size="small"
          placeholder="Betreff"
          value={betreff}
          onChange={(ev) => setBetreff(ev.target.value)}
          inputProps={{ 'aria-label': 'Betreff' }}
          sx={{ flex: '1 1 240px', minWidth: 120, maxWidth: 480 }}
        />
        <Typography sx={{ flex: '1 1 auto', minWidth: 0, fontSize: 12, color: FARBE.gedaempft }} noWrap title={ASSISTENT_HINWEIS}>
          {ASSISTENT_HINWEIS}
        </Typography>
        <Tooltip title="Rückgängig (Strg+Z)">
          <span>
            <IconButton aria-label="Rückgängig" onClick={z.zurueck} disabled={!z.kannZurueck}>
              <UndoRounded sx={{ fontSize: 18 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Wiederholen (Strg+Y)">
          <span>
            <IconButton aria-label="Wiederholen" onClick={z.vor} disabled={!z.kannVor}>
              <RedoRounded sx={{ fontSize: 18 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={ungespeichert ? 'Erst speichern – das PDF zeigt die gespeicherte Fassung' : `Fassung ${basis} als PDF`}>
          <span>
            <Button
              color="inherit"
              disabled={ungespeichert}
              href={pdfAdresse(start.vorschau_url, basis)}
              target="_blank"
              rel="noopener"
              startIcon={<PictureAsPdfOutlined sx={{ fontSize: 16 }} />}
            >
              Als PDF
            </Button>
          </span>
        </Tooltip>
        <Button
          variant="contained"
          disableElevation
          disabled={laeuft}
          onClick={() => void sichern(false)}
          startIcon={laeuft ? <CircularProgress size={14} color="inherit" /> : <SaveOutlined sx={{ fontSize: 16 }} />}
          sx={{ flex: 'none', mr: 1 }}
        >
          Speichern
        </Button>
      </Box>

      <Box sx={{ bgcolor: FARBE.panel, borderRight: `1px solid ${FARBE.linie}`, minHeight: 0, overflow: 'auto' }}>
        <SeiteEbenen z={z} />
      </Box>

      <Box component="main" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
        <SeiteFlaeche z={z} />
      </Box>

      <Box component="aside" aria-label="Eigenschaften" sx={{ bgcolor: FARBE.panel, borderLeft: `1px solid ${FARBE.linie}`, minHeight: 0, overflowY: 'auto' }}>
        <SeiteEigenschaften z={z} vorschautext={vorschautext} setVorschautext={setVorschautext} />
      </Box>

      <Snackbar open={meldungOffen} autoHideDuration={meldung?.art === 'error' ? null : 4000} onClose={() => setMeldung(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity={meldung?.art ?? 'success'} onClose={() => setMeldung(null)}>{meldung?.text}</Alert>
      </Snackbar>

      <Dialog open={konflikt} onClose={() => setKonflikt(false)}>
        <DialogTitle>{KONFLIKT_TITEL}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            „Neu laden“ verwirft deine Änderungen und zeigt die neueste Fassung. „Als Kopie behalten“ speichert deine
            Collage trotzdem als neueste Fassung.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            color="inherit"
            onClick={() => {
              verlassenErlaubt.current = true;
              window.location.reload();
            }}
          >
            Neu laden
          </Button>
          <Button variant="contained" disabled={laeuft} onClick={() => void sichern(true)}>
            Als Kopie behalten
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
