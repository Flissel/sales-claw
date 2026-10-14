// HTTP-Schnittstelle zu ui_kalender.py. Jede Antwort wird zu {ok, status, daten};
// Fehler tragen immer daten.grund - auch wenn die Anmeldewache eine HTML-Seite schickt.

export interface Ergebnis {
  ok: boolean;
  status: number;
  daten: Record<string, unknown> & { grund?: string };
}

let csrf = '';

export function einrichten(marke: string): void {
  csrf = marke;
}

function ersatzGrund(status: number): string {
  if (status === 401 || status === 403) return 'Keine Berechtigung';
  if (status === 404) return 'Nicht gefunden';
  return `Unerwartete Antwort (${status})`;
}

async function anfrage(methode: string, url: string, body?: unknown): Promise<Ergebnis> {
  const kopf: Record<string, string> = { accept: 'application/json' };
  if (methode !== 'GET') {
    kopf['x-csrf'] = csrf;
    kopf['content-type'] = 'application/json';
  }
  let antwort: Response;
  try {
    antwort = await fetch(url, {
      method: methode,
      credentials: 'same-origin',
      headers: kopf,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, daten: { grund: 'Server nicht erreichbar' } };
  }
  let daten: Ergebnis['daten'] | null = null;
  if ((antwort.headers.get('content-type') ?? '').includes('application/json')) {
    try {
      const roh: unknown = await antwort.json();
      if (roh && typeof roh === 'object' && !Array.isArray(roh)) daten = roh as Ergebnis['daten'];
    } catch {
      daten = null;
    }
  }
  if (daten === null) daten = antwort.ok ? {} : { grund: ersatzGrund(antwort.status) };
  else if (!antwort.ok && typeof daten.grund !== 'string') daten.grund = ersatzGrund(antwort.status);
  return { ok: antwort.ok, status: antwort.status, daten };
}

const termin = (id: string) => `/kalender/termine/${encodeURIComponent(id)}`;

export function laden(von: string, bis: string): Promise<Ergebnis> {
  const q = new URLSearchParams({ von, bis });
  return anfrage('GET', `/kalender/termine.json?${q.toString()}`);
}

export function anlegen(body: Record<string, unknown>): Promise<Ergebnis> {
  return anfrage('POST', '/kalender/termine', body);
}

export function aendern(id: string, body: Record<string, unknown>): Promise<Ergebnis> {
  return anfrage('PATCH', termin(id), body);
}

export function loeschen(id: string, body: Record<string, unknown>): Promise<Ergebnis> {
  return anfrage('DELETE', termin(id), body);
}

export function videoraum(): Promise<Ergebnis> {
  return anfrage('POST', '/kalender/videoraum', {});
}

export function kontakte(q: string): Promise<Ergebnis> {
  return anfrage('GET', `/kalender/kontakte.json?${new URLSearchParams({ q }).toString()}`);
}
