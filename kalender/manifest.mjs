// Schreibt sales-mcp/static/kalender/MANIFEST.json nach dem Bauen (Pruefsummen
// fuer tests/test_kalender_paket.py). Aufruf: npm run build
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const hier = import.meta.dirname;
const ordner = join(hier, '..', 'sales-mcp', 'static', 'kalender');
const sperre = JSON.parse(readFileSync(join(hier, 'package-lock.json'), 'utf8'));
const version = sperre.packages['node_modules/@fullcalendar/core'].version;
const sha256 = {};
for (const name of ['kalender.js', 'kalender.css']) {
  sha256[name] = createHash('sha256').update(readFileSync(join(ordner, name))).digest('hex');
}
const manifest = { quelle: `fullcalendar@${version}`, gebaut: new Date().toISOString(), sha256 };
writeFileSync(join(ordner, 'MANIFEST.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log(manifest);
