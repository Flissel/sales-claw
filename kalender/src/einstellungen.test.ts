import { describe, expect, it } from 'vitest';

import { grundOptionen, naechsteVolleStunde } from './einstellungen';

describe('grundOptionen', () => {
  it('keine Symbol-Schrift: die CSP der Seite blockiert die data:-Schrift fcicons', () => {
    expect(grundOptionen(true).buttonIcons).toBe(false);
    expect(grundOptionen(false).buttonIcons).toBe(false);
  });

  it('ganzer Tag im Zeitraster, Start bei 07:00, feste Hoehe zum Scrollen', () => {
    const o = grundOptionen(true);
    expect(o.slotMinTime).toBe('00:00');
    expect(o.slotMaxTime).toBe('24:00');
    expect(o.scrollTime).toBe('07:00');
    expect(typeof o.contentHeight).toBe('number');
    expect(o.height).toBeUndefined();
    expect(o.businessHours).toEqual({ daysOfWeek: [1, 2, 3, 4, 5], startTime: '08:00', endTime: '18:00' });
  });

  it('Knopf "Neu" nur mit Schreibrecht', () => {
    expect(String(grundOptionen(true).headerToolbar && (grundOptionen(true).headerToolbar as { left: string }).left)).toContain('neu');
    expect((grundOptionen(false).headerToolbar as { left: string }).left).not.toContain('neu');
  });
});

describe('naechsteVolleStunde', () => {
  it('rundet auf die naechste volle Stunde', () => {
    expect(naechsteVolleStunde(new Date(2026, 9, 20, 10, 15))).toEqual(new Date(2026, 9, 20, 11, 0));
    expect(naechsteVolleStunde(new Date(2026, 9, 20, 10, 0))).toEqual(new Date(2026, 9, 20, 11, 0));
    expect(naechsteVolleStunde(new Date(2026, 9, 20, 23, 30))).toEqual(new Date(2026, 9, 21, 0, 0));
  });
});
