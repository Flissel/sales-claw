import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import { DUNKEL, HELL } from '../src/pultFarben.ts';

const ui = readFileSync(join(import.meta.dirname, '..', '..', 'sales-mcp', 'ui.py'), 'utf8');

function bloecke() {
  const roots = [...ui.matchAll(/:root\s*\{([^}]*)\}/g)].map((m) => m[1]);
  const lesen = (s) => Object.fromEntries([...s.matchAll(/--([a-z_]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2].toLowerCase()]));
  return [lesen(roots[0]), lesen(roots[1])];
}

test('Editorfarben = Pult-Farben aus ui.py (hell und dunkel)', () => {
  const [hell, dunkel] = bloecke();
  for (const [k, v] of Object.entries(HELL)) assert.equal(v, hell[k], `hell ${k}`);
  for (const [k, v] of Object.entries(DUNKEL)) assert.equal(v, dunkel[k], `dunkel ${k}`);
});
