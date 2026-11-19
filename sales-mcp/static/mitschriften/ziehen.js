// Mitschriften per Ziehen auf einen Reiter verschieben (Betreiber 19.11.2026).
// Ohne Skript bleibt das eingeklappte Formular je Karte der Weg; dieses Skript
// fuellt nur das versteckte Formular #dnd-verschieben und schickt es ab. Pruefung
// (CSRF, Rolle, Rubrik) macht derselbe Server-Weg wie beim Formular.
(function () {
  "use strict";
  var formular = document.getElementById("dnd-verschieben");
  if (!formular) { return; }
  var gezogen = null;

  document.querySelectorAll('article.karte[draggable="true"]').forEach(function (karte) {
    karte.addEventListener("dragstart", function (ev) {
      gezogen = karte.getAttribute("data-uid");
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", gezogen || "");
      karte.classList.add("wird-gezogen");
    });
    karte.addEventListener("dragend", function () {
      karte.classList.remove("wird-gezogen");
      gezogen = null;
    });
  });

  function rubrikVon(a) {
    try {
      return new URL(a.getAttribute("href"), window.location.href).searchParams.get("rubrik");
    } catch (e) {
      return null;
    }
  }

  document.querySelectorAll("nav.reiter a").forEach(function (a) {
    var rubrik = rubrikVon(a);
    // Nur Rubrik-Reiter sind Ziele (nicht „Handbücher“), der aktive Reiter nicht.
    if (!rubrik || a.getAttribute("aria-current") === "page") { return; }
    a.addEventListener("dragover", function (ev) {
      if (gezogen === null) { return; }
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      a.classList.add("ablage");
    });
    a.addEventListener("dragleave", function () { a.classList.remove("ablage"); });
    a.addEventListener("drop", function (ev) {
      ev.preventDefault();
      a.classList.remove("ablage");
      if (gezogen === null) { return; }
      formular.elements.uid.value = gezogen;
      formular.elements.rubrik.value = rubrik;
      formular.submit();
    });
  });
})();
