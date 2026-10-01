// Reine Funktionen aus src/pult.ts. Aufruf (Node >= 23.6, TypeScript ohne Build):
//   cd editor && node --test test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  alterWegHinweis,
  fehlerText,
  medienName,
  mitNachfahren,
  nurErreichbare,
  zurAnzeige,
  zurSpeicherung,
} from '../src/pult.ts';

const DOK = {
  root: { type: 'EmailLayout', data: { childrenIds: ['h', 'rahmen', 'spalten'] } },
  h: { type: 'Heading', data: { props: { text: 'Hallo' } } },
  rahmen: { type: 'Container', data: { props: { childrenIds: ['r1', 'r2'] } } },
  r1: { type: 'Text', data: { props: { text: 'eins' } } },
  r2: { type: 'Image', data: { props: { url: '/medien/datei/logo%20neu.png' } } },
  spalten: {
    type: 'ColumnsContainer',
    data: { props: { columns: [{ childrenIds: ['s1'] }, { childrenIds: [] }, { childrenIds: ['s3'] }] } },
  },
  s1: { type: 'Text', data: { props: { text: 'links' } } },
  s3: { type: 'Button', data: { props: { text: 'Los', url: 'https://x.de' } } },
};

test('nurErreichbare laesst ein vollstaendiges Dokument unveraendert', () => {
  assert.deepEqual(nurErreichbare(DOK), DOK);
});

test('nurErreichbare wirft Waisen weg - auch ganze verwaiste Teilbaeume', () => {
  const kaputt = structuredClone(DOK);
  kaputt.root.data.childrenIds = ['h', 'spalten']; // Rahmen geloescht, Kinder r1/r2 blieben (C1)
  kaputt.waise = { type: 'Spacer', data: {} };
  const neu = nurErreichbare(kaputt);
  assert.deepEqual(Object.keys(neu).sort(), ['h', 'root', 's1', 's3', 'spalten']);
  assert.equal(kaputt.rahmen.type, 'Container', 'Eingabe bleibt unveraendert');
});

test('nurErreichbare haelt null-Kinderlisten, fehlende Verweise und Zyklen aus', () => {
  const d = {
    root: { type: 'EmailLayout', data: { childrenIds: ['a', 'fehlt'] } },
    a: { type: 'Container', data: { props: { childrenIds: null } } },
    b: { type: 'Container', data: { props: { childrenIds: ['c'] } } },
    c: { type: 'Container', data: { props: { childrenIds: ['b'] } } },
  };
  assert.deepEqual(Object.keys(nurErreichbare(d)).sort(), ['a', 'root']);
  assert.deepEqual(nurErreichbare({ x: { type: 'Text' } }), {});
});

test('mitNachfahren sammelt den Block und alles darunter, auch in Spalten', () => {
  assert.deepEqual([...mitNachfahren(DOK, 'rahmen')].sort(), ['r1', 'r2', 'rahmen']);
  assert.deepEqual([...mitNachfahren(DOK, 'spalten')].sort(), ['s1', 's3', 'spalten']);
  assert.deepEqual([...mitNachfahren(DOK, 'h')], ['h']);
});

test('zurSpeicherung: nur Erreichbares, Bilder zurueck auf medien:', () => {
  const kaputt = structuredClone(DOK);
  kaputt.waise = { type: 'Text', data: { props: { text: 'weg' } } };
  const neu = zurSpeicherung(kaputt);
  assert.equal(neu.waise, undefined);
  assert.equal(neu.r2.data.props.url, 'medien:logo neu.png');
});

test('Container-Hintergrundbild: medien: <-> Anzeige-Adresse wie beim Bildblock', () => {
  const d = structuredClone(DOK);
  d.rahmen.data.props = { ...d.rahmen.data.props, url: 'medien:kopf bild.jpg', width: 600, height: 300 };
  const anzeige = zurAnzeige(d);
  assert.equal(anzeige.rahmen.data.props.url, '/medien/datei/kopf%20bild.jpg');
  assert.deepEqual(anzeige.rahmen.data.props.childrenIds, ['r1', 'r2']);
  const zurueck = zurSpeicherung(anzeige);
  assert.equal(zurueck.rahmen.data.props.url, 'medien:kopf bild.jpg');
  assert.equal(zurueck.rahmen.data.props.height, 300);
});

test('zurSpeicherung: kaputtes %-Zeichen ist ein Inhaltsfehler, kein Netzfehler', () => {
  const d = structuredClone(DOK);
  d.r2.data.props.url = '/medien/datei/%E0%A4%A.png';
  assert.throws(() => zurSpeicherung(d), { message: 'Bildadresse ungültig' });
  assert.equal(medienName('/medien/datei/%E0%A4%A.png'), null);
  assert.equal(medienName('/medien/datei/a%20b.png'), 'a b.png');
  assert.equal(medienName('https://x/a.png'), null);
});

test('fehlerText verdoppelt weder Satzzeichen noch Wortlaut', () => {
  assert.equal(fehlerText('Keine Verbindung zum Pult'), 'Nicht gespeichert: Keine Verbindung zum Pult. Deine Änderungen sind noch da.');
  assert.equal(fehlerText('Links nur mit https:// in k.'), 'Nicht gespeichert: Links nur mit https:// in k. Deine Änderungen sind noch da.');
  assert.equal(fehlerText('  '), 'Nicht gespeichert: unbekannter Grund. Deine Änderungen sind noch da.');
});

test('alterWegHinweis nur fuer offene Vorschlaege im alten Weg', () => {
  assert.match(alterWegHinweis({ alter_weg: { status: 'pending_approval', kanal: 'email' } }), /alten Freigabeweg \(email\)/);
  assert.match(alterWegHinweis({ alter_weg: { status: 'draft', kanal: 'email' } }), /Im alten Weg ablehnen/);
  assert.equal(alterWegHinweis({ alter_weg: { status: 'sent', kanal: 'email' } }), null);
  assert.equal(alterWegHinweis({ alter_weg: null }), null);
  assert.equal(alterWegHinweis({}), null);
});
