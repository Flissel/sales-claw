// Erweiterte Block-Schemata (Spec 2026-10-01-newsletter-vorlagen-profi §4).
// Die Paket-Schemata von @usewaypoint verwerfen unbekannte Felder beim Bearbeiten
// stillschweigend (zod "strip"); hier kennen sie die neuen Gestaltungsfelder, damit
// ein Vorlagenblock nach dem Bearbeiten unveraendert gespeichert wird.
import { z } from 'zod';

import { ButtonPropsSchema } from '@usewaypoint/block-button';
import { HeadingPropsSchema } from '@usewaypoint/block-heading';
import { ImagePropsSchema } from '@usewaypoint/block-image';
import { TextPropsSchema } from '@usewaypoint/block-text';

import { FONT_FAMILIES } from './documents/blocks/helpers/fontFamily';

// Schrift-Register (constraints.md) - IDs und Familien woertlich.
export const SCHRIFT_IDS = [
  'cormorant',
  'dm-sans',
  'playfair',
  'poppins',
  'young-serif',
  'manrope',
  'bodoni',
  'montserrat',
  'josefin',
  'oxanium',
  'rajdhani',
] as const;
export type SchriftId = (typeof SCHRIFT_IDS)[number];

export const SCHRIFT_FAMILIE: Record<string, string> = {
  cormorant: "'Cormorant Garamond', Georgia, 'Times New Roman', serif",
  'dm-sans': "'DM Sans', Arial, Helvetica, sans-serif",
  playfair: "'Playfair Display', Georgia, 'Times New Roman', serif",
  poppins: 'Poppins, Arial, Helvetica, sans-serif',
  'young-serif': "'Young Serif', Georgia, serif",
  manrope: 'Manrope, Arial, Helvetica, sans-serif',
  bodoni: "'Bodoni Moda', Didot, Georgia, serif",
  montserrat: 'Montserrat, Arial, Helvetica, sans-serif',
  josefin: "'Josefin Sans', 'Trebuchet MS', Arial, sans-serif",
  oxanium: "Oxanium, 'Trebuchet MS', Arial, sans-serif",
  rajdhani: "Rajdhani, 'Arial Narrow', Arial, sans-serif",
};

const ALT = [
  'MODERN_SANS',
  'BOOK_SANS',
  'ORGANIC_SANS',
  'GEOMETRIC_SANS',
  'HEAVY_SANS',
  'ROUNDED_SANS',
  'MODERN_SERIF',
  'BOOK_SERIF',
  'MONOSPACE',
] as const;
// ANZEIGE/TEXT = Rolle; die Familie kommt aus root.data.schriften der Vorlage.
export const FontFamily = z.enum([...ALT, 'ANZEIGE', 'TEXT']).nullable().optional();

const Fein = {
  fontFamily: FontFamily,
  letterSpacing: z.number().min(-2).max(8).nullable().optional(),
  textTransform: z.enum(['none', 'uppercase']).nullable().optional(),
  lineHeight: z.number().min(0.9).max(2).nullable().optional(),
};

type MitStilBasis<S extends z.ZodRawShape, P extends z.ZodTypeAny> = z.ZodObject<{
  style: z.ZodNullable<z.ZodOptional<z.ZodObject<S>>>;
  props: P;
}>;

// Nimmt das Paket-Schema und erweitert nur dessen style-Objekt (gleiche Verschachtelung
// ZodNullable<ZodOptional<ZodObject>> wie im Paket).
export function mitStil<S extends z.ZodRawShape, P extends z.ZodTypeAny, E extends z.ZodRawShape>(
  basis: MitStilBasis<S, P>,
  extra: E
) {
  const stil = basis.shape.style.unwrap().unwrap();
  return z.object({ style: stil.extend(extra).optional().nullable(), props: basis.shape.props });
}

// fontSize: das Paket-Heading kennt keine Schriftgroesse; Vorlagen setzen 8-72 (wie der SQL-Validator).
export const HeadingSchema = mitStil(HeadingPropsSchema, {
  ...Fein,
  fontSize: z.number().min(8).max(72).nullable().optional(),
});
export const TextSchema = mitStil(TextPropsSchema, Fein);
export const ButtonSchema = mitStil(ButtonPropsSchema, { fontFamily: FontFamily });

const bildProps = ImagePropsSchema.shape.props.unwrap().unwrap();
export const ImageSchema = z.object({
  style: ImagePropsSchema.shape.style,
  props: bildProps
    .extend({ sw: z.boolean().nullable().optional(), grafik: z.boolean().nullable().optional() })
    .optional()
    .nullable(),
});

// Schriftpaar der Vorlage, wie es in root.data.schriften steht (beide Teile optional).
export type Schriftpaar = { anzeige?: string | null; text?: string | null } | null | undefined;

// CSS-Familie fuer style.fontFamily: ANZEIGE/TEXT ueber das Schriftpaar der Vorlage,
// sonst die 9 Altschluessel; undefined = erben (wie der Renderer: kein font-family).
export function schriftFamilie(ff: string | null | undefined, paar: Schriftpaar): string | undefined {
  if (ff === 'ANZEIGE' || ff === 'TEXT') {
    const id = ff === 'ANZEIGE' ? paar?.anzeige : paar?.text;
    return id ? SCHRIFT_FAMILIE[id] : undefined;
  }
  return FONT_FAMILIES.find((f) => f.key === ff)?.value;
}

// Ueberschrift: nur *kursiv* (gleiches Muster wie _KURSIV im Renderer bloecke_mjml.py).
const KURSIV = /(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g;
export function kursivTeile(text: string): { text: string; kursiv: boolean }[] {
  const teile: { text: string; kursiv: boolean }[] = [];
  let pos = 0;
  for (const m of text.matchAll(KURSIV)) {
    const i = m.index ?? 0;
    if (i > pos) teile.push({ text: text.slice(pos, i), kursiv: false });
    teile.push({ text: m[1], kursiv: true });
    pos = i + m[0].length;
  }
  if (pos < text.length) teile.push({ text: text.slice(pos), kursiv: false });
  return teile;
}

export type HeadingDaten = z.infer<typeof HeadingSchema>;
export type TextDaten = z.infer<typeof TextSchema>;
export type ButtonDaten = z.infer<typeof ButtonSchema>;
export type ImageDaten = z.infer<typeof ImageSchema>;
