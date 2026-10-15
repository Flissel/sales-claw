import assert from 'node:assert/strict';
import { test } from 'node:test';

import { readFileSync } from 'node:fs';

import { ABSCHNITTE, einfuegen, farbenAus, golden } from '../src/abschnitte.ts';
import { ANZEIGE, medienName, nurErreichbare } from '../src/pult.ts';

const DOK = { root: { type: 'EmailLayout', data: { canvasColor: '#0f2422', textColor: '#cfe3df', childrenIds: ['a', 'b'] } },
  a: { type: 'Text', data: { props: { text: 'eins' } } }, b: { type: 'Text', data: { props: { text: 'zwei' } } } };

function zaehler() { let n = 0; return () => `x${++n}`; }

test('alle dreizehn Abschnitte', () => {
  assert.deepEqual(ABSCHNITTE.map((a) => a.schluessel),
    ['kopfbild', 'bild_text', 'zwei_spalten', 'drei_spalten', 'zitat', 'grosse_zahl', 'knopfleiste', 'fussgruss',
      'brief', 'portraet_gruss', 'kundenstimme', 'farbband', 'einladung']);
});

for (const { schluessel } of ABSCHNITTE) {
  test(`${schluessel}: an Stelle 1 eingefuegt, alles erreichbar, Eingabe unveraendert`, () => {
    const vorher = structuredClone(DOK);
    const neu = einfuegen(DOK, schluessel, 1, zaehler());
    assert.deepEqual(DOK, vorher);
    assert.equal(neu.root.data.childrenIds[0], 'a');
    assert.equal(neu.root.data.childrenIds.at(-1), 'b');
    assert.equal(neu.root.data.childrenIds.length, 3);
    assert.deepEqual(Object.keys(nurErreichbare(neu)).sort(), Object.keys(neu).sort());
    for (const [id, b] of Object.entries(neu)) {
      if (id === 'root') continue;
      assert.match(id, /^[A-Za-z0-9_-]{1,64}$/);
      if (b.type === 'Image') {
        assert.ok(b.data.props.width > 0 && b.data.props.height > 0, `${id} ist ein Bildplatz`);
        assert.ok(b.data.props.url.startsWith(ANZEIGE), `${id}: url beginnt mit ANZEIGE`);
        assert.match(medienName(b.data.props.url) ?? '', /^platzhalter-\d+x\d+\.png$/);
        assert.ok(b.data.props.alt);
      }
      if (b.type === 'ColumnsContainer') assert.equal(b.data.props.columns.length, 3);
      if (b.type === 'Button') assert.match(b.data.props.url, /^https:\/\//);
    }
  });
}

test('index wird gekappt, ids kollidieren nicht', () => {
  const n = einfuegen(DOK, 'kopfbild', 99, () => 'a');       // Generator liefert eine vorhandene id
  assert.equal(n.root.data.childrenIds.length, 3);
  assert.equal(n.root.data.childrenIds[0], 'a');
  assert.notEqual(n.root.data.childrenIds[2], 'a');
  assert.equal(new Set(n.root.data.childrenIds).size, 3);
});


// Helle Vorlage mit Ladenmarke (wie studio nach dem Fuellen): Rollen zeigen auf echte Werte.
const HELL = { root: { type: 'EmailLayout', data: { canvasColor: '#faf7f2', textColor: '#2b2724', childrenIds: ['knopf', 'titel'],
  rollen: { 'knopf/data/props/buttonBackgroundColor': 'akzent', 'knopf/data/props/buttonTextColor': 'auf_akzent',
    'titel/data/style/color': 'akzent_text' } } },
  knopf: { type: 'Button', data: { props: { text: 'Los', url: 'https://x.de', buttonBackgroundColor: '#b5562f', buttonTextColor: '#ffffff' } } },
  titel: { type: 'Heading', data: { style: { color: '#8f3f1f' }, props: { text: 'T' } } } };

test('Farben kommen aus der Ladenmarke, nicht aus festen Petrol-Toenen', () => {
  const f = farbenAus(HELL);
  assert.equal(f.akzent, '#b5562f');
  assert.equal(f.aufAkzent, '#ffffff');
  assert.equal(f.akzentText, '#8f3f1f');
  assert.equal(f.hell, '#2b2724', 'Ueberschrift auf hellem Grund in Textfarbe, nicht fast weiss');
  assert.equal(f.grund, '#faf7f2');
  assert.notEqual(f.karte, f.grund);
});

test('ohne Rollen: Akzent vom ersten Knopf, sonst der alte Standard', () => {
  const ohne = structuredClone(HELL); delete ohne.root.data.rollen;
  assert.equal(farbenAus(ohne).akzent, '#b5562f');
  assert.equal(farbenAus(DOK).akzent, '#5eead4');
});

test('warme Abschnitte: Portraet als Kreis, Band randlos in Akzentfarbe, Brief mit Anrede', () => {
  const zeig = (s) => { const n = einfuegen(HELL, s, 0, zaehler()); return Object.values(n).filter((b) => b.type !== 'EmailLayout'); };
  assert.ok(zeig('portraet_gruss').some((b) => b.type === 'Image' && b.data.props.form === 'kreis'));
  assert.ok(zeig('kundenstimme').some((b) => b.type === 'Image' && b.data.props.form === 'kreis'));
  const band = zeig('farbband').find((b) => b.type === 'Container');
  assert.equal(band.data.props.randlos, true);
  assert.equal(band.data.style.backgroundColor, '#b5562f');
  assert.ok(zeig('brief').some((b) => b.type === 'Text' && b.data.props.text.startsWith('Hallo')));
  assert.ok(zeig('einladung').some((b) => b.type === 'Button' && b.data.props.buttonStyle === 'pill'));
});

test('Golden-Datei (Bauplaene fuer den Marketing-Agenten) ist aktuell', () => {
  const datei = JSON.parse(readFileSync(new URL('./abschnitte.golden.json', import.meta.url), 'utf8'));
  assert.deepEqual(datei, golden(), 'node scripts/abschnitte_golden.mjs ausfuehren');
});
