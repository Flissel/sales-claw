import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ABSCHNITTE, einfuegen } from '../src/abschnitte.ts';
import { ANZEIGE, medienName, nurErreichbare } from '../src/pult.ts';

const DOK = { root: { type: 'EmailLayout', data: { canvasColor: '#0f2422', textColor: '#cfe3df', childrenIds: ['a', 'b'] } },
  a: { type: 'Text', data: { props: { text: 'eins' } } }, b: { type: 'Text', data: { props: { text: 'zwei' } } } };

function zaehler() { let n = 0; return () => `x${++n}`; }

test('alle acht Abschnitte', () => {
  assert.deepEqual(ABSCHNITTE.map((a) => a.schluessel),
    ['kopfbild', 'bild_text', 'zwei_spalten', 'drei_spalten', 'zitat', 'grosse_zahl', 'knopfleiste', 'fussgruss']);
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
