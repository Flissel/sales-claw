import { describe, expect, it } from 'vitest';

import { inertSetzen } from './sperren';

describe('inertSetzen', () => {
  it('setzt und loest inert am Element', () => {
    const el = { inert: false };
    inertSetzen(el, true);
    expect(el.inert).toBe(true);
    inertSetzen(el, false);
    expect(el.inert).toBe(false);
  });

  it('ohne Element passiert nichts', () => {
    expect(() => inertSetzen(null, true)).not.toThrow();
  });
});
