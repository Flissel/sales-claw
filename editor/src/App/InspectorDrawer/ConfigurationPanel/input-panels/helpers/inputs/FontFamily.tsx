import React, { useState } from 'react';

import { MenuItem, TextField } from '@mui/material';

import { FONT_FAMILIES } from '../../../../../../documents/blocks/helpers/fontFamily';

const OPTIONS = FONT_FAMILIES.map((option) => (
  <MenuItem key={option.key} value={option.key} sx={{ fontFamily: option.value }}>
    {option.label}
  </MenuItem>
));

// Rollen der Vorlage (Spec 2026-10-01 §4): die Familie kommt aus root.data.schriften.
const VORLAGE = [
  <MenuItem key="ANZEIGE" value="ANZEIGE">
    Vorlage – Anzeige
  </MenuItem>,
  <MenuItem key="TEXT" value="TEXT">
    Vorlage – Text
  </MenuItem>,
];

type NullableProps = {
  label: string;
  onChange: (value: null | string) => void;
  defaultValue: null | string;
  // Nur Bloecke (Ueberschrift, Text, Knopf) kennen ANZEIGE/TEXT, nicht die ganze Mail.
  mitVorlage?: boolean;
};
export function NullableFontFamily({ label, onChange, defaultValue, mitVorlage = false }: NullableProps) {
  const [value, setValue] = useState(defaultValue ?? 'inherit');
  return (
    <TextField
      select
      variant="standard"
      label={label}
      value={value}
      onChange={(ev) => {
        const v = ev.target.value;
        setValue(v);
        onChange(v === 'inherit' ? null : v);
      }}
    >
      <MenuItem value="inherit">Wie ganze Mail</MenuItem>
      {mitVorlage && VORLAGE}
      {OPTIONS}
    </TextField>
  );
}
