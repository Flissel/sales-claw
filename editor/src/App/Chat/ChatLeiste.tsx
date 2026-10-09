// Chat mit dem Gestaltungs-Agenten (Spec 2026-10-02 §4): im Newsletter-Editor in der rechten Seitenleiste, im
// Gestaltungsfenster unter den Eigenschaften. Aussehen aus gestaltungStil: Betreiber rechts auf der Akzentflaeche,
// Agent links auf der Panelflaeche, Eingabe unten fest.
// Mehrere Runden (Spec 2026-10-09-editor-parallele-runden §2): "Senden" immer; jede Runde ist ein eigener Eintrag
// (Runde.tsx) mit eigenem Stopp; der Stopp-Dialog gilt der Runde, fuer die er geoeffnet wurde.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ArrowUpwardRounded, AutoAwesomeRounded, ErrorOutlineRounded, ExpandMoreRounded, InfoOutlined } from '@mui/icons-material';
import { Box, ButtonBase, CircularProgress, IconButton, InputBase, ThemeProvider, Tooltip } from '@mui/material';

import { ChatEintrag, ChatKontext, ExportAuswahl, exportLaeuft, rueckgaengigFuer, stoppDialogOffen } from '../../chat';
import { altformSchluessel, kurzText, sendenErlaubt } from '../../chatKontext';
import { getDocument } from '../../documents/editor/EditorContext';
import { auswahlGewechselt, chatAbschicken, chatHinweisWeg, chatRueckgaengig, chatStoppen, chatTextSetzen, HINWEIS_OFFEN, pultStore } from '../../pultZustand';
import { FARBE, FOKUS, gestaltungThema, uebergang, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import { useAnhangAblage } from './AnhangAblage';
import { useGedankenSichtbar } from './Gedanken';
import KontextChips from './KontextChips';
import { Eintrag, RundenAktionen } from './Runde';
import { LIEGT_ZUR_FREIGABE, useAgentArbeitet, useNurLesen } from './Sperre';
import StoppDialog from './StoppDialog';

export const NACHRICHT_MAX = 2000;
export const EINGABE_ZEILEN = 8;
const KOPF = 40;

export type ChatLeisteProps = {
  kontext: ChatKontext;
  // Grund, warum gerade nichts an den Agenten gehen kann (z. B. ungesicherte Flaeche).
  sperre?: string | null;
  // Hoehe des aufgeklappten Chats (Verlauf + Eingabe).
  hoehe: number | string;
  vorschlaege?: string[];
  onExport: (v: ExportAuswahl) => void;
};

// Kurztext der Einzelauswahl (Block im Newsletter; im Gestaltungsfenster die Ebenen-id).
function auswahlKurz(k: ChatKontext): string {
  const id = typeof k.auswahl === 'string' ? k.auswahl : '';
  const block = k.fenster === 'newsletter' ? getDocument()[id] : undefined;
  return block ? kurzText(block as { type: string; data?: unknown }) : id;
}

export default function ChatLeiste({ kontext, sperre: sperreVon = null, hoehe, vorschlaege = [], onExport }: ChatLeisteProps) {
  const thema = useMemo(gestaltungThema, []);
  const gesendeteAuswahl = pultStore((p) => p.gesendeteAuswahl);
  const schluessel = altformSchluessel(kontext);
  useEffect(() => auswahlGewechselt(schluessel), [schluessel]);
  const altform = schluessel !== null && schluessel === gesendeteAuswahl ? { kurz: auswahlKurz(kontext) } : null;
  const chat = pultStore((p) => p.chat);
  const getrennt = pultStore((p) => p.chatGetrennt);
  const [gedankenSichtbar, gedankenUmschalten] = useGedankenSichtbar();
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const hinweisOffen = pultStore((p) => p.hinweisOffen);
  const text = pultStore((p) => p.chatText);
  const arbeitet = useAgentArbeitet();
  const nurLesen = useNurLesen();
  const sperre = sperreVon ?? (nurLesen ? LIEGT_ZUR_FREIGABE : null);
  // Stopp-Dialog: id der Runde, fuer die er geoeffnet wurde (null = zu). Endet sie, geht er zu.
  const [stoppFuer, setStoppFuer] = useState<string | null>(null);
  const dialogOffen = stoppDialogOffen(stoppFuer, chat);
  useEffect(() => {
    if (stoppFuer !== null && !dialogOffen) setStoppFuer(null);
  }, [stoppFuer, dialogOffen]);
  const eingabe = useRef<HTMLTextAreaElement>(null);
  const [offen, setOffen] = useState(true);
  const [sendet, setSendet] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [rueckLaeuft, setRueckLaeuft] = useState<string | null>(null);
  const [fehlerAn, setFehlerAn] = useState<{ id: string; grund: string } | null>(null);
  const liste = useRef<HTMLDivElement>(null);
  const hinweis = pultStore((p) => p.chatHinweis);
  const hochladenLaeuft = pultStore((p) => !sendenErlaubt(p.chatAnhaenge));
  const verlauf = chat?.verlauf ?? [];
  const letzter = verlauf[verlauf.length - 1];

  // Neues unten: beim Oeffnen, bei neuen Eintraegen und wenn eine Antwort kommt.
  useEffect(() => {
    const el = liste.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [offen, verlauf.length, letzter?.status, letzter?.schritt_nr]);

  // Mehrere Runden duerfen laufen; nur ein Newsletter-Export am PC sperrt das Senden.
  const sendSperre =
    sperre ?? (exportLaeuft(chat) ? 'Der Assistent arbeitet gerade' : hochladenLaeuft ? 'Erst warten, bis die Anhänge hochgeladen sind' : null);
  const kannSenden = text.trim() !== '' && sendSperre === null && !sendet;

  const { ablage, ablageFlaeche, bueroklammer, beimEinfuegen } = useAnhangAblage({ onGrund: setFehler, onAngehaengt: () => setOffen(true) });

  const senden = async () => {
    if (!kannSenden) return;
    setSendet(true);
    setFehler(null);
    const grund = await chatAbschicken(text.trim(), kontext);
    setSendet(false);
    if (grund) setFehler(grund);
    else chatTextSetzen('');
  };

  const aktionen: RundenAktionen = {
    rueckSperre:
      sperre ??
      (arbeitet ? 'Der Assistent arbeitet gerade' : hinweisOffen ? HINWEIS_OFFEN : ungespeichert ? 'Erst speichern – sonst gingen deine Änderungen verloren' : null),
    rueckId: rueckgaengigFuer(verlauf, chat?.neueste ?? null),
    rueckLaeuft,
    fehlerAn,
    onRueckgaengig: async (id) => {
      setRueckLaeuft(id);
      setFehlerAn(null);
      const grund = await chatRueckgaengig(id);
      setRueckLaeuft(null);
      if (grund) setFehlerAn({ id, grund });
    },
    onExport,
    onStopp: (e: ChatEintrag) => {
      if (e.status !== 'wartet') {
        setStoppFuer(e.id);
        return;
      }
      setFehlerAn(null);
      void chatStoppen('verwerfen', e.id).then((grund) => {
        if (grund) setFehlerAn({ id: e.id, grund });
      });
    },
    nurLesen,
    getrennt,
    gedankenSichtbar,
    gedankenUmschalten,
  };

  return (
    <ThemeProvider theme={thema}>
      <Box {...ablage} sx={{ position: 'relative', display: 'flex', flexDirection: 'column', bgcolor: FARBE.panel, color: FARBE.text, fontFamily: UI_SCHRIFT, minHeight: 0 }}>
        {ablageFlaeche}
        <ButtonBase
          onClick={() => setOffen((o) => !o)}
          aria-expanded={offen}
          sx={{ flexShrink: 0, height: KOPF, px: 2, gap: 1, justifyContent: 'flex-start', fontFamily: UI_SCHRIFT, transition: uebergang('background-color'), '&:hover': { bgcolor: FARBE.hover }, '&.Mui-focusVisible': FOKUS }}
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
        <StoppDialog offen={dialogOffen} auftrag={stoppFuer} onClose={() => setStoppFuer(null)} />

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
                        onClick={() => chatTextSetzen(v)}
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
              {(fehler || hinweis || sperre) && (
                <Box role={fehler || hinweis ? 'status' : undefined} sx={{ display: 'flex', gap: 0.75, px: 0.5, pb: 1, fontSize: 12, lineHeight: 1.4, color: fehler ? FARBE.fehler : FARBE.gedaempft }}>
                  {fehler && <ErrorOutlineRounded sx={{ fontSize: 14, mt: '1px' }} />}
                  {!fehler && hinweis && <InfoOutlined sx={{ fontSize: 14, mt: '1px', color: FARBE.warnung }} />}
                  <span>{fehler ?? hinweis ?? sperre}</span>
                </Box>
              )}
              <KontextChips altform={altform} />
              <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, pl: 1.5, pr: 0.5, py: 0.5, borderRadius: '8px', bgcolor: FARBE.feld, border: '1px solid transparent', transition: uebergang('border-color'), '&:focus-within': { borderColor: FARBE.akzent } }}>
                {bueroklammer}
                <InputBase
                  multiline
                  disabled={nurLesen}
                  maxRows={EINGABE_ZEILEN}
                  value={text}
                  inputRef={eingabe}
                  placeholder="Nachricht an den Assistenten"
                  onChange={(ev) => {
                    chatTextSetzen(ev.target.value.slice(0, NACHRICHT_MAX));
                    chatHinweisWeg();
                  }}
                  onPaste={beimEinfuegen}
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
                      sx={{ width: 28, height: 28, mb: '2px', bgcolor: FARBE.akzent, color: '#ffffff', '&:hover': { bgcolor: '#4a7bf0', color: '#ffffff' }, '&.Mui-disabled': { bgcolor: FARBE.linie, color: FARBE.gedaempft } }}
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
