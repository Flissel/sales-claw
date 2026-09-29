// Schreibt sales-mcp/static/editor/MANIFEST.json nach dem Bauen (Pruefsummen
// fuer tests/test_editor_paket.py). Aufruf: npm run build
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ordner = join(import.meta.dirname, '..', 'sales-mcp', 'static', 'editor');
const sha256 = {};
for (const name of ['editor.js', 'editor.css']) {
  sha256[name] = createHash('sha256').update(readFileSync(join(ordner, name))).digest('hex');
}
const manifest = { quelle: 'usewaypoint/email-builder-js@ce3e610', gebaut: new Date().toISOString(), sha256 };
writeFileSync(join(ordner, 'MANIFEST.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(manifest);
