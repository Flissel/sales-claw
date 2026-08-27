---
name: linkedin-post
description: "LinkedIn-Beitrag entwerfen oder ueberarbeiten — fester Workflow: Historie lesen, Leser-Nutzen vor Produkt, drei Haken-Varianten, Schablonen-Pruefung, Entwurf zur Freigabe. Nutzen bei jedem Beitrag, den der Betreiber bestellt."
metadata: { "openclaw": { "emoji": "📣" } }
---

# LinkedIn-Beitrag — der Workflow

Gilt fuer NEUE Beitraege und fuer das UEBERARBEITEN wartender Entwuerfe.
Das Ergebnis ist IMMER ein Entwurf zur Freigabe — veroeffentlicht wird
ausschliesslich ueber den Einmal-Versender, den der Betreiber ausloest.

## Schritt 1 — Historie lesen (Pflicht, zuerst)

`linkedin_historie()` aufrufen. Zwei Dinge herausschreiben:

* Welche Themen und Blickwinkel sind schon draussen? Zum selben Thema
  entsteht kein zweiter Beitrag (Ausnahme nur mit `trotzdem=True` und
  echtem neuen Blickwinkel).
* Was steht unter `bausteine`? Diese Wendungen sind VERBRAUCHT — anders
  formulieren oder weglassen. Fuenf Beitraege mit demselben Satz sind
  eine Schablone, und Schablonen zerstoeren Glaubwuerdigkeit.

## Schritt 2 — Den Leser finden, nicht das Produkt

Bevor du eine Zeile schreibst, beantworte schriftlich fuer dich:

* Wer soll das lesen (Rolle, Alltag)?
* Was verliert diese Person HEUTE — Zeit, Geld, Nerven, Chancen — an dem
  Problem, das das Produkt loest?
* Woran erkennt sie sich in den ersten zwei Zeilen wieder?

Der Beitrag beginnt mit diesem Verlust oder dieser Szene. Das Produkt
tritt erst danach auf, als Antwort — nie als Hauptfigur. "Wir haben X
gebaut" ist als Einstieg verboten.

## Schritt 3 — Drei Haken, nimm den haertesten ehrlichen

Schreibe DREI verschiedene erste Zeilen (Musterbruch: ueberraschende
Zahl, unbequeme Behauptung, konkrete Szene). Waehle die haerteste, die
noch wahr ist. Verworfene Varianten nicht loeschen, sondern dem
Betreiber im Chat mitnennen — er waehlt manchmal anders.

## Schritt 4 — Koerper und Schluss

* EIN Gedanke pro Beitrag. Keine Feature-Liste, keine zweite Botschaft.
* Kurze Zeilen, Absaetze nach je ein bis zwei Saetzen.
* Schluss: eine konkrete Frage, die der Leser aus dem EIGENEN Alltag
  beantworten kann — keine rhetorische.
* Hoechstens 3000 Zeichen; gute Beitraege sind deutlich kuerzer.
* Video/Bild-Verweis natuerlich einbetten, nie mit der verbrauchten
  Formel aus den bausteinen.

## Schritt 5 — Selbstpruefung gegen die Historie

Vergleiche den fertigen Text NOCHMAL mit den `bausteine`n aus Schritt 1.
Jede Uebereinstimmung ab sechs Wörtern Folge: umformulieren.

## Schritt 6 — Entwurf ablegen, nie senden

* Neuer Beitrag: `post_entwurf_erstellen(...)`.
* Wartender Entwurf ueberarbeiten: `entwurf_bearbeiten(...)` — geht nur
  bei pending, genau richtig so.
* Danach dem Betreiber EINEN Satz: worum es geht, welcher Haken gewaehlt
  wurde, welche Varianten es noch gaebe. Freigabe und Versand sind seine
  Entscheidung (Versand danach per `linkedin_versand_anfordern()`, nur
  auf seine ausdrueckliche Bitte).
