import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import SeitenGriff from './SeitenGriff';

describe('SeitenGriff', () => {
  it('ist ein ziehbarer, per Tastatur bedienbarer Trenner mit der aktuellen Breite', () => {
    const html = renderToStaticMarkup(<SeitenGriff breite={480} onBreite={() => {}} />);
    expect(html).toContain('role="separator"');
    expect(html).toContain('aria-valuenow="480"');
    expect(html).toContain('aria-valuemin="360"');
    expect(html).toContain('Breite der Seitenleiste');
  });
});
