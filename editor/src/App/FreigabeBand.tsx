import React, { useState } from 'react';

import { Alert, Box, Button, Typography } from '@mui/material';

import { datumKurz, Rueckmeldung, zurueckziehen } from '../pult';
import { pultStore } from '../pultZustand';

// Band: der Newsletter liegt zur Freigabe, der Editor ist nur lesend. Zurueckziehen laedt die Seite neu.
export function LiegtBand() {
  const start = pultStore((p) => p.start);
  const nurLesen = pultStore((p) => p.nurLesen);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  if (!start || !nurLesen) return null;

  const zurueck = async () => {
    setLaeuft(true);
    setFehler(null);
    const r = await zurueckziehen(start);
    if (r.ok) {
      window.location.reload();
      return;
    }
    setLaeuft(false);
    setFehler(r.grund);
  };

  return (
    <Alert
      severity="info"
      data-testid="liegt-zur-freigabe"
      sx={{ borderRadius: 0 }}
      action={
        <Button color="inherit" size="small" disabled={laeuft} onClick={() => void zurueck()}>
          {laeuft ? 'Zieht zurück …' : 'Zurückziehen'}
        </Button>
      }
    >
      Liegt zur Freigabe{start.eingereicht_am ? ` seit ${datumKurz(start.eingereicht_am)}` : ''} – nur lesend.
      {fehler !== null && (
        <Box role="status" component="span" sx={{ display: 'block', color: 'error.main' }}>
          {fehler}
        </Box>
      )}
    </Alert>
  );
}

function Kopf({ r }: { r: Rueckmeldung }) {
  return `Rückmeldung von ${r.von || 'der Freigabe'}, ${datumKurz(r.am)} (Fassung ${r.fassung})`;
}

// Band oben, solange offene Rueckmeldungen da sind: die neueste ausgeklappt, aeltere einklappbar.
export function RueckmeldungBand() {
  const liste = pultStore((p) => p.start?.rueckmeldungen ?? []);
  if (liste.length === 0) return null;
  const [neueste, ...aeltere] = liste;
  return (
    <Alert severity="warning" data-testid="rueckmeldung" sx={{ borderRadius: 0 }}>
      <Typography variant="caption" component="div" sx={{ fontWeight: 700 }}>
        <Kopf r={neueste} />
      </Typography>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
        {neueste.text}
      </Typography>
      {aeltere.map((r, i) => (
        <details key={`${r.am}-${i}`} style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12 }}>
            <Kopf r={r} />
          </summary>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 0.5 }}>
            {r.text}
          </Typography>
        </details>
      ))}
    </Alert>
  );
}
