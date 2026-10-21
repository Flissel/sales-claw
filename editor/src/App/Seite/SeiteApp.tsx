// Collage-Editor (Freie Fläche Stufe 2, Spec 4.6): Leiste oben, Ebenen links, Seite in der Mitte,
// Eigenschaften rechts, darunter der Assistent (Stufe 3). Einreichen wie im Block-Editor (Stufe 4): die API
// erzeugt dabei die Mail-Fassung und nennt Gründe, wenn es nicht geht (Anrede im Bild, zu groß, Bild fehlt).
// "Prüfen" (Stufe 5): speichert Ungespeichertes und zeigt die Befunde der Schönheitsprüfung rechts; scheitert
// das Einreichen, erscheinen sie von selbst (der Grund der API steht weiter in der Meldung).
// Am Handy (unter HANDY_GRENZE) die Vorschau der gespeicherten Fassung und der Assistent.
// Während einer Runde zeigt die Fläche den Zwischenstand nur zur Anzeige; Bearbeiten ist gesperrt.
// Eingereicht (nurLesen): alles nur lesend - Fläche ohne Griffe, Ebenen, Eigenschaften, Tasten, Speichern
// und Chat gesperrt -, bis der Newsletter zurückgezogen ist.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ArrowBackRounded, FactCheckOutlined, PictureAsPdfOutlined, RedoRounded, SaveOutlined, SendOutlined, UndoRounded } from '@mui/icons-material';
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle,
  IconButton, Snackbar, TextField, ThemeProvider, Tooltip, Typography, useMediaQuery,
} from '@mui/material';

import { HANDY_GRENZE } from '../../handy';
import { fehlerText, pruefungLaden, zurueckziehen, type Start } from '../../pult';
import { chipsAbgleichen, editorEinstecken, einreichenAuftrag, LIEGT_ZUR_FREIGABE, pultStore } from '../../pultZustand';
import { speicherGrund, type Seite } from '../../seite';
import { seitenSicherung, type SeitenStand } from '../../seiteChat';
import { seiteSpeichern } from '../../seitePult';
import { SperrSchicht, useAgentArbeitet } from '../Chat/Sperre';
import { useInert } from '../Chat/sperren';
import { HandyAnsicht, INHALT_HOEHE } from '../Handy/HandyApp';
import { FARBE, gestaltungThema, KOPF_HOEHE, LINKS_BREITE, RECHTS_BREITE, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import SeiteEbenen from './SeiteEbenen';
import SeiteEigenschaften from './SeiteEigenschaften';
import SeiteFlaeche from './SeiteFlaeche';
import SeitePruefung, { befundeVeraltet, type PruefStand } from './SeitePruefung';
import SeitenChat from './SeitenChat';
import { useSeiteTasten } from './seiteTasten';
import { useSeite } from './useSeite';

export const ARBEITET_HINWEIS = 'Der Assistent arbeitet';
export const NEUE_FASSUNG_HINWEIS = 'Neue Fassung vom Assistenten – bitte speichern und neu laden';
export const KONFLIKT_TITEL = 'Inzwischen gibt es eine neuere Fassung';

type Meldung = { art: 'success' | 'error'; text: string } | null;

// Einreichen aus der Leiste (wie PultLeiste): Ungespeichertes speichert der eingesteckte Editor vorher;
// der Grund der API (422) wird zur Fehlermeldung.
export async function seiteEinreichen(): Promise<Meldung> {
  const grund = await einreichenAuftrag();
  return grund === null ? { art: 'success', text: 'Zur Freigabe eingereicht' } : { art: 'error', text: grund };
}

// Doppelklick-Schutz: ein zweiter Klick, bevor React neu gerendert hat, sähe den State noch auf false -
// die Sperre steht deshalb in einem Ref (sperre), nicht im State.
export async function nurEinmal<T>(sperre: { current: boolean }, lauf: () => Promise<T>): Promise<T | undefined> {
  if (sperre.current) return undefined;
  sperre.current = true;
  try {
    return await lauf();
  } finally {
    sperre.current = false;
  }
}

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
  // Die Chat-Runden (fassung_vorher, neueFassungLaden) rechnen mit der Basis im Pult-Zustand.
  useEffect(() => {
    pultStore.setState({ basis });
  }, [basis]);
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
      {handy && <HandyAnsicht start={start} basis={basis} betreff={start.betreff} collage assistent={<SeitenChat ebene={null} hoehe={INHALT_HOEHE} />} />}
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
  const [reicht, setReicht] = useState(false);
  const reichtSperre = useRef(false);
  const [zieht, setZieht] = useState(false);
  const [pruefung, setPruefung] = useState<PruefStand | null>(null);
  const pruefSperre = useRef(false);
  const ungespeichert = z.geaendert || betreff !== gesichert.betreff || vorschautext !== gesichert.vorschautext;
  // Assistent: läuft eine Runde, ist Bearbeiten gesperrt; die Fläche zeigt den Zwischenstand nur an.
  const arbeitet = useAgentArbeitet();
  const zwischenstand = pultStore((p) => p.seitenZwischenstand);
  const fassungWartet = pultStore((p) => p.fassungWartet);
  // Liegt zur Freigabe: nur lesend, bis zurückgezogen (die API lehnt Speichern dann ohnehin ab).
  const nurLesen = pultStore((p) => p.nurLesen);
  const agentSperre = arbeitet !== null || zwischenstand !== null;
  const gesperrt = agentSperre || nurLesen;
  const ebenenRef = useInert<HTMLDivElement>(gesperrt);
  // Die Mitte bleibt bei nurLesen bedienbar zum Scrollen; die Fläche selbst ist gesperrt (keine Auswahl, keine Griffe).
  const mitteRef = useInert<HTMLDivElement>(agentSperre);
  const eigenschaftenRef = useInert<HTMLDivElement>(gesperrt);
  const anzeige = zwischenstand ? { ...z, seite: zwischenstand, auswahl: null } : nurLesen ? { ...z, auswahl: null } : z;
  const gewaehlt = nurLesen || z.auswahl === null ? null : (z.seite.ebenen.find((e) => e.id === z.auswahl) ?? null);

  useSeiteTasten(z, !versteckt && !gesperrt);

  // Neue Fassungen nach einer Runde laden nur ohne Ungespeichertes neu (neueFassungLaden).
  useEffect(() => {
    pultStore.setState({ ungespeichert });
  }, [ungespeichert]);

  // Vor dem Senden an den Assistenten: Ungespeichertes als neue Fassung speichern (Konflikt = Dialog,
  // nichts wird gesendet). Eingesteckt in den Chat-Weg des Pult-Zustands, mit dem jeweils neuesten Stand.
  const aktuellRef = useRef({ z, betreff, vorschautext, basis, ungespeichert });
  aktuellRef.current = { z, betreff, vorschautext, basis, ungespeichert };
  useEffect(() => {
    let gesendet: { seite: Seite; betreff: string; vorschautext: string } | null = null;
    const holen = (): SeitenStand => {
      const a = aktuellRef.current;
      a.z.festschreiben();
      const s = a.z.aktuell();
      gesendet = { seite: s, betreff: a.betreff, vorschautext: a.vorschautext };
      return { seite: s, betreff: a.betreff, vorschautext: a.vorschautext, basis: a.basis, ungespeichert: a.ungespeichert };
    };
    const sichern = seitenSicherung(start, holen, {
      gespeichert: (fassung) => {
        setKonflikt(false);
        setBasis(fassung);
        if (!gesendet) return;
        setGesichert({ betreff: gesendet.betreff, vorschautext: gesendet.vorschautext });
        if (aktuellRef.current.z.aktuell() === gesendet.seite) aktuellRef.current.z.gespeichert();
      },
      konflikt: () => setKonflikt(true),
    });
    return editorEinstecken({ sichern, dokument: () => ({ ...aktuellRef.current.z.aktuell() }) });
  }, [start, setBasis]);
  // Chips zeigen nur Ebenen, die es auf der Seite noch gibt. Erst NACH dem Einstecken (Effekte laufen in
  // dieser Reihenfolge): vorher kennt der Abgleich die Seite nicht.
  useEffect(() => chipsAbgleichen(), [z.seite]);

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

  // Liefert die neue Fassung oder null (nicht gespeichert; die Meldung bzw. der Konflikt-Dialog steht dann da).
  const sichern = async (alsKopie: boolean): Promise<number | null> => {
    if (laeuft || gesperrt) return null;
    z.festschreiben();
    const s = z.aktuell();
    const grund = speicherGrund(s);
    if (grund) {
      setMeldung({ art: 'error', text: fehlerText(grund) });
      return null;
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
      return r.fassung;
    }
    if ('konflikt' in r) {
      setKonflikt(true);
    } else {
      setKonflikt(false);
      setMeldung({ art: 'error', text: fehlerText(r.grund) });
    }
    return null;
  };

  // Befunde einer Fassung in die rechte Spalte (beim gescheiterten Einreichen: die gespeicherte = neueste).
  const pruefungZeigen = async (fassung: number) => {
    setPruefung({ art: 'laedt' });
    const r = await pruefungLaden(start, fassung);
    setPruefung(r.ok ? { art: 'befunde', befunde: r.befunde, fassung } : { art: 'fehler', grund: r.grund });
  };

  // "Prüfen": geprüft wird immer eine gespeicherte Fassung - Ungespeichertes wird vorher gespeichert.
  const pruefenKlick = async () => {
    await nurEinmal(pruefSperre, async () => {
      let fassung = basis;
      if (ungespeichert) {
        const neu = await sichern(false);
        if (neu === null) return;
        fassung = neu;
      }
      await pruefungZeigen(fassung);
    });
  };

  const einreichenKlick = async () => {
    if (reicht || laeuft || gesperrt) return;
    await nurEinmal(reichtSperre, async () => {
      setReicht(true);
      const m = await seiteEinreichen();
      setReicht(false);
      setMeldung(m);
      // Abgelehnt (z. B. harter Befund): die Befunde der neuesten Fassung gleich daneben zeigen.
      if (m?.art === 'error' && start.pruefung_url) void pruefungZeigen(pultStore.getState().basis);
    });
  };

  const zurueckziehenKlick = async () => {
    setZieht(true);
    const r = await zurueckziehen(start);
    if (r.ok) {
      verlassenErlaubt.current = true;
      window.location.reload();
      return;
    }
    setZieht(false);
    setMeldung({ art: 'error', text: r.grund });
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
          disabled={gesperrt}
          inputProps={{ 'aria-label': 'Betreff' }}
          sx={{ flex: '1 1 240px', minWidth: 120, maxWidth: 480 }}
        />
        <Typography sx={{ flex: '1 1 auto', minWidth: 0, fontSize: 12, color: FARBE.gedaempft }} noWrap>
          {nurLesen ? LIEGT_ZUR_FREIGABE : agentSperre ? ARBEITET_HINWEIS : fassungWartet !== null ? NEUE_FASSUNG_HINWEIS : ''}
        </Typography>
        <Tooltip title="Rückgängig (Strg+Z)">
          <span>
            <IconButton aria-label="Rückgängig" onClick={z.zurueck} disabled={gesperrt || !z.kannZurueck}>
              <UndoRounded sx={{ fontSize: 18 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Wiederholen (Strg+Y)">
          <span>
            <IconButton aria-label="Wiederholen" onClick={z.vor} disabled={gesperrt || !z.kannVor}>
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
        {start.pruefung_url && (
          <Tooltip title={ungespeichert ? 'Speichert und prüft die Collage' : `Fassung ${basis} prüfen`}>
            <span>
              <Button
                color="inherit"
                disabled={pruefung?.art === 'laedt' || laeuft || (ungespeichert && gesperrt)}
                onClick={() => void pruefenKlick()}
                startIcon={pruefung?.art === 'laedt' ? <CircularProgress size={14} color="inherit" /> : <FactCheckOutlined sx={{ fontSize: 16 }} />}
                sx={{ flex: 'none' }}
              >
                Prüfen
              </Button>
            </span>
          </Tooltip>
        )}
        <Button
          variant="contained"
          disableElevation
          disabled={laeuft || gesperrt}
          onClick={() => void sichern(false)}
          startIcon={laeuft ? <CircularProgress size={14} color="inherit" /> : <SaveOutlined sx={{ fontSize: 16 }} />}
          sx={{ flex: 'none', mr: 1 }}
        >
          Speichern
        </Button>
        {start.einreichen_url && !nurLesen && (
          <Tooltip title={agentSperre ? 'Gesperrt, bis der Assistent fertig ist' : 'Zur Freigabe einreichen'}>
            <span>
              <Button
                variant="outlined"
                color="success"
                disabled={reicht || laeuft || gesperrt}
                onClick={() => void einreichenKlick()}
                startIcon={reicht ? <CircularProgress size={14} color="inherit" /> : <SendOutlined sx={{ fontSize: 16 }} />}
                sx={{ flex: 'none', mr: 1, whiteSpace: 'nowrap' }}
              >
                {reicht ? 'Reicht ein …' : 'Einreichen'}
              </Button>
            </span>
          </Tooltip>
        )}
        {nurLesen && start.zurueckziehen_url && (
          <Button
            variant="outlined"
            color="inherit"
            disabled={zieht}
            onClick={() => void zurueckziehenKlick()}
            sx={{ flex: 'none', mr: 1, whiteSpace: 'nowrap' }}
          >
            {zieht ? 'Zieht zurück …' : 'Zurückziehen'}
          </Button>
        )}
      </Box>

      <Box ref={ebenenRef} sx={{ bgcolor: FARBE.panel, borderRight: `1px solid ${FARBE.linie}`, minHeight: 0, overflow: 'auto' }}>
        <SeiteEbenen z={z} />
      </Box>

      <Box ref={mitteRef} component="main" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
        <SeiteFlaeche z={anzeige} gesperrt={gesperrt} />
      </Box>

      {/* Während einer Runde: Ebenen und Fläche gesperrt (absolut - nimmt keine Rasterzelle) */}
      {agentSperre && <SperrSchicht text={ARBEITET_HINWEIS} lage={{ position: 'absolute', top: KOPF_HOEHE, left: 0, right: RECHTS_BREITE, bottom: 0, zIndex: 2 }} />}

      {/* Rechts: Eigenschaften, darunter der Assistent */}
      <Box component="aside" aria-label="Eigenschaften" sx={{ bgcolor: FARBE.panel, borderLeft: `1px solid ${FARBE.linie}`, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
          {pruefung && (
            <SeitePruefung
              stand={pruefung}
              veraltet={befundeVeraltet(pruefung, ungespeichert, basis)}
              ebenen={new Set(z.seite.ebenen.map((e) => e.id))}
              onWaehlen={(id) => {
                if (!gesperrt) z.waehlen(id);
              }}
              onSchliessen={() => setPruefung(null)}
            />
          )}
          <Box ref={eigenschaftenRef} aria-disabled={gesperrt ? true : undefined} sx={{ opacity: gesperrt ? 0.4 : 1, pointerEvents: gesperrt ? 'none' : 'auto', transition: 'opacity 150ms ease-out' }}>
            <SeiteEigenschaften z={z} vorschautext={vorschautext} setVorschautext={setVorschautext} />
          </Box>
        </Box>
        <Box sx={{ borderTop: `1px solid ${FARBE.linie}`, flexShrink: 0 }}>
          <SeitenChat ebene={gewaehlt} />
        </Box>
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
