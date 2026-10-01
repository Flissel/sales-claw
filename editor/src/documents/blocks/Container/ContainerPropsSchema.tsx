import { z } from 'zod';

import { ContainerPropsSchema as BaseContainerPropsSchema } from '@usewaypoint/block-container';

// Farbfeld ueber dem Hintergrundbild (Spec §4): Farbe #rrggbb, Deckkraft 0-100.
export const OverlaySchema = z.object({
  farbe: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  deckkraft: z.number().min(0).max(100),
});

const ContainerPropsSchema = z.object({
  style: BaseContainerPropsSchema.shape.style
    .unwrap()
    .unwrap()
    .extend({ overlay: OverlaySchema.nullable().optional() })
    .optional()
    .nullable(),
  props: z
    .object({
      childrenIds: z.array(z.string()).optional().nullable(),
      // Hintergrundbild des Abschnitts: derselbe Ort wie beim Bildblock (medien:<datei>).
      url: z.string().nullable().optional(),
      width: z.number().nullable().optional(),
      height: z.number().nullable().optional(),
      grafik: z.boolean().nullable().optional(),
      // Bildhinweis fuer den Bild-Arbeiter (Hintergrund-Slot der Vorlage).
      alt: z.string().nullable().optional(),
    })
    .optional()
    .nullable(),
});

export default ContainerPropsSchema;

export type ContainerProps = z.infer<typeof ContainerPropsSchema>;
