import assert from 'node:assert/strict';
import { test } from 'node:test';

import { erzeugenSperre, formatText, istLeer, istPlatz, standFuer } from '../src/bildfeld.ts';

test('formatText wie die Marketing-API', () => {
  assert.equal(formatText(600, 300), '2:1 · 1200×608');
  assert.equal(formatText(268, 201), '4:3 · 544×416');
  assert.equal(formatText(172, 172), '1:1 · 352×352');
  assert.equal(formatText(552, 311), '16:9 · 1104×624');
});

test('Platz und leer', () => {
  assert.ok(istPlatz({ width: 600, height: 300 }));
  assert.ok(!istPlatz({ width: 600, height: 0 }) && !istPlatz({ width: null, height: 300 }) && !istPlatz(undefined));
  assert.ok(istLeer('') && istLeer(null) && istLeer('/medien/datei/platzhalter-2x1.png') && istLeer('medien:platzhalter-4x3.png'));
  assert.ok(!istLeer('/medien/datei/nl-0123abcd-kopf.jpg'));
});

test('standFuer', () => {
  const a = (platz, status, befund = '') => ({ platz, status, befund });
  assert.deepEqual(standFuer('kopf', []), { text: '', art: null });
  assert.deepEqual(standFuer('kopf', [a(null, 'offen')]), { text: 'wartet (PC muss laufen)', art: 'wartet' });
  assert.deepEqual(standFuer('kopf', [a('kopf', 'in_arbeit'), a(null, 'offen')]), { text: 'wird erzeugt', art: 'laeuft' });
  assert.deepEqual(standFuer('kopf', [a('kopf', 'fehler', 'Schrift im Bild')]),
    { text: 'fehlgeschlagen: Schrift im Bild', art: 'fehler' });
  assert.deepEqual(standFuer('kopf', [a('kopf', 'fertig'), a('kopf', 'fehler', 'x')]), { text: '', art: null });
  assert.deepEqual(standFuer('kopf', [a('neben', 'offen')]), { text: '', art: null });
});

test('erzeugenSperre', () => {
  assert.equal(erzeugenSperre(false, { width: 600, height: 300 }), null);
  assert.match(erzeugenSperre(true, { width: 600, height: 300 }), /^Erst speichern/);
  assert.match(erzeugenSperre(false, { width: 600, height: 0 }), /^Kein Bildplatz/);
});
