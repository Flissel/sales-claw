import React, { useEffect, useState } from 'react';
import type { ZodError } from 'zod';

import { HeightOutlined, OpacityOutlined } from '@mui/icons-material';
import { Box, Button, InputLabel, Stack, Typography } from '@mui/material';

import ContainerPropsSchema, { ContainerProps } from '../../../../documents/blocks/Container/ContainerPropsSchema';
import { ANZEIGE, medienName } from '../../../../pult';
import { medienLaden, pultStore } from '../../../../pultZustand';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import { NullableColorInput } from './helpers/inputs/ColorInput';
import RawSliderInput from './helpers/inputs/raw/RawSliderInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type ContainerSidebarPanelProps = {
  data: ContainerProps;
  setData: (v: ContainerProps) => void;
};

// Hoehe des Hintergrundbilds (Spec §4: 600 × 120–600).
const HOEHE_MIN = 120;
const HOEHE_MAX = 600;
const HOEHE_START = 300;
const DECKKRAFT_START = 60;

export default function ContainerSidebarPanel({ data, setData }: ContainerSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);
  const medien = pultStore((p) => p.medien);
  useEffect(() => {
    medienLaden();
  }, []);

  const updateData = (d: unknown) => {
    const res = ContainerPropsSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  const aktuell = data.props?.url ?? '';
  const gewaehlt = medienName(aktuell) ?? '';
  // Platzhalter-Bilder sind keine Auswahl (wie im Bild-Panel).
  const kacheln = (medien ?? []).filter((n) => !n.startsWith('platzhalter-'));
  const overlay = data.style?.overlay ?? null;
  const [deckkraft, setDeckkraft] = useState(overlay?.deckkraft ?? DECKKRAFT_START);

  const bildWaehlen = (src: string) =>
    updateData({
      ...data,
      props: { ...data.props, url: src, width: 600, height: data.props?.height ?? HOEHE_START },
    });

  return (
    <BaseSidebarPanel title="Rahmen">
      <Stack spacing={1}>
        <Typography variant="subtitle2">Hintergrundbild aus Medien</Typography>
        {kacheln.length > 0 && (
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1 }}>
            {kacheln.map((n) => {
              const src = ANZEIGE + encodeURIComponent(n);
              const an = n === gewaehlt;
              return (
                <Box
                  key={n}
                  component="img"
                  src={src}
                  alt={n}
                  title={n}
                  loading="lazy"
                  onClick={() => bildWaehlen(src)}
                  sx={{
                    width: '100%',
                    aspectRatio: '1 / 1',
                    objectFit: 'cover',
                    borderRadius: 1,
                    cursor: 'pointer',
                    outline: an ? '2px solid' : 'none',
                    outlineColor: 'primary.main',
                    display: 'block',
                  }}
                />
              );
            })}
          </Box>
        )}
        <Typography variant="caption" color="text.secondary">
          {medien === null
            ? 'Medien werden geladen …'
            : kacheln.length === 0
              ? 'Keine Bilder in den Medien. Bilder im Pult unter Medien hochladen.'
              : 'Das Bild füllt den Abschnitt (Breite 600 px).'}
        </Typography>
        {aktuell !== '' && (
          <>
            <InputLabel shrink>Höhe</InputLabel>
            <RawSliderInput
              iconLabel={<HeightOutlined sx={{ color: 'text.secondary' }} />}
              units="px"
              step={10}
              min={HOEHE_MIN}
              max={HOEHE_MAX}
              value={Math.min(HOEHE_MAX, Math.max(HOEHE_MIN, data.props?.height ?? HOEHE_START))}
              setValue={(height) => updateData({ ...data, props: { ...data.props, height } })}
            />
            <Button
              size="small"
              sx={{ alignSelf: 'flex-start' }}
              onClick={() =>
                updateData({ ...data, props: { ...data.props, url: null, width: null, height: null } })
              }
            >
              Kein Hintergrundbild
            </Button>
          </>
        )}

        <Typography variant="subtitle2">Farbfeld</Typography>
        <NullableColorInput
          label="Farbe"
          defaultValue={overlay?.farbe ?? null}
          onChange={(farbe) =>
            updateData({
              ...data,
              style: { ...data.style, overlay: farbe ? { farbe, deckkraft } : null },
            })
          }
        />
        <Stack spacing={1} alignItems="flex-start">
          <InputLabel shrink>Deckkraft</InputLabel>
          <RawSliderInput
            iconLabel={<OpacityOutlined sx={{ color: 'text.secondary' }} />}
            units="%"
            step={5}
            min={0}
            max={100}
            value={deckkraft}
            setValue={(v) => {
              setDeckkraft(v);
              if (overlay) updateData({ ...data, style: { ...data.style, overlay: { ...overlay, deckkraft: v } } });
            }}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          Halbtransparent über dem Hintergrundbild; Outlook zeigt die volle Farbe.
        </Typography>
      </Stack>

      <MultiStylePropertyPanel
        names={['backgroundColor', 'borderColor', 'borderRadius', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}
