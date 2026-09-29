import React from 'react';

import { RoundedCornerOutlined } from '@mui/icons-material';

import { TStyle } from '../../../../../../documents/blocks/helpers/TStyle';
import { NullableColorInput } from '../inputs/ColorInput';
import { NullableFontFamily } from '../inputs/FontFamily';
import FontSizeInput from '../inputs/FontSizeInput';
import FontWeightInput from '../inputs/FontWeightInput';
import PaddingInput from '../inputs/PaddingInput';
import SliderInput from '../inputs/SliderInput';
import TextAlignInput from '../inputs/TextAlignInput';

type StylePropertyPanelProps = {
  name: keyof TStyle;
  value: TStyle;
  onChange: (style: TStyle) => void;
};
export default function SingleStylePropertyPanel({ name, value, onChange }: StylePropertyPanelProps) {
  const defaultValue = value[name] ?? null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleChange = (v: any) => {
    onChange({ ...value, [name]: v });
  };

  switch (name) {
    case 'backgroundColor':
      return <NullableColorInput label="Hintergrundfarbe" defaultValue={defaultValue} onChange={handleChange} />;
    case 'borderColor':
      return <NullableColorInput label="Rahmenfarbe" defaultValue={defaultValue} onChange={handleChange} />;
    case 'borderRadius':
      return (
        <SliderInput
          iconLabel={<RoundedCornerOutlined />}
          units="px"
          step={4}
          marks
          min={0}
          max={48}
          label="Eckenradius"
          defaultValue={defaultValue}
          onChange={handleChange}
        />
      );
    case 'color':
      return <NullableColorInput label="Schriftfarbe" defaultValue={defaultValue} onChange={handleChange} />;
    case 'fontFamily':
      return <NullableFontFamily label="Schriftart" defaultValue={defaultValue} onChange={handleChange} />;
    case 'fontSize':
      return <FontSizeInput label="Schriftgröße" defaultValue={defaultValue} onChange={handleChange} />;
    case 'fontWeight':
      return <FontWeightInput label="Schriftstärke" defaultValue={defaultValue} onChange={handleChange} />;
    case 'textAlign':
      return <TextAlignInput label="Ausrichtung" defaultValue={defaultValue} onChange={handleChange} />;
    case 'padding':
      return <PaddingInput label="Innenabstand" defaultValue={defaultValue} onChange={handleChange} />;
  }
}
