import assert from 'node:assert/strict';
import { test } from 'node:test';

import { erzeugenSperre, formatText, istLeer, istPlatz, knopfText, ladeEntscheid, neuesBildMeldung, staerkeWert, standFuer } from '../src/bildfeld.ts';

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

test('knopfText', () => {
  assert.equal(knopfText(true), 'Bild erzeugen');
  assert.equal(knopfText(false), 'Bild überarbeiten');
});

test('staerkeWert', () => {
  assert.equal(staerkeWert(30), 30);
  assert.equal(staerkeWert(0), 0);
  assert.equal(staerkeWert(100), 100);
  for (const x of [101, -1, 5.5, '30', null, undefined, NaN]) assert.equal(staerkeWert(x), 55);
});

test('ladeEntscheid', () => {
  assert.equal(ladeEntscheid(3, 3, false), null);
  assert.equal(ladeEntscheid(4, 3, false), 'laden');
  assert.equal(ladeEntscheid(4, 3, true), 'hinweis');
  assert.equal(ladeEntscheid(4, 3, false, null), 'laden');
  assert.equal(ladeEntscheid(4, 3, false, 3), 'laden');
  assert.equal(ladeEntscheid(4, 3, false, 4), 'hinweis');
  assert.equal(ladeEntscheid(4, 3, true, 4), 'hinweis');
  assert.equal(ladeEntscheid(3, 3, false, 3), null);
});

test('neuesBildMeldung', () => {
  const seit = Date.parse('2026-09-30T10:00:00Z');
  const neuer = '2026-09-30T10:05:00Z';
  const alt = '2026-09-30T09:00:00Z';
  assert.equal(neuesBildMeldung([], seit), null);
  assert.deepEqual(
    neuesBildMeldung([{ platz: 'kopf', status: 'fertig', geaendert_am: neuer, messung: { kopf: { aehnlich_original: 0.823 } } },
                      { platz: 'neben', status: 'fertig', geaendert_am: neuer, messung: {} }], seit),
    { platz: 'kopf', text: 'Neues Bild vom Agenten – 82 % Themen-Ähnlichkeit' });
  assert.deepEqual(neuesBildMeldung([{ platz: null, status: 'fertig', geaendert_am: neuer, messung: {} }], seit), null);
  assert.deepEqual(neuesBildMeldung([{ platz: 'kopf', status: 'fertig', geaendert_am: neuer }], seit),
    { platz: 'kopf', text: 'Neues Bild vom Agenten' });
  // alte, fehlende oder unlesbare Zeitstempel zaehlen nicht (reines Text-Speichern)
  assert.equal(neuesBildMeldung([{ platz: 'kopf', status: 'fertig', geaendert_am: alt }], seit), null);
  assert.equal(neuesBildMeldung([{ platz: 'kopf', status: 'fertig' }], seit), null);
  assert.equal(neuesBildMeldung([{ platz: 'kopf', status: 'fertig', geaendert_am: 'gestern' }], seit), null);
  assert.deepEqual(
    neuesBildMeldung([{ platz: 'alt', status: 'fertig', geaendert_am: alt }, { platz: 'kopf', status: 'fertig', geaendert_am: neuer }], seit),
    { platz: 'kopf', text: 'Neues Bild vom Agenten' });
});
test('standFuer ueberarbeiten', () => {
  assert.deepEqual(standFuer('kopf', [{ platz: 'kopf', status: 'in_arbeit', modus: 'ueberarbeiten' }]),
    { text: 'wird überarbeitet', art: 'laeuft' });
  assert.deepEqual(standFuer('kopf', [{ platz: 'kopf', status: 'in_arbeit', modus: 'neu' }]),
    { text: 'wird erzeugt', art: 'laeuft' });
});
