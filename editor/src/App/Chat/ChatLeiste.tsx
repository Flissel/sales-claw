// Chat mit dem Gestaltungs-Agenten (Spec 2026-10-02 §4): im Newsletter-Editor in der rechten
// Seitenleiste, im Gestaltungsfenster unter den Eigenschaften. Aussehen aus gestaltungStil:
// Betreiber rechts auf der Akzentflaeche, Agent links auf der Panelflaeche, Eingabe unten fest.
// Waehrend der Agent arbeitet: drei Punkte im 150-ms-Takt; das Dokument sperrt der Aufrufer
// mit der SperrSchicht (Sperre.tsx).
// Live-Lauf (Spec 2026-10-02-newsletter-agent-live §2.3, §3): Schritt-Zeile mit ruhiger
// Fortschritts-Linie, die Eingabe bleibt offen ("Vormerken"), die vorgemerkte Nachricht steht als
// eigene Karte da, "Stopp" fragt im StoppDialog nach.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  ArrowUpwardRounded,
  AutoAwesomeRounded,
  ErrorOutlineRounded,
  ExpandMoreRounded,
  IosShareRounded,
  PhotoLibraryOutlined,
  ScheduleRounded,
  StopRounded,
  UndoRounded,
} from '@mui/icons-material';
import { Box, Button, ButtonBase, CircularProgress, IconButton, InputBase, ThemeProvider, Tooltip } from '@mui/material';

import { ChatEintrag, ChatKontext, ExportAuswahl, exportVorschlag, laufenderChat, rueckgaengigFuer, Vorgemerkt } from '../../chat';
import {
  chatAbschicken,
  chatRueckgaengig,
  chatVormerken,
  HINWEIS_OFFEN,
  pultStore,
  vormerkungLoeschenAuftrag,
  vormerkungStartenAuftrag,
} from '../../pultZustand';
import { FARBE, FOKUS, gestaltungThema, uebergang, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import { Punkte, useAgentArbeitet, useLiveZeile } from './Sperre';
import StoppDialog from './StoppDialog';

export const NACHRICHT_MAX = 2000;
const KOPF = 40;

const laeuftNoch = (e: ChatEintrag) => e.status === 'offen' || e.status === 'in_arbeit';

function Blase({ ich, fehler, children }: { ich: boolean; fehler?: boolean; children: React.ReactNode }) {
  return (
    <Box
      sx={{
        alignSelf: ich ? 'flex-end' : 'flex-start',
        maxWidth: '88%',
        px: 1.5,
        py: 1,
        borderRadius: ich ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
        bgcolor: ich ? FARBE.akzent : FARBE.panel,
        color: ich ? '#ffffff' : fehler ? FARBE.fehler : FARBE.text,
        border: ich ? 'none' : `1px solid ${FARBE.linie}`,
        fontSize: 13,
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap',
        overflowWrap: 'anywhere',
      }}
    >
      {children}
    </Box>
  );
}

const kleinerKnopf = { height: 24, px: 1, fontSize: 12, fontWeight: 500, color: FARBE.gedaempft, minWidth: 0, '&:hover': { color: FARBE.text, bgcolor: FARBE.hover } } as const;

// Laufender Auftrag: Punkte, Schritt-Zeile (blendet bei jedem Schritt sanft ein) und darunter eine
// ruhig wandernde Fortschritts-Linie - man sieht, dass er lebt, ohne dass es zappelt.
function LaufBlase({ text }: { text: string }) {
  return (
    <Box
      sx={{
        alignSelf: 'flex-start',
        position: 'relative',
        overflow: 'hidden',
        maxWidth: '88%',
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1.5,
        minHeight: 36,
        py: 0.75,
        borderRadius: '12px 12px 12px 4px',
        bgcolor: FARBE.panel,
        border: `1px solid ${FARBE.linie}`,
      }}
    >
      <Punkte />
      <Box
        key={text}
        component="span"
        sx={{
          fontSize: 12,
          lineHeight: 1.4,
          color: FARBE.text,
          fontVariantNumeric: 'tabular-nums',
          '@keyframes schrittAuf': { from: { opacity: 0, transform: 'translateY(3px)' }, to: { opacity: 1, transform: 'none' } },
          animation: 'schrittAuf 220ms cubic-bezier(0.2, 0, 0, 1)',
          '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
        }}
      >
        {text}
      </Box>
      <Box
        aria-hidden="true"
        sx={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: '2px',
          background: `linear-gradient(90deg, transparent 0%, ${FARBE.akzent} 50%, transparent 100%)`,
          backgroundSize: '50% 100%',
          backgroundRepeat: 'no-repeat',
          opacity: 0.7,
          '@keyframes schrittLinie': { from: { backgroundPosition: '-100% 0' }, to: { backgroundPosition: '200% 0' } },
          animation: 'schrittLinie 1.8s ease-in-out infinite',
          '@media (prefers-reduced-motion: reduce)': { animation: 'none', opacity: 0.35, backgroundSize: '100% 100%' },
        }}
      />
    </Box>
  );
}

// Die vorgemerkte Nachricht: waehrend des Laufs "startet danach", nach Fehler oder Stopp mit
// "Starten" / "Verwerfen" (sie startet dann nicht von selbst).
function VorgemerktKarte({
  v,
  laeuft,
  arbeitet,
  onBearbeiten,
}: {
  v: Vorgemerkt;
  laeuft: boolean;
  arbeitet: boolean;
  onBearbeiten: (text: string) => void;
}) {
  const [aktion, setAktion] = useState<'loeschen' | 'starten' | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const tun = async (art: 'loeschen' | 'starten') => {
    setAktion(art);
    setFehler(null);
    const grund = art === 'loeschen' ? await vormerkungLoeschenAuftrag() : await vormerkungStartenAuftrag();
    setAktion(null);
    if (grund) setFehler(grund);
  };
  const dreher = (art: 'loeschen' | 'starten') => (aktion === art ? <CircularProgress size={12} color="inherit" /> : undefined);
  return (
    <Box
      sx={{
        alignSelf: 'flex-end',
        maxWidth: '88%',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        px: 1.5,
        py: 1,
        borderRadius: '12px 12px 4px 12px',
        border: `1px dashed ${FARBE.akzent}`,
        bgcolor: 'rgba(91,140,255,0.08)',
        '@keyframes karteAuf': { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'none' } },
        animation: 'karteAuf 200ms cubic-bezier(0.2, 0, 0, 1)',
        '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, fontSize: 11, fontWeight: 600, color: FARBE.akzent, letterSpacing: 0.2 }}>
        <ScheduleRounded sx={{ fontSize: 13 }} />
        {laeuft ? 'Vorgemerkt · startet danach' : 'Vorgemerkt · noch nicht gestartet'}
      </Box>
      <Box sx={{ fontSize: 13, lineHeight: 1.5, color: FARBE.text, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{v.nachricht}</Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 0.5, mr: -0.75 }}>
        <Button size="small" disabled={aktion !== null} onClick={() => onBearbeiten(v.nachricht)} sx={kleinerKnopf}>
          Bearbeiten
        </Button>
        {laeuft ? (
          <Button size="small" disabled={aktion !== null} onClick={() => void tun('loeschen')} startIcon={dreher('loeschen')} sx={kleinerKnopf}>
            Löschen
          </Button>
        ) : (
          <>
            <Button size="small" disabled={aktion !== null} onClick={() => void tun('loeschen')} startIcon={dreher('loeschen')} sx={kleinerKnopf}>
              Verwerfen
            </Button>
            <Tooltip title={arbeitet ? 'Der Assistent arbeitet gerade' : ''}>
              <span>
                <Button
                  size="small"
                  disabled={aktion !== null || arbeitet}
                  onClick={() => void tun('starten')}
                  startIcon={dreher('starten')}
                  sx={{ ...kleinerKnopf, color: FARBE.akzent }}
                >
                  Starten
                </Button>
              </span>
            </Tooltip>
          </>
        )}
      </Box>
      {fehler && <Box sx={{ fontSize: 12, color: FARBE.fehler }}>{fehler}</Box>}
    </Box>
  );
}

type Aktionen = {
  rueckSperre: string | null;
  // Die eine Antwort, die sich rueckgaengig machen laesst (rueckgaengigFuer).
  rueckId: string | null;
  rueckLaeuft: string | null;
  rueckFehler: { id: string; grund: string } | null;
  onRueckgaengig: (id: string) => void;
  onExport: (v: ExportAuswahl) => void;
  // Schritt-Zeile des laufenden Chat-Auftrags (useLiveZeile).
  liveZeile: string | null;
};

function Eintrag({ e, a }: { e: ChatEintrag; a: Aktionen }) {
  if (e.art === 'export') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, fontSize: 12, color: e.status === 'fehler' ? FARBE.fehler : FARBE.gedaempft, textAlign: 'center', px: 2 }}>
        <PhotoLibraryOutlined sx={{ fontSize: 14, flexShrink: 0 }} />
        {laeuftNoch(e) ? (
          <>
            <span>Newsletter-Bilder werden am PC gerechnet</span>
            <Punkte />
          </>
        ) : (
          <span>{e.antwort || (e.status === 'fertig' ? 'Export fertig' : 'Export fehlgeschlagen')}</span>
        )}
      </Box>
    );
  }
  const vorschlag = e.status === 'fertig' ? exportVorschlag(e) : null;
  const mitFassung = e.art === 'chat' && e.status === 'fertig' && e.fassung_nachher !== null;
  const kannZurueck = mitFassung && a.rueckId === e.id;
  const sperre = a.rueckSperre;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {e.nachricht && <Blase ich>{e.nachricht}</Blase>}
      {laeuftNoch(e) ? (
        <LaufBlase text={a.liveZeile ?? (e.status === 'offen' ? 'Wartet auf den Assistenten …' : 'Agent denkt nach …')} />
      ) : (
        <Blase ich={false} fehler={e.status === 'fehler'}>
          {e.status === 'fehler' && <ErrorOutlineRounded sx={{ fontSize: 14, mr: 0.75, verticalAlign: '-2px' }} />}
          {e.antwort || (e.status === 'fehler' ? 'Das hat nicht geklappt.' : 'Erledigt.')}
          {e.hinweise.length > 0 && (
            <Box component="ul" sx={{ m: 0, mt: 1, pl: 2, color: FARBE.gedaempft, fontSize: 12, lineHeight: 1.5, '& li::marker': { color: FARBE.warnung } }}>
              {e.hinweise.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </Box>
          )}
        </Blase>
      )}
      {(mitFassung || vorschlag) && (
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5, mt: -0.5 }}>
          {e.fassung_nachher !== null && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, mr: 0.5, fontVariantNumeric: 'tabular-nums' }}>
              Fassung {e.fassung_nachher}
              {e.ergebnis.notiz ? ` · ${e.ergebnis.notiz}` : ''}
            </Box>
          )}
          {mitFassung && !kannZurueck && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, fontStyle: 'italic' }}>
              · Spätere Änderungen vorhanden
            </Box>
          )}
          {kannZurueck && (
            <Tooltip title={sperre ?? 'Legt die Fassung davor als neue Fassung an'}>
              <span>
                <Button
                  size="small"
                  disabled={sperre !== null || a.rueckLaeuft !== null}
                  onClick={() => a.onRueckgaengig(e.id)}
                  startIcon={a.rueckLaeuft === e.id ? <CircularProgress size={12} color="inherit" /> : <UndoRounded sx={{ fontSize: 14 }} />}
                  sx={kleinerKnopf}
                >
                  Rückgängig
                </Button>
              </span>
            </Tooltip>
          )}
          {vorschlag && (
            <Button size="small" onClick={() => a.onExport(vorschlag)} startIcon={<IosShareRounded sx={{ fontSize: 14 }} />} sx={{ ...kleinerKnopf, color: FARBE.akzent }}>
              Exportieren…
            </Button>
          )}
        </Box>
      )}
      {a.rueckFehler?.id === e.id && <Box sx={{ fontSize: 12, color: FARBE.fehler }}>{a.rueckFehler.grund}</Box>}
    </Box>
  );
}

export type ChatLeisteProps = {
  kontext: ChatKontext;
  // Grund, warum gerade nichts an den Agenten gehen kann (z. B. ungesicherte Flaeche).
  sperre?: string | null;
  // Hoehe des aufgeklappten Chats (Verlauf + Eingabe).
  hoehe: number | string;
  vorschlaege?: string[];
  onExport: (v: ExportAuswahl) => void;
};

export default function ChatLeiste({ kontext, sperre = null, hoehe, vorschlaege = [], onExport }: ChatLeisteProps) {
  const thema = useMemo(gestaltungThema, []);
  const chat = pultStore((p) => p.chat);
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const hinweisOffen = pultStore((p) => p.hinweisOffen);
  const basis = pultStore((p) => p.basis);
  const arbeitet = useAgentArbeitet();
  const liveZeile = useLiveZeile();
  // Waehrend eines Chat-Laufs: Vormerken statt Senden, Stopp in der Kopfzeile.
  const chatLauf = pultStore((p) => laufenderChat(p.chat) !== null);
  const stoppLaeuft = pultStore((p) => p.chat?.live?.stopp != null);
  const vorgemerkt = chat?.vorgemerkt ?? null;
  const [stoppOffen, setStoppOffen] = useState(false);
  const eingabe = useRef<HTMLTextAreaElement>(null);
  const [offen, setOffen] = useState(true);
  const [text, setText] = useState('');
  const [sendet, setSendet] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [rueckLaeuft, setRueckLaeuft] = useState<string | null>(null);
  const [rueckFehler, setRueckFehler] = useState<{ id: string; grund: string } | null>(null);
  const liste = useRef<HTMLDivElement>(null);
  const verlauf = chat?.verlauf ?? [];
  const letzter = verlauf[verlauf.length - 1];

  // Neues unten: beim Oeffnen, bei neuen Eintraegen und wenn eine Antwort kommt.
  useEffect(() => {
    const el = liste.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [offen, verlauf.length, letzter?.status, vorgemerkt?.id, vorgemerkt?.nachricht, liveZeile]);

  // Ein Export am PC sperrt weiter; ein Chat-Lauf nimmt die naechste Nachricht als Vormerkung.
  const sendSperre = sperre ?? (arbeitet && !chatLauf ? 'Der Assistent arbeitet gerade' : null);
  const kannSenden = text.trim() !== '' && sendSperre === null && !sendet;

  const senden = async () => {
    if (!kannSenden) return;
    setSendet(true);
    setFehler(null);
    const grund = chatLauf ? await chatVormerken(text.trim(), kontext) : await chatAbschicken(text.trim(), kontext);
    setSendet(false);
    if (grund) setFehler(grund);
    else setText('');
  };

  const aktionen: Aktionen = {
    rueckSperre:
      sperre ??
      (arbeitet
        ? 'Der Assistent arbeitet gerade'
        : hinweisOffen
          ? HINWEIS_OFFEN
          : ungespeichert
            ? 'Erst speichern – sonst gingen deine Änderungen verloren'
            : null),
    rueckId: rueckgaengigFuer(verlauf, basis),
    rueckLaeuft,
    rueckFehler,
    onRueckgaengig: async (id) => {
      setRueckLaeuft(id);
      setRueckFehler(null);
      const grund = await chatRueckgaengig(id);
      setRueckLaeuft(null);
      if (grund) setRueckFehler({ id, grund });
    },
    onExport,
    liveZeile,
  };

  const bearbeiten = (t: string) => {
    setText(t);
    eingabe.current?.focus();
  };

  return (
    <ThemeProvider theme={thema}>
      <Box sx={{ display: 'flex', flexDirection: 'column', bgcolor: FARBE.panel, color: FARBE.text, fontFamily: UI_SCHRIFT, minHeight: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        <ButtonBase
          onClick={() => setOffen((o) => !o)}
          aria-expanded={offen}
          sx={{ flex: 1, minWidth: 0, height: KOPF, px: 2, gap: 1, justifyContent: 'flex-start', fontFamily: UI_SCHRIFT, transition: uebergang('background-color'), '&:hover': { bgcolor: FARBE.hover }, '&.Mui-focusVisible': FOKUS }}
        >
          <AutoAwesomeRounded sx={{ fontSize: 16, color: FARBE.akzent }} />
          <Box component="span" sx={{ fontSize: 13, fontWeight: 600 }}>
            Assistent
          </Box>
          <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, fontSize: 12, color: FARBE.gedaempft, ml: 0.5 }}>
            <Box component="span" sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: arbeitet ? FARBE.akzent : FARBE.linie, transition: uebergang('background-color') }} />
            {arbeitet ? 'arbeitet' : 'bereit'}
          </Box>
          <ExpandMoreRounded sx={{ ml: 'auto', fontSize: 18, color: FARBE.gedaempft, transform: offen ? 'none' : 'rotate(180deg)', transition: uebergang('transform') }} />
        </ButtonBase>
        {chatLauf && (
          <Tooltip title={stoppLaeuft ? 'Wird gestoppt …' : 'Den Assistenten anhalten'}>
            <span>
              <Button
                size="small"
                disabled={stoppLaeuft}
                onClick={() => setStoppOffen(true)}
                startIcon={<StopRounded sx={{ fontSize: 14 }} />}
                sx={{ mr: 1, height: 26, px: 1.25, fontSize: 12, fontWeight: 600, color: FARBE.text, border: `1px solid ${FARBE.linie}`, borderRadius: '13px', '&:hover': { bgcolor: FARBE.hover, borderColor: FARBE.gedaempft }, '&.Mui-disabled': { color: FARBE.gedaempft } }}
              >
                {stoppLaeuft ? 'Stoppt …' : 'Stopp'}
              </Button>
            </span>
          </Tooltip>
        )}
        </Box>
        <StoppDialog offen={stoppOffen && chatLauf} onClose={() => setStoppOffen(false)} />

        {offen && (
          <Box sx={{ height: hoehe, display: 'flex', flexDirection: 'column', minHeight: 0, borderTop: `1px solid ${FARBE.linie}` }}>
            <Box ref={liste} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', bgcolor: FARBE.geruest, p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {verlauf.length === 0 ? (
                <Box sx={{ m: 'auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5, maxWidth: 260 }}>
                  <AutoAwesomeRounded sx={{ fontSize: 24, color: FARBE.akzent }} />
                  <Box sx={{ fontSize: 13, color: FARBE.gedaempft, lineHeight: 1.5 }}>Sag dem Assistenten, was er gestalten oder ändern soll.</Box>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 1 }}>
                    {vorschlaege.map((v) => (
                      <ButtonBase
                        key={v}
                        onClick={() => setText(v)}
                        sx={{ px: 1.25, height: 28, borderRadius: '14px', border: `1px solid ${FARBE.linie}`, fontSize: 12, color: FARBE.text, fontFamily: UI_SCHRIFT, transition: uebergang('background-color', 'border-color'), '&:hover': { bgcolor: FARBE.hover, borderColor: FARBE.gedaempft }, '&.Mui-focusVisible': FOKUS }}
                      >
                        {v}
                      </ButtonBase>
                    ))}
                  </Box>
                </Box>
              ) : (
                verlauf.map((e) => <Eintrag key={e.id} e={e} a={aktionen} />)
              )}
              {vorgemerkt && <VorgemerktKarte v={vorgemerkt} laeuft={chatLauf} arbeitet={arbeitet !== null} onBearbeiten={bearbeiten} />}
            </Box>

            <Box sx={{ flexShrink: 0, p: 1, borderTop: `1px solid ${FARBE.linie}` }}>
              {(fehler || sperre) && (
                <Box sx={{ display: 'flex', gap: 0.75, px: 0.5, pb: 1, fontSize: 12, lineHeight: 1.4, color: fehler ? FARBE.fehler : FARBE.gedaempft }}>
                  {fehler && <ErrorOutlineRounded sx={{ fontSize: 14, mt: '1px' }} />}
                  <span>{fehler ?? sperre}</span>
                </Box>
              )}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'flex-end',
                  gap: 1,
                  pl: 1.5,
                  pr: 0.5,
                  py: 0.5,
                  borderRadius: '8px',
                  bgcolor: FARBE.feld,
                  border: '1px solid transparent',
                  transition: uebergang('border-color'),
                  '&:focus-within': { borderColor: FARBE.akzent },
                }}
              >
                <InputBase
                  multiline
                  maxRows={6}
                  value={text}
                  inputRef={eingabe}
                  placeholder={chatLauf ? (vorgemerkt ? 'Vormerkung ersetzen …' : 'Nächste Nachricht vormerken …') : arbeitet ? 'Der Assistent arbeitet …' : 'Nachricht an den Assistenten'}
                  onChange={(ev) => setText(ev.target.value.slice(0, NACHRICHT_MAX))}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter' && !ev.shiftKey && !ev.nativeEvent.isComposing) {
                      ev.preventDefault();
                      void senden();
                    }
                  }}
                  inputProps={{ 'aria-label': 'Nachricht an den Assistenten', maxLength: NACHRICHT_MAX }}
                  sx={{ flex: 1, py: 0.5, fontSize: 13, lineHeight: 1.5, color: FARBE.text, '& textarea::placeholder': { color: FARBE.gedaempft, opacity: 1 } }}
                />
                {chatLauf ? (
                  <Tooltip title={sendSperre ?? (vorgemerkt ? 'Ersetzt die vorgemerkte Nachricht' : 'Startet, sobald der Assistent fertig ist')}>
                    <span>
                      <Button
                        size="small"
                        disabled={!kannSenden}
                        onClick={() => void senden()}
                        startIcon={sendet ? <CircularProgress size={12} color="inherit" /> : <ScheduleRounded sx={{ fontSize: 14 }} />}
                        sx={{
                          height: 28,
                          mb: '2px',
                          px: 1.25,
                          fontSize: 12,
                          fontWeight: 600,
                          borderRadius: '14px',
                          bgcolor: FARBE.akzent,
                          color: '#ffffff',
                          '&:hover': { bgcolor: '#4a7bf0' },
                          '&.Mui-disabled': { bgcolor: FARBE.linie, color: FARBE.gedaempft },
                        }}
                      >
                        Vormerken
                      </Button>
                    </span>
                  </Tooltip>
                ) : (
                <Tooltip title={sendSperre ?? 'Senden (Enter)'}>
                  <span>
                    <IconButton
                      aria-label="Senden"
                      disabled={!kannSenden}
                      onClick={() => void senden()}
                      sx={{
                        width: 28,
                        height: 28,
                        mb: '2px',
                        bgcolor: FARBE.akzent,
                        color: '#ffffff',
                        '&:hover': { bgcolor: '#4a7bf0', color: '#ffffff' },
                        '&.Mui-disabled': { bgcolor: FARBE.linie, color: FARBE.gedaempft },
                      }}
                    >
                      {sendet ? <CircularProgress size={14} color="inherit" /> : <ArrowUpwardRounded sx={{ fontSize: 16 }} />}
                    </IconButton>
                  </span>
                </Tooltip>
                )}
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', px: 0.5, pt: 0.5, fontSize: 11, color: FARBE.gedaempft }}>
                <span>{chatLauf ? 'Enter vormerken' : 'Enter senden'} · Shift+Enter neue Zeile</span>
                {text.length > NACHRICHT_MAX - 200 && <span style={{ fontVariantNumeric: 'tabular-nums' }}>{text.length} / {NACHRICHT_MAX}</span>}
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  );
}
