import React from 'react';
import { renderToString } from 'react-dom/server';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AbschnittLeiste from './App/AbschnittLeiste';
import GestaltungFenster, { zurueckGesperrt } from './App/Gestaltung/GestaltungFenster';
import { fensterTaste, type FensterTasteEreignis } from './App/Gestaltung/useFensterTasten';
import type { GestaltungZustand } from './App/Gestaltung/useGestaltung';
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
// Darum zusaetzlich eine Textpruefung je Zeile: kein Hook-Aufruf (useX(...) oder der Store-Hook
// pultStore(...)) als rechter Operand von ||, && oder ?? oder als Zweig eines Ternaers (? / :),
// und - wie bisher - keiner als linker Operand von || oder && (Auslöser des Fehlers: ein Hook nach einem
// kurzschliessenden Operator laeuft nur manchmal). Eine Zeile, kein Parser - grob, aber billig.
const HOOK = String.raw`(?:use[A-Z]\w*|pultStore)\(`;
const HOOK_RECHTS = new RegExp(String.raw`(?:\|\||&&|\?\?|\?|:)\s*${HOOK}`);
const HOOK_LINKS = new RegExp(String.raw`${HOOK}[^)]*\)\s*(?:\|\||&&)`);
function bedingterHook(zeile: string): boolean {
  return HOOK_RECHTS.test(zeile) || HOOK_LINKS.test(zeile);
}

describe('Hooks nie bedingt aufrufen', () => {
  it('die Pruefung selbst erkennt die Muster', () => {
    for (const z of [
      'const a = x || useA();',
      'const a = x && useA();',
      'const a = x ?? useA();',
      'const a = x ? useA() : 1;',
      'const a = x ? 1 : useA();',
      'const a = x || pultStore((s) => s.nurLesen);',
      'const a = x ? pultStore((s) => s.chat) : null;',
      'const a = useA() || x;',
    ]) {
      expect(bedingterHook(z), z).toBe(true);
    }
    for (const z of [
      'const a = useA();',
      'const nurLesen = pultStore((s) => s.nurLesen);',
      'const b = useB(x ? 1 : 2);',
      'const c = useC() ? 1 : 2;',
      // linker Operand von ?? laeuft immer (useAgentArbeitet() ?? ... im Gestaltungsfenster)
      'const d = useD() ?? (x ? 1 : null);',
    ]) {
      expect(bedingterHook(z), z).toBe(false);
    }
  });

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
          if (bedingterHook(z)) schlecht.push(`${d}:${i + 1}: ${z.trim()}`);
        });
    }
    expect(schlecht).toEqual([]);
  });
});

describe('Gestaltungsfenster bei nurLesen (T7b)', () => {
  function zustand(auswahl: string | null) {
    return {
      auswahl,
      waehlen: vi.fn(),
      vor: vi.fn(),
      zurueck: vi.fn(),
      ebeneLoeschen: vi.fn(),
      ebeneAendern: vi.fn(),
    } as unknown as GestaltungZustand & Record<'waehlen' | 'vor' | 'zurueck' | 'ebeneLoeschen' | 'ebeneAendern', ReturnType<typeof vi.fn>>;
  }
  const taste = (key: string, extra: Partial<KeyboardEvent> = {}) =>
    ({ key, ctrlKey: false, metaKey: false, shiftKey: false, preventDefault: vi.fn(), ...extra }) as FensterTasteEreignis;

  it('Esc hebt die Auswahl auch gesperrt auf; alles andere wirkt gesperrt nicht', () => {
    const z = zustand('e1');
    fensterTaste(taste('Escape'), null, z, new Set(), true);
    expect(z.waehlen).toHaveBeenCalledWith(null);
    for (const t of [taste('Delete'), taste('ArrowLeft'), taste('z', { ctrlKey: true })]) {
      fensterTaste(t, null, z, new Set(), true);
    }
    expect(z.ebeneLoeschen).not.toHaveBeenCalled();
    expect(z.ebeneAendern).not.toHaveBeenCalled();
    expect(z.zurueck).not.toHaveBeenCalled();
    fensterTaste(taste('Delete'), null, z, new Set(), false);       // frei: wie bisher
    expect(z.ebeneLoeschen).toHaveBeenCalledWith('e1');
  });

  it('"Zurück zum Newsletter" bleibt bei nurLesen bedienbar, nicht aber waehrend der Agent arbeitet', () => {
    expect(zurueckGesperrt(false, LIEGT_ZUR_FREIGABE, true)).toBe(false);
    expect(zurueckGesperrt(false, 'Der Assistent arbeitet gerade', false)).toBe(true);
    expect(zurueckGesperrt(true, null, true)).toBe(true);
    expect(zurueckGesperrt(false, null, false)).toBe(false);
  });

  it('gerendert: der Knopf ist bei nurLesen nicht disabled', () => {
    const dok = { ...DOK, b: { type: 'Image', data: { props: { url: 'x.png', alt: 'A' } } } } as TEditorConfiguration;
    // renderToString warnt fuer useLayoutEffect (Flaeche) - erwartet, nur Rauschen
    const leise = vi.spyOn(console, 'error').mockImplementation(() => {});
    const knopf = () => {
      const html = rendern(GestaltungFenster);
      const i = html.indexOf('Zurück zum Newsletter');
      return html.slice(html.lastIndexOf('<button', i), i);
    };
    try {
      resetDocument(dok);
      pultStarten({ ...START, status: 'eingereicht' });
      pultStore.setState({ chat: null, gestaltungOffen: 'b' });
      expect(knopf()).not.toMatch(/disabled/);
      pultStarten(START);                                              // Gegenprobe: Agent arbeitet
      pultStore.setState({ chat: LAEUFT, gestaltungOffen: 'b' });
      expect(knopf()).toMatch(/disabled/);
    } finally {
      pultStore.setState({ gestaltungOffen: null });
      leise.mockRestore();
    }
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
