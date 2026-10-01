// Round-Trip-Waechter: jeder Block der sieben Newsletter-Vorlagen muss durch sein
// Editor-Schema unveraendert (deep-equal) hindurchgehen - sonst verwirft zod beim
// Bearbeiten stillschweigend Felder.
// Fixture-Refresh: die JSONs in __fixtures__/vorlagen/ sind Kopien aus
// vibemind-os/spaces/marketing/vorlagen/newsletter/*.json. Bei Aenderung der
// Vorlagen dort neu kopieren und diesen Test laufen lassen.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { EDITOR_DICTIONARY } from './documents/editor/core';

type Block = { type: string; data: unknown };
const DIR = join(__dirname, '__fixtures__', 'vorlagen');
const dateien = readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe('Vorlagen-Round-Trip', () => {
  it('alle sieben Vorlagen sind als Fixture vorhanden', () => {
    expect(dateien).toHaveLength(7);
  });
  for (const datei of dateien) {
    const vorlage = JSON.parse(readFileSync(join(DIR, datei), 'utf8')) as { bloecke: Record<string, Block> };
    describe(datei, () => {
      for (const [id, block] of Object.entries(vorlage.bloecke)) {
        it(`${id} (${block.type})`, () => {
          const def = (EDITOR_DICTIONARY as Record<string, { schema: { safeParse(v: unknown): { success: boolean; data?: unknown; error?: unknown } } }>)[block.type];
          expect(def, `unbekannter Blocktyp ${block.type}`).toBeDefined();
          const res = def.schema.safeParse(block.data);
          expect(res.success, JSON.stringify(res.error)).toBe(true);
          // Ein leeres style:{} darf wegfallen (Spacer kennt kein style) - das verliert nichts.
          const soll = { ...(block.data as Record<string, unknown>) };
          const st = soll.style;
          if (st && typeof st === 'object' && Object.keys(st).length === 0 && !(res.data as Record<string, unknown>).style) delete soll.style;
          expect(res.data).toEqual(soll);
        });
      }
    });
  }
});
