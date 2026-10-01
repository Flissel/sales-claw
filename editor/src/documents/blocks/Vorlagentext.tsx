// Darstellung der neuen Gestaltungsfelder im Editor-Canvas (Spec 2026-10-01 §4):
// Vorlagenschriften (ANZEIGE/TEXT ueber root.data.schriften), Laufweite, Versalien,
// Zeilenhoehe, *kursiv* in Ueberschriften und Schwarz-Weiss-Bilder.
// Die Paket-Bloecke bekommen fontFamily: null, damit sie die Schrift vom Wrapper erben
// (sie kennen ANZEIGE/TEXT nicht und wuerden sonst ueberschreiben).
import React from 'react';

import { Button } from '@usewaypoint/block-button';
import { HeadingPropsDefaults } from '@usewaypoint/block-heading';
import { Image } from '@usewaypoint/block-image';
import { Text } from '@usewaypoint/block-text';

import { ButtonDaten, HeadingDaten, ImageDaten, kursivTeile, schriftFamilie, Schriftpaar, TextDaten } from '../../schemata';
import { useDocument } from '../editor/EditorContext';

type Fein = {
  fontFamily?: string | null;
  letterSpacing?: number | null;
  textTransform?: 'none' | 'uppercase' | null;
  lineHeight?: number | null;
};

function useSchriftpaar(): Schriftpaar {
  const root = useDocument().root;
  return root?.type === 'EmailLayout' ? root.data.schriften : null;
}

function feinStil(style: Fein | null | undefined, paar: Schriftpaar): React.CSSProperties {
  const ls = style?.letterSpacing;
  return {
    fontFamily: schriftFamilie(style?.fontFamily, paar),
    letterSpacing: typeof ls === 'number' ? `${ls}px` : undefined,
    textTransform: style?.textTransform ?? undefined,
    lineHeight: style?.lineHeight ?? undefined,
  };
}

type Polster = { top: number; bottom: number; right: number; left: number } | null | undefined;
function polster(p: Polster): string | undefined {
  return p ? `${p.top}px ${p.right}px ${p.bottom}px ${p.left}px` : undefined;
}

const GROESSE = { h1: 32, h2: 24, h3: 20 } as const;

// Eigene Ueberschrift statt Paket-Heading: das Paket zeigt *kursiv* als Sternchen.
export function VorlagenHeading({ style, props }: HeadingDaten) {
  const paar = useSchriftpaar();
  const level = props?.level ?? HeadingPropsDefaults.level;
  const text = props?.text ?? HeadingPropsDefaults.text;
  const hStyle: React.CSSProperties = {
    color: style?.color ?? undefined,
    backgroundColor: style?.backgroundColor ?? undefined,
    fontWeight: style?.fontWeight ?? 'bold',
    textAlign: style?.textAlign ?? undefined,
    margin: 0,
    fontSize: style?.fontSize ?? GROESSE[level],
    padding: polster(style?.padding),
    ...feinStil(style, paar),
  };
  const inhalt = kursivTeile(text).map((t, i) =>
    t.kursiv ? <em key={i}>{t.text}</em> : <React.Fragment key={i}>{t.text}</React.Fragment>
  );
  const Tag = level;
  return <Tag style={hStyle}>{inhalt}</Tag>;
}

export function VorlagenText({ style, props }: TextDaten) {
  const paar = useSchriftpaar();
  return (
    <div style={feinStil(style, paar)}>
      <Text style={style ? { ...style, fontFamily: null } : style} props={props} />
    </div>
  );
}

export function VorlagenButton({ style, props }: ButtonDaten) {
  const paar = useSchriftpaar();
  return (
    <div style={{ fontFamily: schriftFamilie(style?.fontFamily, paar) }}>
      <Button style={style ? { ...style, fontFamily: null } : style} props={props} />
    </div>
  );
}

// Schwarz-Weiss nur fuer das Bild selbst (nicht die Hintergrundfarbe des Blocks), s. editor.css.
export function VorlagenImage({ style, props }: ImageDaten) {
  const sw = props?.sw === true;
  return (
    <div className={sw ? 'vorlage-sw' : undefined}>
      <Image style={style} props={props} />
    </div>
  );
}
