import React, { useEffect, useState } from 'react';
import { ZodError } from 'zod';

import {
  VerticalAlignBottomOutlined,
  VerticalAlignCenterOutlined,
  VerticalAlignTopOutlined,
} from '@mui/icons-material';
import { Button, MenuItem, Stack, TextField, ToggleButton, Typography } from '@mui/material';
import { ImageProps, ImagePropsSchema } from '@usewaypoint/block-image';

import { ANZEIGE } from '../../../../pult';
import { medienLaden, pultStore } from '../../../../pultZustand';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import RadioGroupInput from './helpers/inputs/RadioGroupInput';
import TextDimensionInput from './helpers/inputs/TextDimensionInput';
import TextInput from './helpers/inputs/TextInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type ImageSidebarPanelProps = {
  data: ImageProps;
  setData: (v: ImageProps) => void;
};
export default function ImageSidebarPanel({ data, setData }: ImageSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);
  const medien = pultStore((p) => p.medien);
  useEffect(() => {
    medienLaden();
  }, []);

  // Das freie URL-Feld gibt es hier nicht: Bilder kommen nur aus den Medien.
  const aktuell = data.props?.url ?? '';
  const gewaehlt = aktuell.startsWith(ANZEIGE) ? decodeURIComponent(aktuell.slice(ANZEIGE.length)) : '';
  const optionen = medien ?? [];
  const fehltInListe = gewaehlt !== '' && !optionen.includes(gewaehlt);

  const updateData = (d: unknown) => {
    const res = ImagePropsSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  return (
    <BaseSidebarPanel title="Bild">
      <Stack spacing={1}>
        <TextField
          select
          fullWidth
          variant="standard"
          label="Aus den Medien"
          value={gewaehlt}
          onChange={(ev) => {
            const name = ev.target.value;
            const url = name ? ANZEIGE + encodeURIComponent(name) : null;
            updateData({ ...data, props: { ...data.props, url } });
          }}
          helperText={
            medien === null
              ? 'Medien werden geladen …'
              : optionen.length === 0
                ? 'Keine Bilder in den Medien. Bilder im Pult unter Medien hochladen.'
                : 'Erlaubt: png, jpg, gif, webp aus den Medien'
          }
        >
          <MenuItem value="">
            <em>Kein Bild</em>
          </MenuItem>
          {fehltInListe && <MenuItem value={gewaehlt}>{gewaehlt} (nicht mehr in den Medien)</MenuItem>}
          {optionen.map((name) => (
            <MenuItem key={name} value={name}>
              {name}
            </MenuItem>
          ))}
        </TextField>
        {aktuell !== '' && !aktuell.startsWith(ANZEIGE) && (
          <Typography variant="body2" color="error">
            Dieses Bild stammt nicht aus den Medien und wird beim Speichern abgelehnt. Bitte ein Bild aus den
            Medien wählen.
          </Typography>
        )}
        <Button size="small" sx={{ alignSelf: 'flex-start' }} onClick={() => medienLaden(true)}>
          Medienliste neu laden
        </Button>
      </Stack>

      <TextInput
        label="Alternativtext"
        defaultValue={data.props?.alt ?? ''}
        onChange={(alt) => updateData({ ...data, props: { ...data.props, alt } })}
      />
      <TextInput
        label="Link beim Anklicken"
        placeholder="https://…"
        helperText="Optional, nur Adressen mit https://"
        defaultValue={data.props?.linkHref ?? ''}
        onChange={(v) => {
          const linkHref = v.trim().length === 0 ? null : v.trim();
          updateData({ ...data, props: { ...data.props, linkHref } });
        }}
      />
      <Stack direction="row" spacing={2}>
        <TextDimensionInput
          label="Breite"
          defaultValue={data.props?.width}
          onChange={(width) => updateData({ ...data, props: { ...data.props, width } })}
        />
        <TextDimensionInput
          label="Höhe"
          defaultValue={data.props?.height}
          onChange={(height) => updateData({ ...data, props: { ...data.props, height } })}
        />
      </Stack>

      <RadioGroupInput
        label="Ausrichtung"
        defaultValue={data.props?.contentAlignment ?? 'middle'}
        onChange={(contentAlignment) => updateData({ ...data, props: { ...data.props, contentAlignment } })}
      >
        <ToggleButton value="top">
          <VerticalAlignTopOutlined fontSize="small" />
        </ToggleButton>
        <ToggleButton value="middle">
          <VerticalAlignCenterOutlined fontSize="small" />
        </ToggleButton>
        <ToggleButton value="bottom">
          <VerticalAlignBottomOutlined fontSize="small" />
        </ToggleButton>
      </RadioGroupInput>

      <MultiStylePropertyPanel
        names={['backgroundColor', 'textAlign', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}
