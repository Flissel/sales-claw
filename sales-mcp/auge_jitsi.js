// Seiten-Skript des Beobachters "Laura (Bildschirm)" (sales-auge, Bildauswertung live).
//
// window.__lauraBild() -> Promise<{teilt, quellen: [{quelle, von, jpeg}]}>
//   Sucht im Jitsi-Store (APP.store, 'features/base/tracks') die ENTFERNTEN
//   Bildschirm-Tracks (mediaType 'screenshare' UND videoType === 'desktop'; nur
//   Multistream-Jitsi, siehe istDesktop). Je Track (Quelle: getSourceName(),
//   Rueckfall participantId) laeuft NUR dessen Videospur in einem eigenen
//   losgeloesten <video>; hoechstens MAX_QUELLEN gleichzeitig (sortiert nach
//   Quelle). Je Quelle ein Standbild im Canvas (hoechstens 1600 px breit) als
//   JPEG (Qualitaet 0.8, Base64) plus Anzeigename des Teilenden. Verschwundene
//   Quellen geben ihr Video sofort frei.
//
// Kamera-Tracks werden NIE angefasst: kein Rendern, kein Lesen. Der Filter
// prueft den Store-Eintrag UND den Track selbst (getVideoType()).
//
// Empfang begrenzen: Die Empfangs-Vorgaben der Konferenz (Receiver-
// Constraints) werden auf die Bildschirm-Quellen umgebogen: Standard
// maxHeight 0 (keine Kameras), nur Desktop-Quellen mit Aufloesung, lastN =
// Anzahl der Desktop-Quellen. Auch Vorgaben, die die Jitsi-Oberflaeche selbst
// setzt, gehen durch diesen Filter.
//
// Keine Netzzugriffe, keine Ablage im Browser: das Bild verlaesst die Seite nur
// als Rueckgabewert an den Beobachter. window.__lauraInfo() liefert fuer die
// Diagnose nur Zahlen (keine Namen, keine Raeume).
(() => {
  'use strict';
  if (window.__lauraBild) return;

  const MAX_BREITE = 1600;
  const QUALITAET = 0.8;
  const BILD_WARTEN_MS = 3000;
  const DESKTOP = 'desktop';
  const MAX_QUELLEN = 3;
  const NICHTS = () => ({ teilt: false, quellen: [] });

  // Quelle -> { video, spur }: je Desktop-Track ein losgeloestes <video> und
  // die JitsiTrack-Spur, die darin laeuft.
  const videos = new Map();
  let aktuelle = [];     // [{quelle, von}] des laufenden Aufrufs (fuer die Zeitgrenze)
  let gepatcht = null;   // Konferenz, deren Empfangs-Vorgaben umgebogen sind
  let original = null;   // urspruengliches setReceiverConstraints dieser Konferenz
  let gesendet = null;   // zuletzt gesendete Quellenliste (Schluessel)

  const zustand = () => {
    try {
      return window.APP && window.APP.store ? window.APP.store.getState() : null;
    } catch (e) {
      return null;
    }
  };

  const konferenz = (s) => {
    const c = s && s['features/base/conference'];
    return (c && c.conference) || null;
  };

  // NUR entfernte Bildschirm-Tracks, und NUR im Multistream-Modell (mediaType
  // 'screenshare', eigener Track je Bildschirm). Der alte Weg (mediaType 'video'
  // mit videoType 'desktop') ist bewusst ausgeschlossen: dort teilen sich Kamera
  // und Bildschirm EINEN Track, und beim Umschalten koennte ein Kamerabild
  // durchrutschen. Ein Jitsi ohne Multistream liefert damit keine Bilder.
  const istDesktop = (t) => {
    if (!t || t.local || !t.jitsiTrack) return false;
    if (t.mediaType !== 'screenshare') return false;
    if (t.videoType !== DESKTOP) return false;
    const jt = t.jitsiTrack;
    if (typeof jt.isLocal === 'function' && jt.isLocal()) return false;
    if (typeof jt.getVideoType === 'function' && jt.getVideoType() !== DESKTOP) return false;
    return true;
  };

  const desktopTracks = (s) => ((s && s['features/base/tracks']) || []).filter(istDesktop);

  // Namen der Desktop-Quellen: aus vorhandenen Tracks und aus der Presence der
  // Teilnehmer (dort steht der videoType schon, bevor Medien fliessen).
  const desktopQuellen = (s, room) => {
    const namen = new Set();
    desktopTracks(s).forEach((t) => {
      const n = typeof t.jitsiTrack.getSourceName === 'function' && t.jitsiTrack.getSourceName();
      if (n) namen.add(String(n));
    });
    try {
      (room.getParticipants() || []).forEach((p) => {
        const quellen = typeof p.getSources === 'function' ? p.getSources() : null;
        const vid = quellen && typeof quellen.get === 'function' ? quellen.get('video') : null;
        if (vid && typeof vid.forEach === 'function') {
          vid.forEach((info, name) => {
            if (info && info.videoType === DESKTOP) namen.add(String(name));
          });
        }
      });
    } catch (e) {
      // Presence nicht lesbar: dann nur die Tracks
    }
    return [...namen].sort();
  };

  const vorgaben = (quellen) => {
    const c = {
      lastN: quellen.length,
      onStageSources: quellen,
      selectedSources: [],
      defaultConstraints: { maxHeight: 0 },
      constraints: {},
    };
    quellen.forEach((q) => { c.constraints[q] = { maxHeight: 1080 }; });
    return c;
  };

  const empfangBegrenzen = (s) => {
    const room = konferenz(s);
    if (!room || typeof room.setReceiverConstraints !== 'function') return;
    if (gepatcht !== room) {
      original = room.setReceiverConstraints.bind(room);
      // Jede Vorgabe der Oberflaeche wird durch die eigene ersetzt.
      room.setReceiverConstraints = () => original(vorgaben(desktopQuellen(zustand(), room)));
      if (typeof room.setLastN === 'function') room.setLastN = () => {};
      gepatcht = room;
      gesendet = null;
    }
    const quellen = desktopQuellen(s, room);
    const schluessel = quellen.join('|');
    if (schluessel !== gesendet) {
      original(vorgaben(quellen));
      gesendet = schluessel;
    }
  };

  const anzeigename = (s, room, id) => {
    const roh = String(id || '');
    const kandidaten = [roh, roh.replace(/-v\d+$/, '')];
    const p = s && s['features/base/participants'];
    for (const k of kandidaten) {
      const r = p && p.remote && typeof p.remote.get === 'function' ? p.remote.get(k) : null;
      if (r && r.name) return String(r.name);
    }
    try {
      const jp = room && room.getParticipantById(kandidaten[1]);
      const n = jp && jp.getDisplayName();
      if (n) return String(n);
    } catch (e) {
      // kein Name bekannt
    }
    return null;
  };

  // Name der Quelle: Jitsi-Quellname (Multistream, z. B. "<endpoint>-v1"),
  // Rueckfall die Teilnehmer-Id.
  const quelleVon = (t) => {
    const jt = t.jitsiTrack;
    const n = typeof jt.getSourceName === 'function' ? jt.getSourceName() : null;
    if (n) return String(n);
    return t.participantId ? String(t.participantId) : null;
  };

  const loesen = (quelle) => {
    const e = videos.get(quelle);
    if (e && e.video) {
      try { e.video.pause(); } catch (err) { /* egal */ }
      e.video.srcObject = null;
    }
    videos.delete(quelle);
  };

  const warten = (ms) => new Promise((r) => setTimeout(r, ms));

  const standbild = async (quelle, jt) => {
    let e = videos.get(quelle);
    if (!e || e.spur !== jt) {
      loesen(quelle);
      const stream = typeof jt.getOriginalStream === 'function' ? jt.getOriginalStream() : jt.stream;
      const spuren = stream && typeof stream.getVideoTracks === 'function' ? stream.getVideoTracks() : [];
      if (!spuren.length) return null;
      const neu = document.createElement('video');
      neu.muted = true;
      neu.playsInline = true;
      neu.autoplay = true;
      neu.srcObject = new MediaStream([spuren[0]]);
      e = { video: neu, spur: jt };
      videos.set(quelle, e);
      // Nicht auf play() warten: ohne Frames bliebe das Versprechen offen und
      // der Beobachter haengt. Stattdessen unten begrenzt auf Frames warten.
      try { neu.play().catch(() => {}); } catch (err) { /* Bild kommt ggf. spaeter */ }
    }
    const video = e.video;
    const ende = Date.now() + BILD_WARTEN_MS;
    while ((video.readyState < 2 || !video.videoWidth) && Date.now() < ende) await warten(100);
    if (!video.videoWidth || !video.videoHeight) return null;
    const f = Math.min(1, MAX_BREITE / video.videoWidth);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(video.videoWidth * f));
    canvas.height = Math.max(1, Math.round(video.videoHeight * f));
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL('image/jpeg', QUALITAET);
    const komma = url.indexOf(',');
    return url.startsWith('data:image/jpeg') && komma > 0 ? url.slice(komma + 1) : null;
  };

  // Obergrenze je Aufruf (fuer ALLE Quellen zusammen): der Beobachter wartet nie
  // unbegrenzt auf die Seite. Die Quellen werden parallel abgefragt.
  const HOECHSTENS_MS = 8000;
  window.__lauraBild = () => Promise.race([
    holen(),
    warten(HOECHSTENS_MS).then(() => ({
      teilt: aktuelle.length > 0,
      quellen: aktuelle.map((q) => ({ quelle: q.quelle, von: q.von, jpeg: null })),
    })),
  ]);

  const holen = async () => {
    const s = zustand();
    if (!s) return NICHTS();
    try { empfangBegrenzen(s); } catch (e) { /* Empfang bleibt wie er ist */ }
    const je = new Map();
    desktopTracks(s).filter((t) => !t.muted).forEach((t) => {
      const q = quelleVon(t);
      if (q && !je.has(q)) je.set(q, t);
    });
    const gewaehlt = [...je.keys()].sort().slice(0, MAX_QUELLEN);
    [...videos.keys()].forEach((q) => { if (!gewaehlt.includes(q)) loesen(q); });
    const room = konferenz(s);
    aktuelle = gewaehlt.map((q) => ({ quelle: q, von: anzeigename(s, room, je.get(q).participantId) }));
    if (!aktuelle.length) return NICHTS();
    const quellen = await Promise.all(aktuelle.map(async ({ quelle, von }) => {
      let jpeg = null;
      try { jpeg = await standbild(quelle, je.get(quelle).jitsiTrack); } catch (e) { jpeg = null; }
      return { quelle, von, jpeg };
    }));
    return { teilt: true, quellen };
  };

  // Empfang so frueh wie moeglich begrenzen: sobald die Konferenz existiert,
  // nicht erst beim ersten __lauraBild (Probe 13.11.: sonst kommen in den
  // ersten Sekunden einige KB Kamera-Daten an, die nie gelesen werden).
  setInterval(() => {
    const s = zustand();
    if (!s) return;
    try { empfangBegrenzen(s); } catch (e) { /* naechster Versuch */ }
  }, 250);

  window.__lauraInfo = () => {
    const s = zustand();
    const room = konferenz(s);
    const alle = (s && s['features/base/tracks']) || [];
    const entfernt = alle.filter((t) => !t.local);
    let teilnehmer = 0;
    try { teilnehmer = room ? room.getParticipants().length : 0; } catch (e) { teilnehmer = -1; }
    return {
      app: !!s,
      beigetreten: !!(room && typeof room.isJoined === 'function' && room.isJoined()),
      teilnehmer,
      entfernt_kamera: entfernt.filter((t) => t.videoType === 'camera').length,
      entfernt_desktop: entfernt.filter(istDesktop).length,
      entfernt_audio: entfernt.filter((t) => t.mediaType === 'audio').length,
      desktop_quellen: room ? desktopQuellen(s, room).length : 0,
      empfang_begrenzt: !!room && gepatcht === room,
      video_aktiv: videos.size > 0,
      videos_aktiv: videos.size,
    };
  };
})();
