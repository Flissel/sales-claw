// deploy/stt/sprachnotiz.mjs - Sprachnachricht -> Text fuer das OpenClaw-Gateway
// (11.11.2026). OpenClaw ruft das als CLI-Modell aus tools.media.audio auf:
//
//   node /home/node/.openclaw/stt/sprachnotiz.mjs <audiodatei>
//
// Die Datei geht an sales-stt (faster-whisper am PC des Betreibers, nur im
// eigenen Tailnet) - dieselbe Stelle, die schon die Sprachnachrichten der
// Kunden abschreibt. Kein Cloud-Anbieter: die Stimme verlaesst das Haus nicht.
//
// Ausgabe: auf stdout NUR der abgeschriebene Text. Fehler: eine kurze Zeile auf
// stderr (Status bzw. Fehlerart, nie Schluessel oder Inhalt) und Code != 0 -
// OpenClaw laesst die Sprachnachricht dann als Anhang stehen.
//
// Zugang (url + schluessel) liegt in einer Datei im Gateway-Volume, angelegt
// von deploy/stt-anbinden.sh; STT_ZUGANG ueberschreibt den Pfad (Tests).
import { readFileSync } from "node:fs";

const ZUGANG = process.env.STT_ZUGANG || "/home/node/.openclaw/stt/zugang.json";
const WARTEZEIT_MS = 55000; // unter timeoutSeconds im Konfigurationsblock

function abbruch(meldung, code) {
  process.stderr.write("sprachnotiz: " + meldung + "\n");
  process.exit(code);
}

const datei = process.argv[2];
if (!datei) abbruch("Aufruf: sprachnotiz.mjs <audiodatei>", 2);

let url;
let schluessel;
try {
  const z = JSON.parse(readFileSync(ZUGANG, "utf8"));
  url = String(z.url || "").replace(/\/+$/, "");
  schluessel = String(z.schluessel || "");
} catch {
  abbruch("zugang fehlt oder unlesbar (deploy/stt-anbinden.sh)", 2);
}
if (!/^https?:\/\//.test(url)) abbruch("zugang ohne gueltige url", 2);

let audio;
try {
  audio = readFileSync(datei);
} catch {
  abbruch("audiodatei unlesbar", 2);
}

const kopf = { "Content-Type": "application/octet-stream" };
if (schluessel) kopf["X-STT-Key"] = schluessel;

let antwort;
try {
  antwort = await fetch(url + "/transkribieren", {
    method: "POST", headers: kopf, body: audio, signal: AbortSignal.timeout(WARTEZEIT_MS),
  });
} catch (e) {
  // Nur die Fehlerart: PC aus (ECONNREFUSED/ENOTFOUND) oder Zeitueberschreitung.
  abbruch("sales-stt nicht erreichbar (" + String(e?.cause?.code || e?.name || "Fehler") + ")", 3);
}
if (antwort.status !== 200) abbruch("sales-stt HTTP " + antwort.status, 4);

let text = "";
try {
  text = String((await antwort.json())?.text || "").trim();
} catch {
  abbruch("antwort von sales-stt unlesbar", 4);
}
if (!text) abbruch("keine Sprache erkannt", 5);
process.stdout.write(text + "\n");
