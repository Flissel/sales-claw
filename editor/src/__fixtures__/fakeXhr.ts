// Nachgebautes XMLHttpRequest: merkt sich den letzten Aufruf, der Test spielt Fortschritt und Ende.
export class FakeXhr {
  static letzte: FakeXhr | null = null;
  methode = '';
  url = '';
  kopf: Record<string, string> = {};
  body: unknown = null;
  withCredentials = false;
  status = 0;
  responseText = '';
  abgebrochen = false;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() {
    FakeXhr.letzte = this;
  }
  open(m: string, u: string) {
    this.methode = m;
    this.url = u;
  }
  setRequestHeader(k: string, v: string) {
    this.kopf[k] = v;
  }
  send(b: unknown) {
    this.body = b;
  }
  abort() {
    this.abgebrochen = true;
    this.onabort?.();
  }
  fortschritt(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  ende(status: number, body: unknown) {
    this.status = status;
    this.responseText = typeof body === 'string' ? body : JSON.stringify(body);
    this.onload?.();
  }
}
