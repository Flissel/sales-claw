import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';

import { pultStore } from '../../pultZustand';

import KontextChips from './KontextChips';

beforeEach(() => pultStore.setState({ chatAuswahl: [], chatAnhaenge: [] }));

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

describe('KontextChips', () => {
  it('veraltete Markierung ausgegraut mit „aus der letzten Nachricht“', () => {
    pultStore.setState({ chatAuswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Herbst', alt: true }] });
    const html = rendern(<KontextChips />);
    expect(html).toContain('Überschrift · Herbst');
    expect(html).toContain('aus der letzten Nachricht');
    expect(html).toContain('Wieder mitschicken: Überschrift · Herbst');
  });
  it('liegengebliebene Einzelauswahl erscheint ebenso', () => {
    const html = rendern(<KontextChips altform={{ kurz: 'Text · Hallo' }} />);
    expect(html).toContain('Text · Hallo');
    expect(html).toContain('aus der letzten Nachricht');
  });
  it('frische Chips ohne Vermerk', () => {
    pultStore.setState({ chatAuswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Herbst' }] });
    const html = rendern(<KontextChips />);
    expect(html).toContain('Überschrift · Herbst');
    expect(html).not.toContain('aus der letzten Nachricht');
  });
});
