// Chat mit dem Gestaltungs-Agenten (Spec 2026-10-02 §4): im Newsletter-Editor in der rechten
// Seitenleiste, im Gestaltungsfenster unter den Eigenschaften. Aussehen aus gestaltungStil:
// Betreiber rechts auf der Akzentflaeche, Agent links auf der Panelflaeche, Eingabe unten fest.
// Waehrend der Agent arbeitet: drei Punkte im 150-ms-Takt; das Dokument sperrt der Aufrufer
// mit der SperrSchicht (Sperre.tsx).
import React, { useEffect, useMemo, useRef, useState } from 'react';

import {
  ArrowUpwardRounded,
  AutoAwesomeRounded,
  ErrorOutlineRounded,
  ExpandMoreRounded,
  IosShareRounded,
  PhotoLibraryOutlined,
  UndoRounded,
} from '@mui/icons-material';
import { Box, Button, ButtonBase, CircularProgress, IconButton, InputBase, ThemeProvider, Tooltip } from '@mui/material';

import { ChatEintrag, ChatKontext, ExportAuswahl, exportVorschlag } from '../../chat';
import { chatAbschicken, chatRueckgaengig, pultStore } from '../../pultZustand';
import { FARBE, FOKUS, gestaltungThema, uebergang, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import { Punkte, useAgentArbeitet } from './Sperre';

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

type Aktionen = {
  rueckSperre: string | null;
  rueckLaeuft: string | null;
  rueckFehler: { id: string; grund: string } | null;
  onRueckgaengig: (id: string) => void;
  onExport: (v: ExportAuswahl) => void;
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
  const kannZurueck = e.status === 'fertig' && e.fassung_nachher !== null;
  const sperre = a.rueckSperre;
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {e.nachricht && <Blase ich>{e.nachricht}</Blase>}
      {laeuftNoch(e) ? (
        <Box sx={{ alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 1, px: 1.5, height: 36, borderRadius: '12px 12px 12px 4px', bgcolor: FARBE.panel, border: `1px solid ${FARBE.linie}` }}>
          <Punkte />
          <Box component="span" sx={{ fontSize: 12, color: FARBE.gedaempft }}>
            {e.status === 'offen' ? 'wartet auf den Assistenten' : 'arbeitet'}
          </Box>
        </Box>
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
      {(kannZurueck || vorschlag) && (
        <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.5, mt: -0.5 }}>
          {e.fassung_nachher !== null && (
            <Box component="span" sx={{ fontSize: 11, color: FARBE.gedaempft, mr: 0.5, fontVariantNumeric: 'tabular-nums' }}>
              Fassung {e.fassung_nachher}
              {e.ergebnis.notiz ? ` · ${e.ergebnis.notiz}` : ''}
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
  const arbeitet = useAgentArbeitet();
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
  }, [offen, verlauf.length, letzter?.status]);

  const sendSperre = sperre ?? (arbeitet ? 'Der Assistent arbeitet gerade' : null);
  const kannSenden = text.trim() !== '' && sendSperre === null && !sendet;

  const senden = async () => {
    if (!kannSenden) return;
    setSendet(true);
    setFehler(null);
    const grund = await chatAbschicken(text.trim(), kontext);
    setSendet(false);
    if (grund) setFehler(grund);
    else setText('');
  };

  const aktionen: Aktionen = {
    rueckSperre: sperre ?? (arbeitet ? 'Der Assistent arbeitet gerade' : ungespeichert ? 'Erst speichern – sonst gingen deine Änderungen verloren' : null),
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
  };

  return (
    <ThemeProvider theme={thema}>
      <Box sx={{ display: 'flex', flexDirection: 'column', bgcolor: FARBE.panel, color: FARBE.text, fontFamily: UI_SCHRIFT, minHeight: 0 }}>
        <ButtonBase
          onClick={() => setOffen((o) => !o)}
          aria-expanded={offen}
          sx={{ height: KOPF, px: 2, gap: 1, justifyContent: 'flex-start', flexShrink: 0, fontFamily: UI_SCHRIFT, transition: uebergang('background-color'), '&:hover': { bgcolor: FARBE.hover }, '&.Mui-focusVisible': FOKUS }}
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

        {offen && (
          <Box sx={{ height: hoehe, display: 'flex', flexDirection: 'column', minHeight: 0, borderTop: `1px solid ${FARBE.linie}` }}>
            <Box ref={liste} aria-live="polite" sx={{ flex: 1, minHeight: 0, overflowY: 'auto', bgcolor: FARBE.geruest, p: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
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
                  placeholder={arbeitet ? 'Der Assistent arbeitet …' : 'Nachricht an den Assistenten'}
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
              </Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', px: 0.5, pt: 0.5, fontSize: 11, color: FARBE.gedaempft }}>
                <span>Enter senden · Shift+Enter neue Zeile</span>
                {text.length > NACHRICHT_MAX - 200 && <span style={{ fontVariantNumeric: 'tabular-nums' }}>{text.length} / {NACHRICHT_MAX}</span>}
              </Box>
            </Box>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  );
}
