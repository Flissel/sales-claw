import React from 'react';
import { renderToString } from 'react-dom/server';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AbschnittLeiste from './App/AbschnittLeiste';
import TemplatePanel from './App/TemplatePanel';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import {
  anhangHinzu,
  chatAbschicken,
  chatRueckgaengig,
  chatVormerken,
  fensterWiederOeffnen,
  LIEGT_ZUR_FREIGABE,
  pultStarten,
  pultStore,
  vormerkungStartenAuftrag,
} from './pultZustand';

const DOK = { root: { type: 'EmailLayout', data: { childrenIds: [] } } } as TEditorConfiguration;
const START = { dokument: DOK, betreff: 'B', vorschautext: '', basis_fassung: 1, csrf: 'm', chat_url: '/c', einreichen_url: '/e', zurueckziehen_url: '/z' } as Start;
const LAEUFT = { laeuft: true, verlauf: [], live: null, vorgemerkt: null };

function lesend() {
  resetDocument(DOK);
  pultStarten({ ...START, status: 'eingereicht', eingereicht_am: '2026-10-07T09:30:00+00:00' });
  pultStore.setState({ chat: null });
}

// zustand rendert auf dem Server den INITIAL-Zustand (getInitialState). Damit renderToString den
// aktuellen Stand sieht, wird dieses Objekt fuer den Aufruf auf den aktuellen Store-Stand gesetzt.
const INITIAL = { ...pultStore.getInitialState() };
function rendern(komponente: React.ComponentType): string {
  Object.assign(pultStore.getInitialState(), pultStore.getState());
  try {
    return renderToString(React.createElement(komponente));
  } finally {
    Object.assign(pultStore.getInitialState(), INITIAL);
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  pultStore.setState({ chat: null, nurLesen: false });
});

describe('Smoke: Sperrzustaende rendern ohne Fehler (renderToString, kein DOM-Werkzeug installiert)', () => {
  for (const [name, f] of [['TemplatePanel', TemplatePanel], ['AbschnittLeiste', AbschnittLeiste]] as const) {
    it(`${name}: frei, Agent arbeitet, nurLesen`, () => {
      resetDocument(DOK);
      pultStarten(START);
      pultStore.setState({ chat: null, nurLesen: false });
      expect(() => rendern(f)).not.toThrow();
      pultStore.setState({ chat: LAEUFT });
      expect(() => rendern(f)).not.toThrow();
      pultStore.setState({ chat: null, nurLesen: true });
      expect(() => rendern(f)).not.toThrow();
    });
  }

  it('nurLesen zeigt das Liegt-Band in der Pult-Leiste', () => {
    lesend();
    const html = rendern(TemplatePanel);
    expect(html).toContain('Liegt zur Freigabe');
    expect(html).toContain('Zurückziehen');
    pultStarten(START);
    expect(rendern(TemplatePanel)).not.toContain('Liegt zur Freigabe');
    expect(rendern(TemplatePanel)).toContain('Zur Freigabe einreichen');
  });
});

// renderToString kann eine wechselnde Hook-Reihenfolge nicht sehen (jeder Aufruf beginnt frisch).
// Darum zusaetzlich: kein Hook-Aufruf als Operand von ||, && oder ?? (Auslöser des Fehlers).
describe('Hooks nie bedingt aufrufen', () => {
  function dateien(ordner: string): string[] {
    return readdirSync(ordner).flatMap((n) => {
      const p = join(ordner, n);
      return statSync(p).isDirectory() ? dateien(p) : /\.(tsx?|ts)$/.test(n) && !/\.test\./.test(n) ? [p] : [];
    });
  }
  it('in src/App', () => {
    const schlecht: string[] = [];
    for (const d of dateien(join(__dirname, 'App'))) {
      readFileSync(d, 'utf8')
        .split('\n')
        .forEach((z, i) => {
          if (/(\|\||&&)\s*use[A-Z]\w*\(/.test(z) || /use[A-Z]\w*\([^)]*\)\s*(\|\||&&)/.test(z)) schlecht.push(`${d}:${i + 1}: ${z.trim()}`);
        });
    }
    expect(schlecht).toEqual([]);
  });
});

describe('Sperren bei nurLesen (Store)', () => {
  it('chatAbschicken / chatVormerken / vormerkungStartenAuftrag / chatRueckgaengig / anhangHinzu rufen nichts auf', async () => {
    lesend();
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await chatAbschicken('hallo', {} as never)).toBe(LIEGT_ZUR_FREIGABE);
    expect(await chatVormerken('hallo', {} as never)).toBe(LIEGT_ZUR_FREIGABE);
    expect(await vormerkungStartenAuftrag()).toBe(LIEGT_ZUR_FREIGABE);
    expect(await chatRueckgaengig('x')).toBe(LIEGT_ZUR_FREIGABE);
    expect(anhangHinzu(new File(['x'], 'a.png', { type: 'image/png' }))).toBe(LIEGT_ZUR_FREIGABE);
    expect(f).not.toHaveBeenCalled();
    expect(pultStore.getState().chatAnhaenge).toEqual([]);
  });

  it('fensterWiederOeffnen oeffnet bei nurLesen nichts', () => {
    const speicher = new Map<string, string>([['vibemind-fenster', 'b']]);
    vi.stubGlobal('sessionStorage', {
      getItem: (k: string) => speicher.get(k) ?? null,
      removeItem: (k: string) => void speicher.delete(k),
      setItem: (k: string, v: string) => void speicher.set(k, v),
    });
    resetDocument({ ...DOK, b: { type: 'Image', data: { props: {} } } } as TEditorConfiguration);
    pultStarten({ ...START, status: 'eingereicht' });
    fensterWiederOeffnen();
    expect(pultStore.getState().gestaltungOffen).toBeNull();
    expect(speicher.has('vibemind-fenster')).toBe(false);
  });
});
