import React, { useState } from 'react';
import { ZodError } from 'zod';

import { ToggleButton } from '@mui/material';
import { HeadingPropsDefaults } from '@usewaypoint/block-heading';

import { HeadingDaten, HeadingSchema } from '../../../../schemata';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import BooleanInput from './helpers/inputs/BooleanInput';
import RadioGroupInput from './helpers/inputs/RadioGroupInput';
import TextInput from './helpers/inputs/TextInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type HeadingSidebarPanelProps = {
  data: HeadingDaten;
  setData: (v: HeadingDaten) => void;
};
export default function HeadingSidebarPanel({ data, setData }: HeadingSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);

  const updateData = (d: unknown) => {
    const res = HeadingSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  return (
    <BaseSidebarPanel title="Überschrift">
      <TextInput
        label="Inhalt"
        rows={3}
        helperText="*kursiv* ist erlaubt."
        defaultValue={data.props?.text ?? HeadingPropsDefaults.text}
        onChange={(text) => {
          updateData({ ...data, props: { ...data.props, text } });
        }}
      />
      <RadioGroupInput
        label="Ebene"
        defaultValue={data.props?.level ?? HeadingPropsDefaults.level}
        onChange={(level) => {
          updateData({ ...data, props: { ...data.props, level } });
        }}
      >
        <ToggleButton value="h1">H1</ToggleButton>
        <ToggleButton value="h2">H2</ToggleButton>
        <ToggleButton value="h3">H3</ToggleButton>
      </RadioGroupInput>
      <BooleanInput
        label="Versalien gesperrt"
        defaultValue={data.style?.textTransform === 'uppercase'}
        onChange={(an) =>
          updateData({
            ...data,
            style: { ...data.style, textTransform: an ? 'uppercase' : null, letterSpacing: an ? 2 : data.style?.letterSpacing === 2 ? null : data.style?.letterSpacing },
          })
        }
      />
      <MultiStylePropertyPanel
        names={['color', 'backgroundColor', 'fontFamily', 'fontWeight', 'textAlign', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}
