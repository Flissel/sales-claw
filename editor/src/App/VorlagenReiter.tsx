// Reiter "Vorlagen" der linken Leiste (Plan 2026-10-19 E8/E9): freigegebene Vorlagen der Firma
// dieses Newsletters mit Mini-Vorschau, "Als neuer Entwurf" und "Auf diesen Entwurf anwenden …".
import React, { useCallback, useEffect, useState } from 'react';

import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';

import { Start, vorlageAlsNeu, vorlageAnwenden, VorlageInfo, vorlagenListe } from '../pult';
import { LIEGT_ZUR_FREIGABE, pultStore } from '../pultZustand';

export const TITEL_MAX = 200;
// Mini-Vorschau: die Vorlage wird 600 px breit gezeichnet und auf 0,34 verkleinert.
const RAHMEN_BREITE = 600;
const MASSSTAB = 0.34;
const BOX_BREITE = 204;
const BOX_HOEHE = 160;

export function anwendenText(basis: number): string {
  return `Aufbau, Gestaltung, Texte und Bilder werden ersetzt. Betreff und Vorschautext bleiben. Deine Fassung ${basis} bleibt im Verlauf.`;
}

// Warum "Anwenden" gerade nicht geht (null = frei).
export function anwendenSperre(ungespeichert: boolean, nurLesen: boolean): string | null {
  if (nurLesen) return LIEGT_ZUR_FREIGABE;
  if (ungespeichert) return 'Erst speichern';
  return null;
}

export function titelFehler(titel: string): string | null {
  const t = titel.trim();
  if (!t) return 'Bitte einen Titel eingeben';
  if (Array.from(t).length > TITEL_MAX) return `Höchstens ${TITEL_MAX} Zeichen`;
  return null;
}

// Anwenden; Erfolg laedt den Editor mit der neuen Fassung neu. Liefert null oder den Grund (bleibt im Dialog).
export async function anwendenAusfuehren(start: Start, vorlage: string, basis: number): Promise<string | null> {
  const e = await vorlageAnwenden(start, vorlage, basis);
  if (!e.ok) return e.grund;
  window.location.reload();
  return null;
}

// Neuer Entwurf aus der Vorlage; Erfolg oeffnet ihn. Liefert null oder den Grund.
export async function alsNeuAusfuehren(start: Start, vorlage: string, titel: string): Promise<string | null> {
  const fehler = titelFehler(titel);
  if (fehler) return fehler;
  const e = await vorlageAlsNeu(start, vorlage, titel.trim());
  if (!e.ok) return e.grund;
  window.location.href = e.editorUrl;
  return null;
}

function Vorschau({ src, name }: { src: string; name: string }) {
  return (
    <Box
      sx={{
        width: BOX_BREITE,
        maxWidth: '100%',
        height: BOX_HOEHE,
        overflow: 'hidden',
        borderRadius: 1,
        border: 1,
        borderColor: 'divider',
        bgcolor: 'background.default',
        pointerEvents: 'none',
      }}
    >
      <Box
        component="iframe"
        src={src}
        title={`Vorschau der Vorlage ${name}`}
        sandbox=""
        loading="lazy"
        tabIndex={-1}
        aria-hidden="true"
        sx={{
          width: RAHMEN_BREITE,
          height: Math.ceil(BOX_HOEHE / MASSSTAB),
          border: 0,
          transform: `scale(${MASSSTAB})`,
          transformOrigin: 'top left',
          display: 'block',
        }}
      />
    </Box>
  );
}

type ListeProps = {
  start: Start;
  // 'laedt' = Anfrage laeuft, null = nicht erreichbar
  vorlagen: VorlageInfo[] | null | 'laedt';
  ungespeichert: boolean;
  nurLesen: boolean;
  onAnwenden: (name: string) => void;
  onAlsNeu: (name: string) => void;
  onNeuLaden: () => void;
};

export function VorlagenListe({ start, vorlagen, ungespeichert, nurLesen, onAnwenden, onAlsNeu, onNeuLaden }: ListeProps) {
  if (!start.vorlagen_url || !start.vorlage_bild_url || !start.vorlage_url) {
    return (
      <Typography variant="body2" color="text.secondary">
        Vorlagen sind hier noch nicht eingerichtet.
      </Typography>
    );
  }
  if (vorlagen === 'laedt') {
    return (
      <Typography variant="body2" color="text.secondary">
        Vorlagen werden geladen …
      </Typography>
    );
  }
  if (vorlagen === null) {
    return (
      <Stack spacing={1} alignItems="flex-start">
        <Typography variant="body2" color="text.secondary">
          Vorlagen gerade nicht erreichbar.
        </Typography>
        <Button size="small" onClick={onNeuLaden}>
          Erneut versuchen
        </Button>
      </Stack>
    );
  }
  if (vorlagen.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        Keine freigegebenen Vorlagen für die Firma dieses Newsletters.
      </Typography>
    );
  }
  const sperre = anwendenSperre(ungespeichert, nurLesen);
  const bildUrl = start.vorlage_bild_url;
  return (
    <Stack spacing={1.5}>
      {vorlagen.map((v) => (
        <Card key={v.name} variant="outlined">
          <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
            <Vorschau src={bildUrl + encodeURIComponent(v.name)} name={v.name} />
            <Typography variant="subtitle2" sx={{ mt: 1, textTransform: 'capitalize' }}>
              {v.name}
            </Typography>
            {v.beschreibung && (
              <Typography variant="caption" color="text.secondary" component="p">
                {v.beschreibung}
              </Typography>
            )}
            <Stack spacing={0.5} sx={{ mt: 1 }} alignItems="flex-start">
              <Button size="small" variant="outlined" disabled={nurLesen} onClick={() => onAlsNeu(v.name)}>
                Als neuer Entwurf
              </Button>
              <Tooltip title={sperre ?? ''}>
                <span>
                  <Button
                    size="small"
                    disabled={sperre !== null}
                    onClick={() => onAnwenden(v.name)}
                    sx={{ px: 0.5, whiteSpace: 'nowrap', letterSpacing: 0 }}
                  >
                    Auf diesen Entwurf anwenden …
                  </Button>
                </span>
              </Tooltip>
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

// Inhalt des Bestaetigungsdialogs (getrennt, damit er sich ohne Portal pruefen laesst).
export function AnwendenFrage({ name, basis, grund }: { name: string; basis: number; grund: string | null }) {
  return (
    <>
      <DialogContentText>
        Die Vorlage „{name}“ wird auf diesen Entwurf angewendet. {anwendenText(basis)}
      </DialogContentText>
      {grund && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {grund}
        </Alert>
      )}
    </>
  );
}

export default function VorlagenReiter() {
  const start = pultStore((p) => p.start);
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const nurLesen = pultStore((p) => p.nurLesen);
  const basis = pultStore((p) => p.basis);
  const [vorlagen, setVorlagen] = useState<VorlageInfo[] | null | 'laedt'>('laedt');
  const [anwenden, setAnwenden] = useState<{ name: string; grund: string | null; laeuft: boolean } | null>(null);
  const [neu, setNeu] = useState<{ name: string; titel: string; grund: string | null; laeuft: boolean } | null>(null);

  const laden = useCallback(() => {
    if (!start) return;
    setVorlagen('laedt');
    void vorlagenListe(start).then(setVorlagen);
  }, [start]);

  useEffect(() => {
    if (start?.vorlagen_url) laden();
  }, [start?.vorlagen_url, laden]);

  if (!start) return null;

  const anwendenBestaetigt = async () => {
    if (!anwenden) return;
    setAnwenden({ ...anwenden, grund: null, laeuft: true });
    // Basis zum Zeitpunkt des Klicks: ist inzwischen eine Agent-Fassung neuer, lehnt der Server ab.
    const grund = await anwendenAusfuehren(start, anwenden.name, pultStore.getState().basis);
    if (grund !== null) setAnwenden({ ...anwenden, grund, laeuft: false });
  };

  const neuAnlegen = async () => {
    if (!neu) return;
    setNeu({ ...neu, grund: null, laeuft: true });
    const grund = await alsNeuAusfuehren(start, neu.name, neu.titel);
    if (grund !== null) setNeu({ ...neu, grund, laeuft: false });
  };

  const titelHinweis = neu ? titelFehler(neu.titel) : null;

  return (
    <>
      <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 1.5 }}>
        Freigegebene Vorlagen der Firma dieses Newsletters.
      </Typography>
      <VorlagenListe
        start={start}
        vorlagen={vorlagen}
        ungespeichert={ungespeichert}
        nurLesen={nurLesen}
        onAnwenden={(name) => setAnwenden({ name, grund: null, laeuft: false })}
        onAlsNeu={(name) => setNeu({ name, titel: '', grund: null, laeuft: false })}
        onNeuLaden={laden}
      />

      <Dialog open={anwenden !== null} onClose={() => !anwenden?.laeuft && setAnwenden(null)}>
        <DialogTitle>Vorlage anwenden?</DialogTitle>
        <DialogContent>{anwenden && <AnwendenFrage name={anwenden.name} basis={basis} grund={anwenden.grund} />}</DialogContent>
        <DialogActions>
          <Button disabled={anwenden?.laeuft} onClick={() => setAnwenden(null)}>
            Abbrechen
          </Button>
          <Button
            variant="contained"
            disabled={anwenden?.laeuft || anwendenSperre(ungespeichert, nurLesen) !== null}
            onClick={() => void anwendenBestaetigt()}
          >
            {anwenden?.laeuft ? 'Wird angewendet …' : 'Anwenden'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={neu !== null} onClose={() => !neu?.laeuft && setNeu(null)} fullWidth maxWidth="xs">
        <DialogTitle>Neuer Entwurf aus „{neu?.name}“</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Der neue Entwurf gehört derselben Firma und öffnet sich danach im Editor. Dieser Entwurf bleibt, wie er ist.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            size="small"
            label="Titel des neuen Entwurfs"
            value={neu?.titel ?? ''}
            error={neu !== null && neu.titel !== '' && titelHinweis !== null}
            helperText={neu && neu.titel !== '' && titelHinweis ? titelHinweis : `1 bis ${TITEL_MAX} Zeichen`}
            onChange={(ev) => neu && setNeu({ ...neu, titel: ev.target.value })}
            onKeyDown={(ev) => {
              if (ev.key === 'Enter' && titelHinweis === null && !neu?.laeuft) void neuAnlegen();
            }}
          />
          {neu?.grund && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {neu.grund}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button disabled={neu?.laeuft} onClick={() => setNeu(null)}>
            Abbrechen
          </Button>
          <Button variant="contained" disabled={neu?.laeuft || titelHinweis !== null} onClick={() => void neuAnlegen()}>
            {neu?.laeuft ? 'Wird angelegt …' : 'Anlegen und öffnen'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
