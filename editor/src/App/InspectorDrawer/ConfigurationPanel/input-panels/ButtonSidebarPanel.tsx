import React, { useState } from 'react';
import { ZodError } from 'zod';

import { ToggleButton } from '@mui/material';
import { ButtonProps, ButtonPropsDefaults, ButtonPropsSchema } from '@usewaypoint/block-button';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import ColorInput from './helpers/inputs/ColorInput';
import RadioGroupInput from './helpers/inputs/RadioGroupInput';
import TextInput from './helpers/inputs/TextInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type ButtonSidebarPanelProps = {
  data: ButtonProps;
  setData: (v: ButtonProps) => void;
};
export default function ButtonSidebarPanel({ data, setData }: ButtonSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);

  const updateData = (d: unknown) => {
    const res = ButtonPropsSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  const text = data.props?.text ?? ButtonPropsDefaults.text;
  const url = data.props?.url ?? ButtonPropsDefaults.url;
  const fullWidth = data.props?.fullWidth ?? ButtonPropsDefaults.fullWidth;
  const size = data.props?.size ?? ButtonPropsDefaults.size;
  const buttonStyle = data.props?.buttonStyle ?? ButtonPropsDefaults.buttonStyle;
  const buttonTextColor = data.props?.buttonTextColor ?? ButtonPropsDefaults.buttonTextColor;
  const buttonBackgroundColor = data.props?.buttonBackgroundColor ?? ButtonPropsDefaults.buttonBackgroundColor;

  return (
    <BaseSidebarPanel title="Knopf">
      <TextInput
        label="Beschriftung"
        defaultValue={text}
        onChange={(text) => updateData({ ...data, props: { ...data.props, text } })}
      />
      <TextInput
        label="Link"
        placeholder="https://…"
        required
        error={url.trim() === ''}
        helperText={url.trim() === '' ? 'Ohne Link wird der Knopf nicht gespeichert – bitte https://… eintragen' : 'Nur Adressen mit https://'}
        defaultValue={url}
        onChange={(url) => updateData({ ...data, props: { ...data.props, url } })}
      />
      <RadioGroupInput
        label="Breite"
        defaultValue={fullWidth ? 'FULL_WIDTH' : 'AUTO'}
        onChange={(v) => updateData({ ...data, props: { ...data.props, fullWidth: v === 'FULL_WIDTH' } })}
      >
        <ToggleButton value="FULL_WIDTH">Ganze Breite</ToggleButton>
        <ToggleButton value="AUTO">Automatisch</ToggleButton>
      </RadioGroupInput>
      <RadioGroupInput
        label="Größe"
        defaultValue={size}
        onChange={(size) => updateData({ ...data, props: { ...data.props, size } })}
      >
        <ToggleButton value="x-small">XS</ToggleButton>
        <ToggleButton value="small">S</ToggleButton>
        <ToggleButton value="medium">M</ToggleButton>
        <ToggleButton value="large">L</ToggleButton>
      </RadioGroupInput>
      <RadioGroupInput
        label="Form"
        defaultValue={buttonStyle}
        onChange={(buttonStyle) => updateData({ ...data, props: { ...data.props, buttonStyle } })}
      >
        <ToggleButton value="rectangle">Eckig</ToggleButton>
        <ToggleButton value="rounded">Abgerundet</ToggleButton>
        <ToggleButton value="pill">Pille</ToggleButton>
      </RadioGroupInput>
      <ColorInput
        label="Schriftfarbe"
        defaultValue={buttonTextColor}
        onChange={(buttonTextColor) => updateData({ ...data, props: { ...data.props, buttonTextColor } })}
      />
      <ColorInput
        label="Knopffarbe"
        defaultValue={buttonBackgroundColor}
        onChange={(buttonBackgroundColor) => updateData({ ...data, props: { ...data.props, buttonBackgroundColor } })}
      />
      <MultiStylePropertyPanel
        names={['backgroundColor', 'fontFamily', 'fontSize', 'fontWeight', 'textAlign', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}
