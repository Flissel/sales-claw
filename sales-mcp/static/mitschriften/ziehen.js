// Mitschriften per Ziehen auf einen Reiter verschieben (Betreiber 19.11.2026).
// Ohne Skript bleibt das eingeklappte Formular je Karte der Weg; dieses Skript
// fuellt nur das versteckte Formular #dnd-verschieben und schickt es ab. Pruefung
// (CSRF, Rolle, Rubrik) macht derselbe Server-Weg wie beim Formular.
// Gezogen wird nur am Griff ⠿, damit der Text der Karte markierbar bleibt.
(function () {
  "use strict";
  var formular = document.getElementById("dnd-verschieben");
  if (!formular) { return; }
  var gezogen = null;
  var ausKurse = false;

  document.querySelectorAll('.griff[draggable="true"]').forEach(function (griff) {
    var karte = griff.closest("article.karte");
    griff.addEventListener("dragstart", function (ev) {
      gezogen = griff.getAttribute("data-uid");
      ausKurse = griff.getAttribute("data-kurs") === "1";
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", gezogen || "");
      if (karte) {
        ev.dataTransfer.setDragImage(karte, 16, 16);
        karte.classList.add("wird-gezogen");
      }
    });
    griff.addEventListener("dragend", function () {
      if (karte) { karte.classList.remove("wird-gezogen"); }
      gezogen = null;
      ausKurse = false;
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
      // data-kurs: Herausziehen aus „Kurse“ loescht Kursmitschrift und PDF.
      if (ausKurse && !window.confirm("Aus „Kurse“ nach „" + rubrik + "“ verschieben? "
          + "Kursmitschrift und PDF werden dabei gelöscht und erst beim Zurückschieben neu erzeugt.")) {
        return;
      }
      formular.elements.uid.value = gezogen;
      formular.elements.rubrik.value = rubrik;
      formular.submit();
    });
  });
})();
