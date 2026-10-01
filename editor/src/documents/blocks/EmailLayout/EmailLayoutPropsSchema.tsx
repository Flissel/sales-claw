import { z } from 'zod';

import { SCHRIFT_IDS } from '../../../schemata';

const COLOR_SCHEMA = z
  .string()
  .regex(/^#[0-9a-fA-F]{6}$/)
  .nullable()
  .optional();

const FONT_FAMILY_SCHEMA = z
  .enum([
    'MODERN_SANS',
    'BOOK_SANS',
    'ORGANIC_SANS',
    'GEOMETRIC_SANS',
    'HEAVY_SANS',
    'ROUNDED_SANS',
    'MODERN_SERIF',
    'BOOK_SERIF',
    'MONOSPACE',
  ])
  .nullable()
  .optional();

const EmailLayoutPropsSchema = z.object({
  backdropColor: COLOR_SCHEMA,
  borderColor: COLOR_SCHEMA,
  borderRadius: z.number().optional().nullable(),
  canvasColor: COLOR_SCHEMA,
  textColor: COLOR_SCHEMA,
  fontFamily: FONT_FAMILY_SCHEMA,
  childrenIds: z.array(z.string()).optional().nullable(),
  // Vorlagen-Metadaten (Spec §4): Schriftpaar, Dark-Mode, Rollen der Ladenmarke.
  schriften: z
    .object({ anzeige: z.enum(SCHRIFT_IDS), text: z.enum(SCHRIFT_IDS) })
    .partial()
    .nullable()
    .optional(),
  dunkel: z.boolean().nullable().optional(),
  rollen: z.record(z.string(), z.string()).nullable().optional(),
});

export default EmailLayoutPropsSchema;

export type EmailLayoutProps = z.infer<typeof EmailLayoutPropsSchema>;
