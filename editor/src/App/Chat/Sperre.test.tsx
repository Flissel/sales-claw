import { describe, expect, it } from 'vitest';

import { schichtLage } from './Sperre';

describe('schichtLage', () => {
  it('laesst Zeiger und Rad durch die Sperrschicht', () => {
    const lage = schichtLage({ position: 'fixed', top: 0, zIndex: 1201 });
    expect(lage.pointerEvents).toBe('none');
    expect(lage.position).toBe('fixed');
    expect(lage.zIndex).toBe(1201);
  });
});
