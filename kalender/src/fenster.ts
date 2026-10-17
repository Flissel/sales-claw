// Fenster zum Anlegen, Bearbeiten und Ansehen eines Termins: ein schlichter
// <dialog> mit Formular, ohne UI-Bibliothek. Oben die reinen Helfer (getestet),
// unten der DOM-Teil.
import type { EventApi } from '@fullcalendar/core';

import { isoMitOffset, lokalZuIso, NICHT_IM_HANDY } from './abbild';
import { type Konflikt, type Oberflaeche, schreiben, UNVOLLSTAENDIG } from './ablauf';
import * as api from './api';

// --- reine Helfer --------------------------------------------------------------

export interface Werte {
  art: 'eigen' | 'kunde';
  titel: string;
  datum: string; // YYYY-MM-DD
  zeit: string; // HH:MM
  dauer: number;
  ort: string;
  notiz: string;
  lead_id: string;
  einladung: boolean;
}

export interface Alt {
  art: 'eigen' | 'kunde';
  titel: string;
  beginn: string;
  dauer: number;
  ort: string;
  notiz?: string;
  geaendert_am?: string;
}

export const DAUER = { eigen: [5, 1440], kunde: [15, 480] } as const;

export function pruefen(w: Werte): string | null {
  if (!w.titel.trim()) return w.art === 'kunde' ? 'Bitte ein Thema angeben.' : 'Bitte einen Titel angeben.';
  if (w.titel.length > 200) return 'Titel/Thema höchstens 200 Zeichen.';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(w.datum) || !/^\d{2}:\d{2}$/.test(w.zeit)) return 'Bitte Datum und Uhrzeit angeben.';
  const [min, max] = DAUER[w.art];
  if (!Number.isInteger(w.dauer) || w.dauer < min || w.dauer > max) return `Dauer muss ${min}–${max} Minuten sein.`;
  if (w.ort.length > 200) return 'Ort höchstens 200 Zeichen.';
  if (w.art === 'eigen' && w.notiz.length > 2000) return 'Notiz höchstens 2000 Zeichen.';
  if (w.art === 'kunde' && !w.lead_id.trim()) return 'Bitte einen Kontakt wählen.';
  return null;
}

export function koerperAnlegen(w: Werte): Record<string, unknown> {
  const beginn = lokalZuIso(w.datum, w.zeit);
  if (w.art === 'eigen') {
    return { art: 'eigen', titel: w.titel.trim(), beginn, dauer_minuten: w.dauer, ort: w.ort, notiz: w.notiz };
  }
  return {
    art: 'kunde', lead_id: w.lead_id.trim(), thema: w.titel.trim(), beginn, dauer_minuten: w.dauer,
    ort: w.ort, einladung: w.einladung,
  };
}

/** Eigen: alle Felder mit Stempel. Kunde: nur Geaendertes, nie Notiz, leerer Ort = unveraendert.
 *  -> null, wenn sich bei einem Kundentermin nichts geaendert hat. */
export function koerperAendern(w: Werte, alt: Alt): Record<string, unknown> | null {
  const beginn = lokalZuIso(w.datum, w.zeit);
  if (alt.art === 'eigen') {
    return {
      titel: w.titel.trim(), beginn, dauer_minuten: w.dauer, ort: w.ort, notiz: w.notiz,
      geaendert_am: alt.geaendert_am,
    };
  }
  const body: Record<string, unknown> = {};
  if (w.titel.trim() !== alt.titel) body.titel = w.titel.trim();
  if (Date.parse(beginn) !== Date.parse(alt.beginn)) body.beginn = beginn;
  if (w.dauer !== alt.dauer) body.dauer_minuten = w.dauer;
  if (w.ort.trim() && w.ort !== alt.ort) body.ort = w.ort;
  return Object.keys(body).length ? body : null;
}

/** Absenden nur einmal gleichzeitig: Knopf gesperrt, weitere Aufrufe tun nichts. */
export function mitSperre<T>(knopf: { disabled: boolean }, fn: () => Promise<T>): () => Promise<T | undefined> {
  let laeuft = false;
  return async () => {
    if (laeuft) return undefined;
    laeuft = true;
    knopf.disabled = true;
    try {
      return await fn();
    } finally {
      laeuft = false;
      knopf.disabled = false;
    }
  };
}

// --- DOM ------------------------------------------------------------------------

export interface Kontext {
  darfSchreiben: boolean;
  rolle: string;
  freigabenUrl: string;
  ui: Oberflaeche;
}

type Kind = Node | string | null | undefined | false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attr: Record<string, string> = {},
  ...kinder: Kind[]
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attr)) e.setAttribute(k, v);
  for (const k of kinder) if (k) e.append(k);
  return e;
}

function anfuegen(ziel: HTMLElement, ...kinder: Kind[]): void {
  for (const k of kinder) if (k) ziel.append(k);
}

function feld(beschriftung: string, eingabe: HTMLElement, ...mehr: Kind[]): HTMLElement {
  return el('label', { class: 'vk-feld' }, el('span', {}, beschriftung), eingabe, ...mehr);
}

function neuesFenster(titel: string): { fenster: HTMLDialogElement; inhalt: HTMLElement } {
  const fenster = el('dialog', { class: 'vk-fenster' });
  const inhalt = el('div', { class: 'vk-inhalt' });
  fenster.append(el('h2', {}, titel), inhalt);
  fenster.addEventListener('close', () => fenster.remove());
  document.body.append(fenster);
  return { fenster, inhalt };
}

const zwei = (n: number) => String(n).padStart(2, '0');
const datumVon = (d: Date) => `${d.getFullYear()}-${zwei(d.getMonth() + 1)}-${zwei(d.getDate())}`;
const zeitVon = (d: Date) => `${zwei(d.getHours())}:${zwei(d.getMinutes())}`;

export function zeitText(beginn: Date | string, ende?: Date | string | null): string {
  const b = typeof beginn === 'string' ? new Date(beginn) : beginn;
  const tag = b.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
  const von = b.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  if (!ende) return `${tag}, ${von}`;
  const e = typeof ende === 'string' ? new Date(ende) : ende;
  return `${tag}, ${von}–${e.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}`;
}

/** Konfliktfenster: "trotzdem speichern" -> true, "abbrechen"/Escape -> false. */
export function konfliktFragen(konflikte: Konflikt[], unvollstaendig: boolean): Promise<boolean> {
  return new Promise((fertig) => {
    const { fenster, inhalt } = neuesFenster('Terminkonflikt');
    const liste = el('ul', { class: 'vk-konflikte' });
    for (const k of konflikte) liste.append(el('li', {}, `${zeitText(k.beginn, k.ende)} · ${k.titel} (${k.art})`));
    const trotzdem = el('button', { type: 'button', class: 'vk-haupt' }, 'trotzdem speichern');
    const abbrechen = el('button', { type: 'button' }, 'abbrechen');
    let antwort = false;
    trotzdem.onclick = () => { antwort = true; fenster.close(); };
    abbrechen.onclick = () => fenster.close();
    fenster.addEventListener('close', () => fertig(antwort));
    anfuegen(inhalt,
      el('p', {}, 'Zu dieser Zeit liegt schon etwas:'), liste,
      unvollstaendig ? el('p', { class: 'vk-warnung' }, `${UNVOLLSTAENDIG} – nicht alle Kalender waren abrufbar.`) : null,
      el('div', { class: 'vk-knoepfe' }, abbrechen, trotzdem),
    );
    fenster.showModal();
  });
}

/** Nur ansehen: fremde Termine (Handy, Kollegen) und alles fuer Rollen ohne Schreibrecht. */
export function detailsOeffnen(ev: EventApi, ctx: Kontext): void {
  const p = ev.extendedProps;
  const { fenster, inhalt } = neuesFenster(String(p.art === 'kunde' ? p.thema : ev.title));
  const zeile = (k: string, v: unknown) => (v ? el('div', { class: 'vk-zeile' }, el('b', {}, `${k}: `), String(v)) : null);
  const art = { kunde: 'Kundentermin', eigen: 'Eigener Termin', kollege: 'Kollegen-Kalender', handy: 'Handy-Kalender' }[
    String(p.art)] ?? '';
  anfuegen(inhalt,
    zeile('Art', art), zeile('Zeit', ev.start ? zeitText(ev.start, ev.end) : ''), zeile('Kontakt', p.kontakt),
    zeile('Kalender', p.quelle), zeile('Ort', p.ort), zeile('Notiz', p.notiz),
    p.handy_fehlt ? el('p', { class: 'vk-warnung' }, NICHT_IM_HANDY) : null,
    p.art === 'kunde' && !p.bearbeitbar && ctx.darfSchreiben
      ? el('p', { class: 'vk-hinweis' }, 'Ohne Kontakt – hier nicht bearbeitbar.') : null,
    p.lead_id && ctx.rolle !== 'kalender'
      ? el('p', {}, el('a', { href: `/kontakte/${encodeURIComponent(String(p.lead_id))}` }, 'Zum Kontakt')) : null,
  );
  const zu = el('button', { type: 'button' }, 'Schließen');
  zu.onclick = () => fenster.close();
  inhalt.append(el('div', { class: 'vk-knoepfe' }, zu));
  fenster.showModal();
}

interface Vorgabe {
  modus: 'neu' | 'bearbeiten';
  ev?: EventApi;
  start: Date;
  dauer: number;
  art?: 'eigen' | 'kunde';
  kunde?: { lead_id: string; name: string };
}

/** Startart und vorgewaehlter Kontakt des Formulars (rein, ohne DOM). */
export function startWerte(
  v: Partial<Vorgabe>, p: Record<string, unknown>,
): { art: 'eigen' | 'kunde'; leadId: string; gewaehlt: string } {
  const bearbeiten = v.modus === 'bearbeiten';
  const art = bearbeiten ? (p.art === 'kunde' ? 'kunde' : 'eigen') : (v.art ?? 'eigen');
  return {
    art,
    leadId: v.kunde && !bearbeiten ? v.kunde.lead_id : String(p.lead_id ?? ''),
    gewaehlt: v.kunde && !bearbeiten ? v.kunde.name : '',
  };
}

function formular(v: Vorgabe, ctx: Kontext): void {
  const p = v.ev?.extendedProps ?? {};
  const bearbeiten = v.modus === 'bearbeiten';
  const vorbelegt = startWerte(v, p);
  let art: 'eigen' | 'kunde' = vorbelegt.art;
  const { fenster, inhalt } = neuesFenster(bearbeiten ? 'Termin bearbeiten' : 'Neuer Termin');
  const form = el('form', { class: 'vk-formular', novalidate: '' });

  // Art
  const artEigen = el('input', { type: 'radio', name: 'vk-art', value: 'eigen' });
  const artKunde = el('input', { type: 'radio', name: 'vk-art', value: 'kunde' });
  artEigen.checked = art === 'eigen';
  artKunde.checked = art === 'kunde';
  const artWahl = el('fieldset', { class: 'vk-art' }, el('legend', {}, 'Art'),
    el('label', {}, artEigen, ' eigener Termin'), el('label', {}, artKunde, ' Kundentermin'));

  // Kontakt (nur Kunde, nur neu)
  // Je Fenster neu pruefen: ein einzelnes 403/404 (z. B. Sitzung) schaltet die Suche
  // nur fuer dieses Fenster auf das Lead-ID-Feld um.
  let kontaktSucheVorhanden = true;
  let leadId = vorbelegt.leadId;
  const gewaehlt = el('div', { class: 'vk-gewaehlt' });
  const suche = el('input', { type: 'search', placeholder: 'Name suchen …', autocomplete: 'off' });
  const treffer = el('ul', { class: 'vk-treffer' });
  const leadFeld = el('input', { type: 'text', placeholder: 'Lead-ID' });
  const kontaktBereich = el('div', { class: 'vk-kontakt' });
  const sucheZeigen = () => {
    kontaktBereich.replaceChildren(kontaktSucheVorhanden
      ? feld('Kontakt', suche, treffer, gewaehlt)
      : feld('Lead-ID', leadFeld, el('small', {}, 'Die Kontaktsuche ist nicht verfügbar – Lead-ID von der Kontaktseite eintragen.')));
  };
  let suchUhr = 0;
  suche.addEventListener('input', () => {
    window.clearTimeout(suchUhr);
    suchUhr = window.setTimeout(async () => {
      const q = suche.value.trim();
      if (!q) { treffer.replaceChildren(); return; }
      const r = await api.kontakte(q);
      if (r.status === 403 || r.status === 404) { kontaktSucheVorhanden = false; sucheZeigen(); return; }
      if (!r.ok) { treffer.replaceChildren(el('li', {}, r.daten.grund ?? 'Suche fehlgeschlagen')); return; }
      const liste = Array.isArray(r.daten.kontakte) ? (r.daten.kontakte as { lead_id: string; name: string }[]) : [];
      treffer.replaceChildren(...(liste.length ? liste.map((k) => {
        const b = el('button', { type: 'button' }, k.name);
        b.onclick = () => {
          leadId = k.lead_id;
          gewaehlt.textContent = `Gewählt: ${k.name}`;
          treffer.replaceChildren();
          suche.value = k.name;
        };
        return el('li', {}, b);
      }) : [el('li', {}, 'Kein Treffer')]));
    }, 250);
  });
  if (vorbelegt.gewaehlt) {
    gewaehlt.textContent = `Gewählt: ${vorbelegt.gewaehlt}`;
    suche.value = vorbelegt.gewaehlt;
  }
  sucheZeigen();

  // Felder
  const titel = el('input', { type: 'text', maxlength: '200', required: '' });
  titel.value = bearbeiten ? String(p.thema ?? v.ev?.title ?? '') : '';
  const titelBeschriftung = el('span', {});
  const datum = el('input', { type: 'date', required: '' });
  datum.value = datumVon(v.start);
  const zeit = el('input', { type: 'time', step: '300', required: '' });
  zeit.value = zeitVon(v.start);
  const dauer = el('input', { type: 'number', min: '5', max: '1440', step: '5', required: '' });
  dauer.value = String(v.dauer);
  const ort = el('input', { type: 'text', maxlength: '200' });
  ort.value = String(p.ort ?? '');
  const raumKnopf = el('button', { type: 'button' }, 'Videoraum');
  const ortHinweis = el('small', {}, 'Leer gelassen bleibt der bisherige Ort.');
  const notiz = el('textarea', { rows: '3', maxlength: '2000' });
  notiz.value = String(p.notiz ?? '');
  const einladung = el('input', { type: 'checkbox' });
  const fehler = el('p', { class: 'vk-fehler', role: 'alert' });

  const notizFeld = feld('Notiz', notiz);
  const einladungFeld = el('label', { class: 'vk-feld vk-haken' }, einladung, ' Einladung als Entwurf anlegen');
  const kundenHinweis = el('p', { class: 'vk-hinweis' },
    'Änderungen und Absagen legen einen Entwurf an den Kunden an – versendet wird erst nach Freigabe.');
  const titelFeld = el('label', { class: 'vk-feld' }, titelBeschriftung, titel);
  const ortFeld = feld('Ort', el('div', { class: 'vk-reihe' }, ort, raumKnopf), bearbeiten && art === 'kunde' ? ortHinweis : null);

  const sichtbar = (e: HTMLElement, ja: boolean) => { e.hidden = !ja; };
  const umschalten = () => {
    art = artKunde.checked ? 'kunde' : 'eigen';
    titelBeschriftung.textContent = art === 'kunde' ? 'Thema' : 'Titel';
    sichtbar(kontaktBereich, art === 'kunde' && !bearbeiten);
    sichtbar(notizFeld, art === 'eigen');
    sichtbar(einladungFeld, art === 'kunde' && !bearbeiten);
    sichtbar(kundenHinweis, art === 'kunde' && bearbeiten);
    const [min, max] = DAUER[art];
    dauer.min = String(min);
    dauer.max = String(max);
  };
  artEigen.onchange = umschalten;
  artKunde.onchange = umschalten;

  const werte = (): Werte => ({
    art, titel: titel.value, datum: datum.value, zeit: zeit.value, dauer: Number(dauer.value),
    ort: ort.value, notiz: art === 'eigen' ? notiz.value : '',
    lead_id: kontaktSucheVorhanden || bearbeiten ? leadId : leadFeld.value, einladung: einladung.checked,
  });

  raumKnopf.onclick = mitSperre(raumKnopf, async () => {
    const r = await api.videoraum();
    if (r.ok && typeof r.daten.link === 'string' && r.daten.link) ort.value = r.daten.link;
    fehler.textContent = r.ok ? String(r.daten.hinweis ?? '') : (r.daten.grund ?? 'Kein Videoraum');
  });

  // Knoepfe; eine Sperre fuer alle schreibenden Knoepfe des Fensters.
  const speichern = el('button', { type: 'submit', class: 'vk-haupt' }, 'Speichern');
  const abbrechen = el('button', { type: 'button' }, 'Abbrechen');
  abbrechen.onclick = () => fenster.close();
  const loeschKnopf = el('button', { type: 'button', class: 'vk-gefahr' }, art === 'kunde' ? 'Absagen' : 'Löschen');
  const grund = el('input', { type: 'text', maxlength: '200', placeholder: 'Grund der Absage (Pflicht)' });
  const gruppe = {
    get disabled() { return speichern.disabled; },
    set disabled(ja: boolean) { speichern.disabled = ja; loeschKnopf.disabled = ja; },
  };

  const absenden = mitSperre(gruppe, async () => {
    const w = werte();
    const f = pruefen(w);
    if (f) { fehler.textContent = f; return; }
    fehler.textContent = '';
    let ok: boolean;
    if (!bearbeiten) {
      const body = koerperAnlegen(w);
      ok = await schreiben((trotzdem) => api.anlegen({ ...body, trotzdem }), ctx.ui, ctx.freigabenUrl);
    } else {
      const ev = v.ev as EventApi;
      const body = koerperAendern(w, {
        art, titel: String(p.thema ?? ''), beginn: ev.start ? isoMitOffset(ev.start) : '',
        dauer: v.dauer, ort: String(p.ort ?? ''), notiz: String(p.notiz ?? ''), geaendert_am: p.geaendert_am as string | undefined,
      });
      if (!body) { fenster.close(); return; }
      ok = await schreiben((trotzdem) => api.aendern(ev.id, { ...body, trotzdem }), ctx.ui, ctx.freigabenUrl);
    }
    if (ok) fenster.close();
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); void absenden(); });

  loeschKnopf.onclick = mitSperre(gruppe, async () => {
    const ev = v.ev as EventApi;
    if (art === 'kunde') {
      if (!grund.value.trim()) { fehler.textContent = 'Für eine Absage braucht es einen Grund.'; grund.focus(); return; }
      if (!window.confirm('Termin absagen? Ein Entwurf an den Kunden wird angelegt.')) return;
    } else if (!window.confirm('Termin löschen?')) {
      return;
    }
    const ok = await schreiben(
      () => api.loeschen(ev.id, art === 'kunde' ? { grund: grund.value.trim() } : {}), ctx.ui, ctx.freigabenUrl);
    if (ok) fenster.close();
  });

  anfuegen(form,
    bearbeiten ? null : artWahl,
    kontaktBereich, titelFeld,
    el('div', { class: 'vk-reihe' }, feld('Datum', datum), feld('Uhrzeit', zeit), feld('Dauer (Min.)', dauer)),
    ortFeld, notizFeld, einladungFeld, kundenHinweis,
    p.handy_fehlt ? el('p', { class: 'vk-warnung' }, NICHT_IM_HANDY) : null,
    fehler,
    el('div', { class: 'vk-knoepfe' }, abbrechen, speichern),
  );
  if (bearbeiten) {
    const weg = el('div', { class: 'vk-loeschen' },
      art === 'kunde' ? grund : null, loeschKnopf,
      art === 'kunde' && p.lead_id
        ? el('a', { href: `/kontakte/${encodeURIComponent(String(p.lead_id))}` }, 'Zum Kontakt') : null);
    form.append(weg);
  }
  inhalt.append(form);
  umschalten();
  fenster.showModal();
  titel.focus();
}

export function anlegenOeffnen(
  start: Date, ende: Date | null, ganztags: boolean, ctx: Kontext, vorgabe: Partial<Vorgabe> = {},
): void {
  let beginn = start;
  let dauer = ende ? Math.round((ende.getTime() - start.getTime()) / 60000) : 60;
  if (ganztags) {
    beginn = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 9, 0);
    dauer = 60;
  }
  formular({ ...vorgabe, modus: 'neu', start: beginn, dauer: Math.max(15, Math.min(dauer, 480)) }, ctx);
}

export function bearbeitenOeffnen(ev: EventApi, ctx: Kontext): void {
  if (!ev.start) return;
  const dauer = ev.end ? Math.round((ev.end.getTime() - ev.start.getTime()) / 60000) : 60;
  formular({ modus: 'bearbeiten', ev, start: ev.start, dauer }, ctx);
}

