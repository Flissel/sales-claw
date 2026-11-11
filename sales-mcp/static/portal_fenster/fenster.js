// Portal-Fenster: noVNC-Client fuer das Chromium des Bewerbungs-Bots.
// Wird nur ueber /freigaben/bewerbung/fenster/fenster.js ausgeliefert (Rolle freigeben).
// Keine Zugangsdaten hier: der Server haengt sie an die Verbindung zum Container an.
import RFB from "./novnc/core/rfb.js";

const status = document.getElementById("status");
const schirm = document.getElementById("schirm");

function zeige(text) {
  status.textContent = text;
}

const protokoll = location.protocol === "https:" ? "wss:" : "ws:";
const adresse = `${protokoll}//${location.host}/freigaben/bewerbung/fenster/ws`;

try {
  const rfb = new RFB(schirm, adresse, { wsProtocols: ["binary"] });
  rfb.scaleViewport = true;
  rfb.resizeSession = false;
  rfb.addEventListener("connect", () => zeige("Verbunden"));
  rfb.addEventListener("disconnect", () => zeige("Getrennt \u2013 Seite neu laden"));
  rfb.addEventListener("securityfailure", () => zeige("Getrennt \u2013 Seite neu laden"));
  // Der Container verlangt kein VNC-Passwort; kommt die Frage trotzdem, nicht abfragen.
  rfb.addEventListener("credentialsrequired", () => {
    zeige("Fenster verlangt ein Passwort \u2013 Einrichtung pr\u00fcfen");
  });
} catch (e) {
  zeige("Getrennt \u2013 Seite neu laden");
}
