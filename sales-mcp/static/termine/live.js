// Live-Steuerseite /termine/<uid>/live: fragt alle 3 s live.json ab und zeigt den
// BESTAETIGTEN Zustand, das Transkript mit Pausenzeilen und die Bilder als Kacheln
// (nur eigene Adressen /termine/..., dieselbe Route wie in der Akte).
// Transkript und Bildbeschreibungen sind Fremdtext: nur per textContent. Die Knoepfe
// sind normale Formulare der Seite; dieses Skript blendet sie nur je nach Zustand
// ein oder aus. Bei Fehlern: "Verbindung unterbrochen", spaeter erneut versuchen.
(function () {
  "use strict";
  var wurzel = document.getElementById("live");
  if (!wurzel) { return; }
  var url = wurzel.getAttribute("data-json");
  var zustandEl = document.getElementById("live-zustand");
  var verbindungEl = document.getElementById("live-verbindung");
  var textEl = document.getElementById("live-text");
  var bilderEl = document.getElementById("live-bilder");
  var bilderRaster = document.getElementById("live-bilder-raster");
  var TAKT = 3000;
  var TAKT_FEHLER = 10000;
  var letzteAnsicht = "";
  var letzteBilder = "";

  function zeit(iso) {
    var t = Date.parse(iso);
    return isNaN(t) ? 0 : t;
  }

  function zeile(klasse, teile) {
    var p = document.createElement("p");
    if (klasse) { p.className = klasse; }
    teile.forEach(function (teil) { p.appendChild(teil); });
    return p;
  }

  function textKnoten(text, fett) {
    var knoten = fett ? document.createElement("b") : document.createElement("span");
    knoten.textContent = text;
    return knoten;
  }

  function transkript(d) {
    var eintraege = [];
    (d.segmente || []).forEach(function (s) {
      eintraege.push({ t: zeit(s.beginn), rang: 1, s: s });
    });
    (d.pausen || []).forEach(function (p) {
      eintraege.push({ t: zeit(p.von), rang: 0, p: p });
    });
    eintraege.sort(function (a, b) { return a.t - b.t || a.rang - b.rang; });
    var teile = document.createDocumentFragment();
    eintraege.forEach(function (e) {
      if (e.p) {
        teile.appendChild(zeile("live-pause", [textKnoten(String(e.p.text || "Pause"), false)]));
      } else {
        teile.appendChild(zeile("", [
          textKnoten(String(e.s.uhr || "") + " ", false),
          textKnoten(String(e.s.sprecher || "?") + ": ", true),
          textKnoten(String(e.s.text || ""), false)
        ]));
      }
    });
    textEl.textContent = "";
    textEl.appendChild(teile);
  }

  function knoepfe(zustand) {
    var formulare = wurzel.querySelectorAll("form.live-knopf");
    Array.prototype.forEach.call(formulare, function (f) {
      var bei = (f.getAttribute("data-bei") || "").split(" ");
      f.hidden = bei.indexOf(zustand) < 0;
    });
  }

  // Nur eigene Bild-Adressen (dieselbe gesicherte Route wie im Bildschirm-Reiter der Akte).
  function eigeneBildAdresse(url) {
    return typeof url === "string" && url.indexOf("/termine/") === 0 && url.indexOf("//") < 0;
  }

  function kachel(b) {
    var li = document.createElement("li");
    li.className = "bild-karte karte";
    var a = document.createElement("a");
    a.href = b.url;
    a.target = "_blank";
    a.rel = "noopener";
    var img = document.createElement("img");
    img.src = b.url;
    img.loading = "lazy";
    img.alt = "Bildschirm um " + String(b.uhr || "");
    a.appendChild(img);
    li.appendChild(a);
    var wer = String(b.uhr || "") + (b.geteilt_von ? " · geteilt von " + String(b.geteilt_von) : "");
    li.appendChild(zeile("meta", [textKnoten(wer, false)]));
    li.appendChild(zeile("", [textKnoten(String(b.beschreibung || ""), false)]));
    return li;
  }

  function kacheln(d) {
    var teile = document.createDocumentFragment();
    // Neueste zuerst (die Liste kommt alt -> neu).
    (d.bilder || []).slice().reverse().forEach(function (b) {
      if (eigeneBildAdresse(b.url)) { teile.appendChild(kachel(b)); }
    });
    bilderRaster.textContent = "";
    bilderRaster.appendChild(teile);
  }

  function zeigen(d) {
    zustandEl.textContent = String(d.zustand_text || "");
    zustandEl.setAttribute("data-zustand", String(d.zustand || ""));
    knoepfe(String(d.zustand || ""));
    bilderEl.textContent = "Bilder: " + String(d.bilder_anzahl || 0);
    var ansicht = JSON.stringify([d.segmente, d.pausen]);
    if (ansicht !== letzteAnsicht) {
      letzteAnsicht = ansicht;
      transkript(d);
    }
    var bilder = JSON.stringify(d.bilder || []);
    if (bilderRaster && bilder !== letzteBilder) {
      letzteBilder = bilder;
      kacheln(d);
    }
  }

  function runde() {
    var naechste = TAKT;
    fetch(url, { credentials: "same-origin", cache: "no-store",
                 headers: { "Accept": "application/json" } })
      .then(function (antwort) {
        if (antwort.status === 401 || antwort.status === 403) {
          throw new Error("abgemeldet");
        }
        if (!antwort.ok) { throw new Error("status"); }
        return antwort.json();
      })
      .then(function (d) {
        verbindungEl.hidden = true;
        zeigen(d);
      })
      .catch(function () {
        verbindungEl.hidden = false;
        naechste = TAKT_FEHLER;
      })
      .then(function () {
        window.setTimeout(runde, naechste);
      });
  }

  runde();
})();
