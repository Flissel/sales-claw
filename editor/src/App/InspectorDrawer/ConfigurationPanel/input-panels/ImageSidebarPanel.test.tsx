import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { pultStore } from '../../../../pultZustand';
import { ImageDaten } from '../../../../schemata';

vi.mock('../../../../documents/editor/EditorContext', () => ({ useSelectedBlockId: () => 'held' }));

import ImageSidebarPanel from './ImageSidebarPanel';

// zustand rendert auf dem Server den INITIAL-Zustand (getInitialState); fuer den Aufruf auf den aktuellen Stand setzen.
const INITIAL = { ...pultStore.getInitialState() };
function rendern(el: React.ReactElement): string {
  Object.assign(pultStore.getInitialState(), pultStore.getState());
  try {
    return renderToStaticMarkup(el);
  } finally {
    Object.assign(pultStore.getInitialState(), INITIAL);
  }
}

const PLATZ = { props: { width: 600, height: 300, url: null } } as unknown as ImageDaten;

beforeEach(() => pultStore.setState({ stand: null, medien: [] }));

describe('ImageSidebarPanel', () => {
  it('Bildaufträge nur über den Assistenten, keine KI-Knöpfe', () => {
    const html = rendern(<ImageSidebarPanel data={PLATZ} setData={() => undefined} />);
    expect(html).toContain('Bild erzeugen, ändern oder freistellen: Bild markieren und den Assistenten fragen');
    expect(html).not.toContain('Hinweis (optional)');
    expect(html).not.toContain('Stärke der Überarbeitung');
    expect(html).not.toContain('Ganz neu erzeugen');
    expect(html).not.toContain('Freistellen<');
    expect(html).toContain('Aus Medien wählen');
    expect(html).toContain('Alternativtext');
  });

  it('laufender Auftrag am Platz erscheint als Stand-Chip', () => {
    pultStore.setState({ stand: { auftraege: [{ platz: 'held', status: 'in_arbeit' }] } as never });
    const html = rendern(<ImageSidebarPanel data={PLATZ} setData={() => undefined} />);
    expect(html).toContain('wird erzeugt');
  });
});
