import React, { useState } from 'react';

import { Box, Button, Stack, Tab, Tabs, Typography } from '@mui/material';

import { vorschauAdresse } from '../../handy';
import type { Start } from '../../pult';
import { pultStore } from '../../pultZustand';
import NewsletterChat, { Export } from '../NewsletterChat';

export type HandyReiter = 'vorschau' | 'assistent';

// Kopfzeile (56 px) + Reiter (48 px) + Rand: der Rest gehoert Vorschau bzw. Chat.
export const INHALT_HOEHE = 'calc(100vh - 112px)';

const nichts: Export = () => undefined;

type AnsichtProps = {
  start: Pick<Start, 'vorschau_url' | 'zurueck_url'> | null;
  basis: number;
  betreff: string;
  reiter?: HandyReiter;
  exportOeffnen?: Export;
  // Eigener Assistent im Reiter (Collage: der Seiten-Chat); ohne = der Newsletter-Chat.
  assistent?: React.ReactNode;
  // Collage: live die Seite (format=seite) statt der Mail, dazu ein Link auf die Mail-Vorschau (format=handy).
  collage?: boolean;
};

// Die reine Ansicht (Props statt Store - beim Server-Rendern im Test liest zustand nur den Anfangszustand).
export function HandyAnsicht({ start, basis, betreff, reiter: anfang = 'vorschau', exportOeffnen = nichts, assistent, collage = false }: AnsichtProps) {
  const [reiter, setReiter] = useState<HandyReiter>(anfang);
  return (
    <Stack sx={{ height: '100vh', overflow: 'hidden' }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ minHeight: 56, px: 1.5, borderBottom: 1, borderColor: 'divider' }}>
        <Button href={start?.zurueck_url ?? '#'} sx={{ minHeight: 44, flex: 'none' }}>
          Zurück
        </Button>
        <Typography variant="subtitle1" noWrap sx={{ fontWeight: 600, minWidth: 0, flex: 1 }}>
          {betreff || 'Newsletter'}
        </Typography>
        {collage && start ? (
          <Button
            href={vorschauAdresse(start.vorschau_url, basis, 'handy')}
            target="_blank"
            rel="noopener noreferrer"
            sx={{ minHeight: 44, flex: 'none' }}
          >
            Mail-Vorschau
          </Button>
        ) : null}
      </Stack>
      <Tabs value={reiter} onChange={(_, v: HandyReiter) => setReiter(v)} variant="fullWidth" sx={{ minHeight: 48, borderBottom: 1, borderColor: 'divider' }}>
        <Tab value="vorschau" label="Vorschau" sx={{ minHeight: 48 }} />
        <Tab value="assistent" label="Assistent" sx={{ minHeight: 48 }} />
      </Tabs>
      <Box sx={{ flex: 1, minHeight: 0 }}>
        {reiter === 'vorschau' ? (
          start ? (
            // key = Basisfassung: kommt eine neue Fassung (Agent), laedt die Vorschau neu.
            <iframe
              key={basis}
              sandbox=""
              title="Vorschau Handy"
              src={vorschauAdresse(start.vorschau_url, basis, collage ? 'seite' : 'handy')}
              style={{ width: '100%', height: INHALT_HOEHE, border: 0, display: 'block' }}
            />
          ) : null
        ) : (
          assistent ?? <NewsletterChat exportOeffnen={exportOeffnen} hoehe={INHALT_HOEHE} />
        )}
      </Box>
    </Stack>
  );
}

// Editor am Handy (E15): Vorschau der gespeicherten Fassung und der Assistent, kein Bearbeiten.
// `reiter` nur fuer Tests (Vorgabe "vorschau").
export default function HandyApp({ reiter, exportOeffnen }: { reiter?: HandyReiter; exportOeffnen?: Export }) {
  const start = pultStore((p) => p.start);
  const basis = pultStore((p) => p.basis);
  const betreff = pultStore((p) => p.betreff);
  return <HandyAnsicht start={start} basis={basis} betreff={betreff} reiter={reiter} exportOeffnen={exportOeffnen} />;
}
