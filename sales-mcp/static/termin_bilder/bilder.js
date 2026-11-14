/* Bildschirm-Reiter der Termin-Akte: holt bilder.json alle 3 s, solange der
 * Termin live ist (danach einmalig), fuegt neue Karten an, entfernt nicht mehr
 * gelieferte (geloescht, z. B. als heikel erkannt) und sucht per ?q=. Der
 * Heikel-Hinweis folgt bilder_uebersprungen. Fremdtexte (Beschreibung, Name)
 * landen ausschliesslich per textContent im DOM, nie als HTML. */
(function () {
  "use strict";
  var wurzel = document.getElementById("bilder");
  var raster = document.getElementById("bild-raster");
  if (!wurzel || !raster) { return; }
  var adresse = wurzel.getAttribute("data-json");
  var suche = document.getElementById("bild-suche");
  var meldung = document.getElementById("bild-meldung");
  var vorlage = document.getElementById("bild-loeschen-vorlage");
  var leer = wurzel.querySelector(".bild-leer");
  var heikel = document.getElementById("bild-heikel");
  var TAKT = 3000;
  var suchtext = "";
  var timer = null;
  var laufnummer = 0;

  function el(name, klasse, text) {
    var e = document.createElement(name);
    if (klasse) { e.className = klasse; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function beschreibung(b) {
    if (b.beschreibung) { return b.beschreibung; }
    return b.status === "fehler" ? "keine Beschreibung möglich" : "wird beschrieben …";
  }

  function karte(b) {
    var li = el("li", "bild-karte karte");
    li.setAttribute("data-id", b.id);
    var a = el("a");
    a.href = b.url;
    a.target = "_blank";
    a.rel = "noopener";
    var img = el("img", "bild-gross");
    img.src = b.url;
    img.loading = "lazy";
    img.alt = "Bildschirm um " + b.uhr;
    a.appendChild(img);
    li.appendChild(a);
    var wer = b.uhr + (b.geteilt_von ? " · geteilt von " + b.geteilt_von : "");
    li.appendChild(el("p", "meta bild-zeit", wer));
    li.appendChild(el("p", "bild-text", beschreibung(b)));
    if (vorlage && vorlage.content) {
      var kopie = vorlage.content.cloneNode(true);
      var feld = kopie.querySelector("input[name=bild_id]");
      if (feld) { feld.value = b.id; }
      li.appendChild(kopie);
    }
    return li;
  }

  function bekannt() {
    var m = {};
    var karten = raster.querySelectorAll("li[data-id]");
    for (var i = 0; i < karten.length; i++) { m[karten[i].getAttribute("data-id")] = karten[i]; }
    return m;
  }

  function leerHinweis() {
    if (leer) { leer.hidden = raster.children.length > 0; }
  }

  /* Gleicher Text wie ui_termin.heikel_satz. */
  function heikelHinweis(n) {
    if (!heikel || typeof n !== "number") { return; }
    var text = "";
    if (n === 1) {
      text = "1 heikler Bildschirm (Anmeldung, Bezahlung, Postfach) wurde nicht gespeichert.";
    } else if (n > 1) {
      text = n + " heikle Bildschirme (Anmeldung, Bezahlung, Postfach) wurden nicht gespeichert.";
    }
    if (heikel.textContent !== text) { heikel.textContent = text; }
    heikel.hidden = !text;
  }

  /* Normalbetrieb: neue Karten oben anfuegen (Liste ist alt -> neu), vorhandene
   * nur in der Beschreibung auffrischen, nicht mehr gelieferte entfernen. Nie im
   * Suchmodus (dort zeigt das Raster nur Treffer). */
  function ergaenzen(liste) {
    var da = bekannt();
    if (wurzel.getAttribute("data-modus") !== "suche") {
      var geliefert = {};
      for (var j = 0; j < liste.length; j++) { geliefert[liste[j].id] = true; }
      for (var id in da) {
        if (Object.prototype.hasOwnProperty.call(da, id) && !geliefert[id]) {
          raster.removeChild(da[id]);
          delete da[id];
        }
      }
    }
    for (var i = 0; i < liste.length; i++) {
      var b = liste[i];
      var k = da[b.id];
      if (k) {
        var t = k.querySelector(".bild-text");
        if (t && t.textContent !== beschreibung(b)) { t.textContent = beschreibung(b); }
      } else {
        raster.insertBefore(karte(b), raster.firstChild);
      }
    }
    leerHinweis();
  }

  /* Suche: nur die Treffer zeigen, in Trefferreihenfolge. */
  function ersetzen(liste) {
    while (raster.firstChild) { raster.removeChild(raster.firstChild); }
    for (var i = 0; i < liste.length; i++) { raster.appendChild(karte(liste[i])); }
    leerHinweis();
  }

  function abrufen() {
    var nr = ++laufnummer;
    var q = suchtext;
    var url = adresse + (q ? "?q=" + encodeURIComponent(q) : "");
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("http")); })
      .then(function (d) {
        if (nr !== laufnummer) { return; }   // veraltete Antwort
        heikelHinweis(d.bilder_uebersprungen);
        if (q) {
          ersetzen(d.bilder || []);
          meldung.textContent = d.fehler ? d.fehler
            : ((d.bilder || []).length ? "" : "Keine passenden Bilder.");
        } else {
          meldung.textContent = "";
          if (wurzel.getAttribute("data-modus") === "suche") {
            wurzel.removeAttribute("data-modus");
            ersetzen([]);      // Trefferliste weg, alles frisch aufbauen
          }
          ergaenzen(d.bilder || []);
        }
        if (q) { wurzel.setAttribute("data-modus", "suche"); }
        planen(!q && d.live);
      })
      .catch(function () {
        if (nr !== laufnummer) { return; }
        meldung.textContent = "Bilder gerade nicht abrufbar.";
        planen(!q && wurzel.getAttribute("data-live") === "1");
      });
  }

  function planen(weiter) {
    if (timer) { clearTimeout(timer); timer = null; }
    if (weiter) { timer = setTimeout(abrufen, TAKT); }
  }

  if (suche) {
    var warte = null;
    suche.addEventListener("input", function () {
      clearTimeout(warte);
      warte = setTimeout(function () {
        suchtext = suche.value.replace(/\s+/g, " ").trim();
        planen(false);
        abrufen();
      }, 300);
    });
  }

  abrufen();
})();
