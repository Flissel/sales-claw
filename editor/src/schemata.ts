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

// Vorhandene Schnitte je Schrift als [gewicht, kursiv]; gespiegelt aus claw/schriften.py REGISTER.
export const SCHNITTE: Record<SchriftId, Array<[number, boolean]>> = {
  cormorant: [[400, false], [400, true]],
  'dm-sans': [[400, false], [700, false]],
  playfair: [[900, false]],
  poppins: [[400, false], [600, false], [700, false]],
  'young-serif': [[400, false]],
  manrope: [[300, false], [400, false], [700, false]],
  bodoni: [[500, false], [500, true]],
  montserrat: [[400, false], [600, false]],
  josefin: [[300, false], [700, false]],
  oxanium: [[600, false], [700, false]],
  rajdhani: [[500, false], [600, false]],
};

const FARBE = /^#[0-9a-fA-F]{6}$/;
const EBENE_ID = /^[A-Za-z0-9_-]{1,32}$/;
const QUELLE = /^medien:[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(png|jpe?g|gif|webp)$/;

const BildEbeneSchema = z.object({
  id: z.string().regex(EBENE_ID),
  art: z.literal('bild'),
  quelle: z.string().regex(QUELLE).refine((q) => !q.includes('..')),
  x: z.number().min(-600).max(1200),
  y: z.number().min(-750).max(1500),
  breite: z.number().min(8).max(3000),
  drehung: z.number().min(-180).max(180),
});

const TextEbeneSchema = z
  .object({
    id: z.string().regex(EBENE_ID),
    art: z.literal('text'),
    text: z
      .string()
      .max(200)
      .refine((t) => t.split('\n').length <= 6),
    schrift: z.enum(SCHRIFT_IDS),
    gewicht: z.number().int(),
    kursiv: z.boolean(),
    groesse: z.number().min(10).max(160),
    farbe: z.string().regex(FARBE),
    ausrichtung: z.enum(['links', 'mitte', 'rechts']),
    zeilenabstand: z.number().min(0.8).max(2),
    x: z.number().min(-600).max(1200),
    y: z.number().min(-750).max(1500),
    drehung: z.number().min(-180).max(180),
  })
  .refine((t) => SCHNITTE[t.schrift].some(([g, k]) => g === t.gewicht && k === t.kursiv), {
    message: 'Schnitt der Schrift nicht vorhanden',
  });

export const GestaltungSchema = z.object({
  version: z.literal(1),
  format: z.enum(['quer', 'quadrat', 'hoch', 'banner']),
  hintergrund: z.string().regex(FARBE),
  ebenen: z.array(z.union([BildEbeneSchema, TextEbeneSchema])).max(20),
});

const bildProps = ImagePropsSchema.shape.props.unwrap().unwrap();
export const ImageSchema = z.object({
  style: ImagePropsSchema.shape.style,
  props: bildProps
    .extend({ sw: z.boolean().nullable().optional(), grafik: z.boolean().nullable().optional(),
      gestaltung: GestaltungSchema.nullable().optional(),
    })
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
