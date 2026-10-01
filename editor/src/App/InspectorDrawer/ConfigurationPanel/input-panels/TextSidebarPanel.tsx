import React, { useState } from 'react';
import { ZodError } from 'zod';

import { TextDaten, TextSchema } from '../../../../schemata';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import BooleanInput from './helpers/inputs/BooleanInput';
import TextInput from './helpers/inputs/TextInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type TextSidebarPanelProps = {
  data: TextDaten;
  setData: (v: TextDaten) => void;
};
export default function TextSidebarPanel({ data, setData }: TextSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);

  const updateData = (d: unknown) => {
    const res = TextSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  return (
    <BaseSidebarPanel title="Text">
      <TextInput
        label="Inhalt"
        rows={5}
        helperText="Erlaubt: **fett**, *kursiv*, [Link](https://…). Leerzeile = neuer Absatz, Enter = neue Zeile."
        defaultValue={data.props?.text ?? ''}
        onChange={(text) => updateData({ ...data, props: { ...data.props, text } })}
      />
      <BooleanInput
        label="Formatierung (fett, kursiv, Links) anwenden"
        defaultValue={data.props?.markdown ?? false}
        onChange={(markdown) => updateData({ ...data, props: { ...data.props, markdown } })}
      />
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
        names={['color', 'backgroundColor', 'fontFamily', 'fontSize', 'fontWeight', 'textAlign', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}
