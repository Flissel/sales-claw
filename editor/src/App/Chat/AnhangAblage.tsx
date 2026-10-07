// Anhaenge in den Chat bringen (Spec 2026-10-06 §2.1): Bueroklammer, Ziehen auf den Chat (Ablageflaeche
// mit dezentem Akzent-Rahmen) und Einfuegen von Bildern aus der Zwischenablage. Jede Datei wird sofort
// ein Chip (KontextChips), der Upload laeuft im Hintergrund.
import React, { useRef, useState } from 'react';

import { AttachFileRounded } from '@mui/icons-material';
import { Box, IconButton, Tooltip } from '@mui/material';

import { DATEI_ANNAHME } from '../../chatKontext';
import { anhangHinzu, pultStore } from '../../pultZustand';
import { FARBE } from '../Gestaltung/gestaltungStil';

import { vorschauErzeugen } from './KontextChips';

const mitDateien = (ev: React.DragEvent) => Array.from(ev.dataTransfer.types).includes('Files');

// onGrund: Grund fuer den Betreiber (z. B. schon 5 Anhaenge) oder null; onAngehaengt: z. B. Chat aufklappen.
export function useAnhangAblage({ onGrund, onAngehaengt }: { onGrund: (grund: string | null) => void; onAngehaengt: () => void }) {
  const dateiWahl = useRef<HTMLInputElement>(null);
  // Zaehlt dragenter/-leave (Kindelemente feuern beides); > 0 = Dateien schweben ueber dem Chat.
  const [ziehen, setZiehen] = useState(0);
  // Liegt zur Freigabe: keine Anhaenge (Bueroklammer, Ziehen, Einfuegen).
  const nurLesen = pultStore((p) => p.nurLesen);

  const anhaengen = (dateien: File[]) => {
    if (nurLesen) return;
    let grund: string | null = null;
    for (const d of dateien) {
      const vorher = new Set(pultStore.getState().chatAnhaenge.map((a) => a.id));
      grund = anhangHinzu(d) ?? grund;
      const neu = pultStore.getState().chatAnhaenge.find((a) => !vorher.has(a.id));
      if (neu && neu.art === 'bild' && neu.status !== 'fehler') void vorschauErzeugen(neu.id, d);
    }
    onGrund(grund);
    onAngehaengt();
  };

  // Auf den Bereich, der Dateien annimmt (braucht position: relative fuer die Ablageflaeche).
  const ablage = {
    onDragEnter: (ev: React.DragEvent) => {
      if (nurLesen || !mitDateien(ev)) return;
      ev.preventDefault();
      setZiehen((n) => n + 1);
    },
    onDragOver: (ev: React.DragEvent) => {
      if (nurLesen || !mitDateien(ev)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'copy';
    },
    onDragLeave: (ev: React.DragEvent) => {
      if (mitDateien(ev)) setZiehen((n) => Math.max(0, n - 1));
    },
    onDrop: (ev: React.DragEvent) => {
      if (nurLesen || !mitDateien(ev)) return;
      ev.preventDefault();
      setZiehen(0);
      anhaengen(Array.from(ev.dataTransfer.files));
    },
  };

  const ablageFlaeche =
    ziehen > 0 ? (
      <Box
        aria-hidden="true"
        sx={{
          position: 'absolute',
          inset: 6,
          zIndex: 2,
          pointerEvents: 'none',
          display: 'grid',
          placeItems: 'center',
          textAlign: 'center',
          borderRadius: '10px',
          border: `1.5px dashed ${FARBE.akzent}`,
          bgcolor: 'rgba(15,15,17,0.86)',
          color: FARBE.text,
          fontSize: 13,
          '@keyframes ablageAuf': { from: { opacity: 0 }, to: { opacity: 1 } },
          animation: 'ablageAuf 120ms ease-out',
        }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.75 }}>
          <AttachFileRounded sx={{ fontSize: 20, color: FARBE.akzent, transform: 'rotate(45deg)' }} />
          Hier ablegen – Bilder oder Dokumente
          <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft }}>
            JPG, PNG, WebP · PDF, DOCX, TXT, MD · je bis 15 MB
          </Box>
        </Box>
      </Box>
    ) : null;

  const bueroklammer = (
    <>
      <Tooltip title="Datei anhängen – Bild oder Dokument (auch Ziehen oder Einfügen)">
        <IconButton aria-label="Datei anhängen" disabled={nurLesen} onClick={() => dateiWahl.current?.click()} sx={{ width: 28, height: 28, mb: '2px', ml: -1, flexShrink: 0 }}>
          <AttachFileRounded sx={{ fontSize: 16, transform: 'rotate(45deg)' }} />
        </IconButton>
      </Tooltip>
      <input
        ref={dateiWahl}
        type="file"
        multiple
        accept={DATEI_ANNAHME}
        hidden
        onChange={(ev) => {
          const dateien = Array.from(ev.target.files ?? []);
          ev.target.value = '';
          anhaengen(dateien);
        }}
      />
    </>
  );

  // Fuer das Eingabefeld: Bilder aus der Zwischenablage (heissen oft nur "image.png" - der Server
  // macht den Namen eindeutig); Text wird normal eingefuegt.
  const beimEinfuegen = (ev: React.ClipboardEvent) => {
    if (nurLesen) return;
    const bilder = Array.from(ev.clipboardData.files).filter((f) => f.type.startsWith('image/'));
    if (bilder.length === 0) return;
    ev.preventDefault();
    anhaengen(bilder);
  };

  return { ablage, ablageFlaeche, bueroklammer, beimEinfuegen };
}
