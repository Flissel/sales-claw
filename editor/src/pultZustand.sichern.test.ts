import { afterEach, describe, expect, it, vi } from 'vitest';

import { getDocument, resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { newsletterSichern, pultStore } from './pultZustand';

const DOK = {
  root: { type: 'EmailLayout', data: { childrenIds: ['b'] } },
  b: { type: 'Image', data: { props: { url: null, alt: 'alt' } } },
} as TEditorConfiguration;

function vorbereiten() {
  resetDocument(DOK);
  pultStore.setState({
    start: { speichern_url: '/s', csrf: 'm' } as Start,
    betreff: 'B',
    vorschautext: 'V',
    basis: 3,
    ungespeichert: true,
  });
}

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('newsletterSichern', () => {
  it('Erfolg: Fassung wird Basis, nichts mehr ungespeichert, Aenderung landet im Dokument', async () => {
    vorbereiten();
    const f = vi.fn(async () => antwort(200, { fassung: 4 }));
    vi.stubGlobal('fetch', f);
    const neuesAlt = (d: TEditorConfiguration) => ({ ...d, b: { type: 'Image', data: { props: { url: null, alt: 'neu' } } } }) as TEditorConfiguration;
    const e = await newsletterSichern(false, neuesAlt);
    expect(e).toEqual({ ok: true, fassung: 4 });
    expect(pultStore.getState()).toMatchObject({ basis: 4, ungespeichert: false });
    const body = JSON.parse(String((f.mock.calls[0] as unknown as [string, RequestInit])[1].body));
    expect(body).toMatchObject({ basis_fassung: 3, betreff: 'B', vorschautext: 'V', als_kopie: false });
    expect(body.dokument.b.data.props.alt).toBe('neu');
    expect((getDocument().b.data as { props: { alt: string } }).props.alt).toBe('neu');
  });

  it('422: Grund zurueck, Basis und Dokument bleiben', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(409, { grund: 'Der Assistent arbeitet gerade' })));
    const e = await newsletterSichern(false, (d) => ({ ...d, b: { type: 'Image', data: { props: { url: null, alt: 'neu' } } } }) as TEditorConfiguration);
    expect(e).toEqual({ ok: false, konflikt: true, grund: 'Der Assistent arbeitet gerade' });
    expect(pultStore.getState()).toMatchObject({ basis: 3, ungespeichert: true });
    expect((getDocument().b.data as { props: { alt: string } }).props.alt).toBe('alt');
  });
});
