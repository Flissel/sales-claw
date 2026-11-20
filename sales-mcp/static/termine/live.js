// Live-Steuerseite /termine/<uid>/live: fragt alle 3 s live.json ab und zeigt den
// BESTAETIGTEN Zustand, das Transkript mit Pausenzeilen und die Bilderzahl.
// Das Transkript ist Fremdtext: es wird nur per textContent gesetzt. Die Knoepfe
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
  var TAKT = 3000;
  var TAKT_FEHLER = 10000;
  var letzteAnsicht = "";

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
