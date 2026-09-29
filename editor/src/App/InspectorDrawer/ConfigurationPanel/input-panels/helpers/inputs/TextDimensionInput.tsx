import React, { useState } from 'react';

import { TextField, Typography } from '@mui/material';

type TextDimensionInputProps = {
  label: string;
  defaultValue: number | null | undefined;
  onChange: (v: number | null) => void;
  // Grenzen wie in der DB-Pruefung (marketing.pult_bloecke_fehler); ausserhalb wird geklemmt.
  min?: number;
  max?: number;
};
export default function TextDimensionInput({ label, defaultValue, onChange, min, max }: TextDimensionInputProps) {
  const [wert, setWert] = useState(defaultValue == null ? '' : String(defaultValue));
  const handleChange: React.ChangeEventHandler<HTMLInputElement> = (ev) => {
    let value = parseInt(ev.target.value);
    if (!isNaN(value)) {
      if (min !== undefined) value = Math.max(min, value);
      if (max !== undefined) value = Math.min(max, value);
    }
    setWert(isNaN(value) ? ev.target.value : String(value));
    onChange(isNaN(value) ? null : value);
  };
  return (
    <TextField
      fullWidth
      onChange={handleChange}
      value={wert}
      helperText={min !== undefined && max !== undefined ? `${min}–${max}` : undefined}
      label={label}
      variant="standard"
      placeholder="auto"
      size="small"
      InputProps={{
        endAdornment: (
          <Typography variant="body2" color="text.secondary">
            px
          </Typography>
        ),
      }}
    />
  );
}
