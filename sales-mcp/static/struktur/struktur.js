// Struktur per Ziehen umhaengen (Betreiber 28.10.2026). Ohne Skript bleiben die
// Formulare je Eintrag der Weg; dieses Skript fuellt nur die versteckten
// Formulare #dnd-einlader / #dnd-ueber und schickt sie nach einer Rueckfrage ab.
// Ringe (jemanden unter seinen eigenen Teilbaum) lehnt der Server ab.
(function () {
  "use strict";
  var gezogen = null;

  function name(el) {
    var li = el && el.closest ? el.closest("[data-name]") : null;
    return li ? li.getAttribute("data-name") : null;
  }

  document.querySelectorAll('li[draggable="true"]').forEach(function (li) {
    li.addEventListener("dragstart", function (ev) {
      ev.stopPropagation();
      gezogen = li.getAttribute("data-name");
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", gezogen);
      li.classList.add("wird-gezogen");
    });
    li.addEventListener("dragend", function () {
      li.classList.remove("wird-gezogen");
      gezogen = null;
    });
  });

  function ziel(el, beiAblage) {
    el.addEventListener("dragover", function (ev) {
      if (gezogen === null) { return; }
      ev.preventDefault();
      ev.stopPropagation();
      el.classList.add("ablage");
    });
    el.addEventListener("dragleave", function () { el.classList.remove("ablage"); });
    el.addEventListener("drop", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      el.classList.remove("ablage");
      if (gezogen === null) { return; }
      beiAblage(gezogen, el);
    });
  }

  document.querySelectorAll(".struktur-liste [data-name]").forEach(function (li) {
    ziel(li, function (wer, el) {
      var neu = name(el);
      if (neu === wer) { return; }
      var text = neu ? "unter " + neu : "direkt unter dich";
      if (!window.confirm(wer + " " + text + " hängen?")) { return; }
      var f = document.getElementById("dnd-einlader");
      f.elements.name.value = wer;
      f.elements.einlader.value = neu || "";
      f.submit();
    });
  });

  var ueber = document.querySelector('[data-ziel="ueber"]');
  if (ueber) {
    ziel(ueber, function (wer) {
      if (!window.confirm(wer + " als deinen höheren Knoten setzen?")) { return; }
      var f = document.getElementById("dnd-ueber");
      f.elements.ueber.value = wer;
      f.submit();
    });
  }
})();
