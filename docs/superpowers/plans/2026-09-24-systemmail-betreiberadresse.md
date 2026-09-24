# Systemmails aller Läden über die Adresse des Betreibers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Konto-Mails (Passwort vergessen, neu: Willkommen) gehen in jedem Laden über die Adresse des Betreibers raus, Kundenentwürfe nie.

**Architecture:** `mail_dispatch.py` bekommt eine zweite SMTP-Identität (`SYSTEM_*`), die ausschließlich für `benutzer_mails` gilt. Jeder Laden bekommt einen `<laden>-mail`-Dienst. „Laden anlegen" nimmt optional eine private Adresse an, und der Host-Orchestrator legt im neuen Schema einen Willkommens-Zettel ab und meldet dessen Ausgang zurück.

**Tech Stack:** Python 3.12 (`smtplib`, psycopg3), Starlette (`sales-mcp/ui.py`), PostgreSQL (`db/provision.sql`, `db/laden-anlegen.sql`), Bash (`deploy/*.sh`), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-24-systemmail-betreiberadresse-design.md`

## Global Constraints

- Ein Kundenentwurf (`drafts`) wird **nie** über die System-Identität verschickt. Fehlt `SMTP_*`, bleiben Entwürfe `approved` liegen.
- System-Identität = `SYSTEM_SMTP_HOST`, `SYSTEM_SMTP_PORT` (Vorgabe 587), `SYSTEM_SMTP_USER`, `SYSTEM_SMTP_PASSWORT`, `SYSTEM_ABSENDER`. Ist sie unvollständig, gilt für Konto-Mails `SMTP_*`/`EMAIL_ABSENDER`.
- `SYSTEM_*` gehen per Compose **nur** an `sales-mail`, nie an `sales-ui` oder `sales-mcp` (T5a).
- Kein Geheimnis über Argv (`psql -v`, `docker exec -e NAME=wert`, `curl -H`). Nicht-geheime Werte (Name, Adresse) dürfen über `psql -v` laufen.
- Konto-Mail-Texte sind fest, ohne Parameter für freien Inhalt. Token-Klartext entsteht im Versender, nur der Hash geht in die Datenbank.
- Gültigkeit: `passwort_reset` 30 Minuten (unverändert), `willkommen` 7 Tage.
- Nie `docker compose up -d` ohne wörtliche Dienstnamen (`sales-mcp sales-ui sales-mail`).
- Anzeigetexte in `ui.py` mit echten Umlauten (`test_darstellung.py::test_literale_zeigen_echte_umlaute`). Kommentare und `passwort_reset.py`-Mailtexte bleiben im bestehenden ASCII-Stil.
- Tests laufen nur im Container: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest <datei> -q`. Wenn der Container die DB nicht erreicht, zusätzlich `--network host`. Nach jeder Änderung an `db/provision.sql` zuerst `docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql`.
- Kein Subagent fasst die VM an (Deploy, `ivan.env`, Container-Start, echter Probelauf). Das macht Task 5, nur mit Freigabe.

## Review Focus

1. **Basis-Laden unverändert:** Ohne `SYSTEM_*` geht eine Konto-Mail mit `From: EMAIL_ABSENDER` raus, Entwürfe wie bisher (Task 1, `test_ohne_system_identitaet_nimmt_kontomail_die_des_ladens`).
2. **Laden mit beiden Identitäten:** Der Entwurf geht vom Laden, die Konto-Mail vom Betreiber, in derselben Runde (Task 1, `test_beide_identitaeten_trennen_sauber`).
3. **System-Passwort in Fehlertexten:** Es wird maskiert wie das Laden-Passwort (Task 1, `test_system_passwort_wird_maskiert`).
4. **Gültigkeiten nicht vertauscht:** `reset_bis` ist ~30 min bei `passwort_reset` und ~7 Tage bei `willkommen` (Task 2, `test_willkommen_gilt_sieben_tage_reset_dreissig_minuten`).
5. **Laden anlegen ohne Adresse:** Verhalten wie heute, das Wegwerf-Passwort wird angezeigt, kein Zettel (Task 3, `test_ohne_adresse_bleibt_alles_wie_bisher`, und Task 4, Step 6).

---

### Task 1: Zwei Identitäten im Mail-Dienst

**Files:**
- Modify: `sales-mcp/mail_dispatch.py`
- Modify: `sales-mcp/tests/test_mail_dispatch.py`
- Modify: `sales-mcp/tests/test_passwort_reset.py` (nur die Attrappe `_versenden`)

**Interfaces:**
- Produces: `mail_dispatch.Identitaet` (frozen dataclass: `art, host, port, user, passwort, absender`; Methoden `vollstaendig()`, `brauchbar()`), `kunden_identitaet() -> Identitaet`, `system_identitaet() -> Identitaet`, `senden(nachricht, identitaet=None)`, `_verbindung(identitaet=None)`, `nachricht_bauen(adresse, betreff, rumpf, cc=None, absender=None)`. Task 2 benutzt `system_identitaet()` und `nachricht_bauen(..., absender=...)`.

- [ ] **Step 1: Konfiguration und Identitäten**

In `sales-mcp/mail_dispatch.py` bei den übrigen Importen ergänzen:

```python
from dataclasses import dataclass
```

Direkt nach der Zeile `EMAIL_ABSENDER = os.environ.get("EMAIL_ABSENDER", "").strip()` einfügen:

```python

# Zweite Identitaet (24.09.2026): NUR fuer Konto-Mails aus `benutzer_mails`
# - die Adresse des Betreibers, damit auch ein Laden ohne eigenes Postfach
# "Passwort vergessen" und Willkommensmails verschicken kann. Kundenentwuerfe
# laufen NIE hierueber (siehe eine_runde). Fehlt sie, gelten fuer
# Konto-Mails die SMTP_* oben - im Basis-Laden ist das dieselbe Person.
SYSTEM_SMTP_HOST = os.environ.get("SYSTEM_SMTP_HOST", "").strip()
SYSTEM_SMTP_PORT = int(os.environ.get("SYSTEM_SMTP_PORT", "587") or "587")
SYSTEM_SMTP_USER = os.environ.get("SYSTEM_SMTP_USER", "").strip()
SYSTEM_SMTP_PASSWORT = os.environ.get("SYSTEM_SMTP_PASSWORT", "")
SYSTEM_ABSENDER = os.environ.get("SYSTEM_ABSENDER", "").strip()
```

Direkt vor `class VersandFehler(Exception):` einfügen:

```python
@dataclass(frozen=True)
class Identitaet:
    """Mit wessen Zugangsdaten und unter welcher Adresse eine Mail rausgeht."""
    art: str            # "kunde" | "system" - nur fuer Log und Fehlertexte
    host: str
    port: int
    user: str
    passwort: str
    absender: str

    def vollstaendig(self) -> bool:
        return bool(self.host and self.user and self.passwort and self.absender)

    def brauchbar(self) -> bool:
        return self.vollstaendig() and bool(mailadresse.pruefe(self.absender)[0])


def kunden_identitaet() -> Identitaet:
    """Die Identitaet des Ladens selbst. Liest die Modulkonstanten bei jedem
    Aufruf, damit Tests sie wie bisher umbiegen koennen."""
    return Identitaet("kunde", SMTP_HOST, SMTP_PORT, SMTP_USER,
                      SMTP_PASSWORT, EMAIL_ABSENDER)


def system_identitaet() -> Identitaet:
    """Fuer Konto-Mails: die des Betreibers, wenn vollstaendig gesetzt,
    sonst die des Ladens."""
    eigen = Identitaet("system", SYSTEM_SMTP_HOST, SYSTEM_SMTP_PORT,
                       SYSTEM_SMTP_USER, SYSTEM_SMTP_PASSWORT, SYSTEM_ABSENDER)
    return eigen if eigen.vollstaendig() else kunden_identitaet()


```

- [ ] **Step 2: Beide Passwörter maskieren**

Den Rumpf von `_ohne_geheimnis` (ab `if not SMTP_PASSWORT:` bis einschließlich `return text`) ersetzen durch:

```python
    # Seit 24.09.2026 fuer BEIDE Identitaeten.
    for user, passwort in ((SMTP_USER, SMTP_PASSWORT),
                           (SYSTEM_SMTP_USER, SYSTEM_SMTP_PASSWORT)):
        if not passwort:
            continue
        # Auch die kodierten Formen (Review-Befund H2): auf der Leitung
        # reist das Passwort als Base64 - allein (AUTH LOGIN) oder als
        # \0user\0passwort-Block (AUTH PLAIN).
        text = text.replace(passwort, "***")
        text = text.replace(base64.b64encode(
            passwort.encode("utf-8")).decode("ascii"), "***")
        text = text.replace(base64.b64encode(
            f"\0{user}\0{passwort}".encode("utf-8")).decode("ascii"), "***")
    return text
```

- [ ] **Step 3: Absender, Verbindung und Versand je Identität**

In `nachricht_bauen` die Signatur und die `From`-Zeile ändern:

```python
def nachricht_bauen(adresse: str, betreff: str, rumpf: str,
                    cc=None, absender=None) -> EmailMessage:
```

```python
    nachricht["From"] = absender or EMAIL_ABSENDER
```

`_verbindung` ändern. Der Docstring bleibt, Signatur und Rumpf werden zu:

```python
def _verbindung(identitaet=None):
```

```python
    ident = identitaet or kunden_identitaet()
    kontext = ssl.create_default_context()
    if ident.port == SMTP_SSL_PORT:
        return smtplib.SMTP_SSL(ident.host, ident.port,
                                timeout=SMTP_TIMEOUT_S, context=kontext)
    verbindung = smtplib.SMTP(ident.host, ident.port, timeout=SMTP_TIMEOUT_S)
    verbindung.ehlo()
    verbindung.starttls(context=kontext)
    verbindung.ehlo()
    return verbindung
```

In `senden` die Signatur ändern zu `def senden(nachricht: EmailMessage, identitaet=None) -> None:`. Direkt nach dem Docstring einfügen:

```python
    ident = identitaet or kunden_identitaet()
    praefix = "SYSTEM_SMTP" if ident.art == "system" else "SMTP"
```

Im `try`-Block ersetzen:

```python
        verbindung = _verbindung(ident)
        if ident.user:
            verbindung.login(ident.user, ident.passwort)
        verbindung.send_message(nachricht)
```

Im `SMTPAuthenticationError`-Zweig ersetzen:

```python
            f"SMTP-Anmeldung abgelehnt ({e.smtp_code}) — {praefix}_USER/"
            f"{praefix}_PASSWORT in der .env pruefen (viele Anbieter verlangen "
```

Im `ssl.SSLError`-Zweig ersetzen:

```python
            f"TLS-Fehler zum Mailserver: {e}. Stimmt {praefix}_PORT? 465 ist "
```

- [ ] **Step 4: Die Weiche in der Runde und beim Start**

In `eine_runde` die Entwurfsabfrage in eine Bedingung einschließen. Ersetzen:

```python
    zeilen = server._q(
        "select id from drafts where status = 'approved' and channel = 'email' "
        "order by created_at limit %s", (STAPEL,))
```

durch:

```python
    # DIE WEICHE (24.09.2026): Kundenentwuerfe nur mit der EIGENEN Identitaet
    # des Ladens. Fehlt sie, bleiben sie `approved` liegen und gehen raus,
    # sobald das Postfach eingetragen ist - nie ueber die des Betreibers.
    if kunden_identitaet().brauchbar():
        zeilen = server._q(
            "select id from drafts where status = 'approved' "
            "and channel = 'email' order by created_at limit %s", (STAPEL,))
    else:
        zeilen = []
```

In `main` den Block von `fehlend = _fehlende_konfiguration()` bis einschließlich des `return 0` nach der `EMAIL_ABSENDER`-Prüfung ersetzen durch:

```python
    kunde_aktiv = kunden_identitaet().brauchbar()
    system = system_identitaet()
    konto_aktiv = system.brauchbar()
    if not (kunde_aktiv or konto_aktiv):
        # Exit 0, nicht 2: ein nicht eingerichteter E-Mail-Kanal ist ein
        # gueltiger Zustand dieses Prototyps, kein Ausfall.
        fehlend = _fehlende_konfiguration()
        if fehlend:
            LOG.warning("E-Mail-Kanal nicht eingerichtet — %s fehlt in der "
                        "Umgebung (.env). Es wird nichts versendet; "
                        "freigegebene E-Mail-Entwuerfe bleiben unangetastet "
                        "liegen.", ", ".join(fehlend))
        else:
            LOG.error("EMAIL_ABSENDER ist keine brauchbare Adresse — es wird "
                      "nichts versendet.")
        return 0
    LOG.info("Aktiv: kundenmails=%s kontomails=%s (identitaet=%s)",
             "ja" if kunde_aktiv else "nein — Entwuerfe bleiben liegen",
             "ja" if konto_aktiv else "nein", system.art)
```

- [ ] **Step 5: Test-Attrappen an die neue Signatur anpassen**

In `sales-mcp/tests/test_mail_dispatch.py`, Fixture `saubere_umgebung`: direkt nach `monkeypatch.setattr(mail_dispatch, "EMAIL_ABSENDER", "haus@example.org")` einfügen:

```python
    # Riegel 2b: nie die echte Betreiber-Identitaet aus der .env.
    for name in ("SYSTEM_SMTP_HOST", "SYSTEM_SMTP_USER",
                 "SYSTEM_SMTP_PASSWORT", "SYSTEM_ABSENDER"):
        monkeypatch.setattr(mail_dispatch, name, "")
```

Und die drei Attrappen erweitern: `def _blank():` wird `def _blank(identitaet=None):`, und beide `def _tot():` werden `def _tot(identitaet=None):`.

In `sales-mcp/tests/test_passwort_reset.py`, Funktion `_versenden`: `def _ausgang(_nachricht):` wird `def _ausgang(_nachricht, **_k):`. Außerdem bekommt der `with`-Block einen weiteren Patch, damit der Test nicht von der `.env` im Container abhängt:

```python
    with mock.patch.object(mail_dispatch, "UI_BASIS_URL", basis), \
         mock.patch.object(mail_dispatch, "EMAIL_ABSENDER",
                           "haus@example.invalid"), \
         mock.patch.object(mail_dispatch, "system_identitaet",
                           lambda: mail_dispatch.Identitaet(
                               "system", "127.0.0.1", 587, "u", "p",
                               "haus@example.invalid")), \
         mock.patch.object(mail_dispatch, "senden",
                           side_effect=_ausgang) as gesendet:
```

- [ ] **Step 6: Neue Tests schreiben**

Am Ende von `sales-mcp/tests/test_mail_dispatch.py` anfügen:

```python
# ---------------------------------------------------------------------------
# Zwei Identitaeten (24.09.2026): Konto-Mails vom Betreiber, Entwuerfe nie
# ---------------------------------------------------------------------------

def _system_setzen(monkeypatch, absender="betreiber@example.org"):
    monkeypatch.setattr(mail_dispatch, "SYSTEM_SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(mail_dispatch, "SYSTEM_SMTP_PORT", STUB_PORT)
    monkeypatch.setattr(mail_dispatch, "SYSTEM_SMTP_USER", "betreiber-user")
    monkeypatch.setattr(mail_dispatch, "SYSTEM_SMTP_PASSWORT", "SYSTEM-GEHEIMNIS")
    monkeypatch.setattr(mail_dispatch, "SYSTEM_ABSENDER", absender)


def _konto_mit_zettel(name="lena", art="passwort_reset"):
    with server.pool.connection() as conn:
        conn.execute("truncate sales_test.benutzer, sales_test.benutzer_mails")
    server._q(
        "insert into benutzer (name, rolle, passwort_hash, aktiv, email) "
        "values (%s, 'lesen', 'x', true, %s) returning name",
        (name, f"{name}@privat.example"))
    return server._q(
        "insert into benutzer_mails (benutzer, art) values (%s, %s) "
        "returning id", (name, art))[0]["id"]


def _zettelstatus(zettel_id):
    return server._q("select status, grund from benutzer_mails where id = %s",
                     (zettel_id,))[0]


def test_ohne_kundenpostfach_bleibt_der_entwurf_liegen(monkeypatch):
    """Die Kernregel: gaebe es nur die Betreiber-Identitaet, darf ein
    Kundenentwurf trotzdem NICHT rausgehen - sonst schriebe der Betreiber
    im Namen eines anderen Menschen an dessen Kunden."""
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "")
    _system_setzen(monkeypatch)
    draft = _draft(_lead())

    mail_dispatch.eine_runde()

    assert _zeile(draft)["status"] == "approved"
    assert STUB.mails == []


def test_kontomail_geht_ueber_die_betreiber_identitaet(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "")
    monkeypatch.setattr(mail_dispatch, "UI_BASIS_URL", "https://laden.example")
    _system_setzen(monkeypatch)
    zettel = _konto_mit_zettel()

    mail_dispatch.eine_runde()

    assert _zettelstatus(zettel)["status"] == "gesendet"
    assert len(STUB.mails) == 1
    assert "betreiber@example.org" in STUB.mails[0]["absender"]
    assert "From: betreiber@example.org" in STUB.mails[0]["roh"]


def test_beide_identitaeten_trennen_sauber(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "UI_BASIS_URL", "https://laden.example")
    _system_setzen(monkeypatch)
    draft = _draft(_lead())
    zettel = _konto_mit_zettel()

    mail_dispatch.eine_runde()

    assert _zeile(draft)["status"] == "sent"
    assert _zettelstatus(zettel)["status"] == "gesendet"
    absender = sorted(m["absender"] for m in STUB.mails)
    assert any("haus@example.org" in a for a in absender)
    assert any("betreiber@example.org" in a for a in absender)
    for m in STUB.mails:
        if "max@example.com" in " ".join(m["empfaenger"]):
            assert "haus@example.org" in m["absender"]


def test_ohne_system_identitaet_nimmt_kontomail_die_des_ladens(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "UI_BASIS_URL", "https://laden.example")
    zettel = _konto_mit_zettel()

    mail_dispatch.eine_runde()

    assert _zettelstatus(zettel)["status"] == "gesendet"
    assert "haus@example.org" in STUB.mails[0]["absender"]


def test_system_passwort_wird_maskiert(monkeypatch):
    _system_setzen(monkeypatch)
    text = mail_dispatch._ohne_geheimnis("Antwort: SYSTEM-GEHEIMNIS kaputt")
    assert "SYSTEM-GEHEIMNIS" not in text and "***" in text


def test_dienst_startet_mit_nur_der_system_identitaet(monkeypatch):
    monkeypatch.setattr(mail_dispatch, "SMTP_PASSWORT", "")
    _system_setzen(monkeypatch)
    monkeypatch.setattr(mail_dispatch, "MAIL_ONCE", True)
    draft = _draft(_lead())

    with _Mitschnitt() as mitschnitt:
        assert mail_dispatch.main() == 0

    assert _zeile(draft)["status"] == "approved"
    gemeldet = " ".join(mitschnitt.texte())
    assert "kontomails=ja" in gemeldet
    assert "Entwuerfe bleiben liegen" in gemeldet
```

Hinweis: Der Stub zeichnet `absender` aus `MAIL FROM` auf (Form `<adresse>`), deshalb prüfen die Tests mit `in`. `"sent"` ist der Erfolgsstatus eines Entwurfs (nachgesehen: `tests/test_mail_dispatch.py:378`).

- [ ] **Step 7: Tests laufen lassen**

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest tests/test_mail_dispatch.py tests/test_passwort_reset.py tests/test_links_und_cc.py tests/test_kollision.py tests/test_termin_einladen.py -q`
Expected: alle grün. Die bestehenden Tests `test_ohne_konfiguration_endet_der_dienst_sauber` und `test_unbrauchbarer_absender_versendet_nichts` müssen unverändert grün bleiben.

- [ ] **Step 8: Volle Suite, dann Commit**

Run: `docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest -q`
Expected: alle grün.

```bash
git add sales-mcp/mail_dispatch.py sales-mcp/tests/test_mail_dispatch.py sales-mcp/tests/test_passwort_reset.py
git commit -m "feat(sales-claw): Mail-Dienst trennt Kunden- und Betreiber-Identitaet"
```

---

### Task 2: Willkommens-Zettel im Versender und in der Datenbank

**Files:**
- Modify: `sales-mcp/passwort_reset.py`
- Modify: `sales-mcp/mail_dispatch.py` (`verarbeite_kontomail`)
- Modify: `db/provision.sql` (Schleife je Laden, nach `benutzer_mails_offen_idx`)
- Modify: `db/laden-anlegen.sql`
- Modify: `sales-mcp/tests/test_passwort_reset.py`

**Interfaces:**
- Consumes: `mail_dispatch.system_identitaet()`, `senden(nachricht, identitaet=...)`, `nachricht_bauen(..., absender=...)` aus Task 1.
- Produces: `benutzer_mails.art in ('passwort_reset','willkommen')` in jedem Laden-Schema. `passwort_reset.WILLKOMMEN_GUELTIG_S`, `WILLKOMMEN_BETREFF`, `willkommenstext(name, link)`. Task 4 legt Zettel `art='willkommen'` an.

- [ ] **Step 1: Test schreiben (rot)**

Am Ende von `sales-mcp/tests/test_passwort_reset.py` anfügen:

```python
# --- Willkommen (24.09.2026) -----------------------------------------------

def _zettel_willkommen(name):
    return server._q(
        "insert into benutzer_mails (benutzer, art) values (%s, 'willkommen') "
        "returning id", (name,))[0]["id"]


def test_willkommen_gilt_sieben_tage_reset_dreissig_minuten():
    _benutzer("lena", email="lena@privat.example")
    _benutzer("ivan")
    _versenden(_zettel_willkommen("lena"))
    _anfordern("ivan")
    _versenden(_zettel("ivan")[0]["id"])
    rest = {z["name"]: z["rest_s"] for z in server._q(
        "select name, extract(epoch from reset_bis - now()) as rest_s "
        "from benutzer where name in ('lena','ivan')")}
    assert 6.9 * 86400 < rest["lena"] <= 7 * 86400
    assert 25 * 60 < rest["ivan"] <= 30 * 60


def test_willkommen_hat_festen_text_und_link_auf_den_eigenen_laden():
    _benutzer("lena", email="lena@privat.example")
    ausgang, gesendet = _versenden(_zettel_willkommen("lena"),
                                   basis="https://ivan.example:8445")
    assert ausgang == "gesendet"
    nachricht = gesendet.call_args[0][0]
    assert nachricht["Subject"] == passwort_reset.WILLKOMMEN_BETREFF
    assert nachricht["To"] == "lena@privat.example"
    rumpf = nachricht.get_body(preferencelist=("plain",)).get_content()
    assert "https://ivan.example:8445/passwort-neu?name=lena&token=" in rumpf
    assert "lena" in rumpf and "7 Tage" in rumpf


def test_willkommen_geht_ueber_die_system_identitaet():
    _benutzer("lena", email="lena@privat.example")
    _, gesendet = _versenden(_zettel_willkommen("lena"))
    assert gesendet.call_args.kwargs["identitaet"].art == "system"


def test_unbekannte_art_bleibt_fehler():
    _benutzer("lena", email="lena@privat.example")
    with server.pool.connection() as conn:
        conn.execute("alter table benutzer_mails drop constraint benutzer_mails_art_check")
    try:
        zid = server._q("insert into benutzer_mails (benutzer, art) values "
                        "('lena', 'quatsch') returning id")[0]["id"]
        ausgang, gesendet = _versenden(zid)
        assert ausgang == "fehler" and not gesendet.called
    finally:
        with server.pool.connection() as conn:
            conn.execute("delete from benutzer_mails where art = 'quatsch'")
            conn.execute("alter table benutzer_mails add constraint "
                         "benutzer_mails_art_check check "
                         "(art in ('passwort_reset','willkommen'))")
```

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest tests/test_passwort_reset.py -q`
Expected: FAIL (die DB lehnt `art='willkommen'` ab, `WILLKOMMEN_BETREFF` fehlt).

- [ ] **Step 2: Texte und Gültigkeit in `passwort_reset.py`**

Nach `GUELTIG_S = 30 * 60` einfügen:

```python

# Willkommensmail (24.09.2026): 7 Tage, weil ein neuer Mensch die Mail
# nicht zwingend am selben Tag liest. Derselbe Token-Mechanismus, derselbe
# Link auf /passwort-neu - nur laenger gueltig.
WILLKOMMEN_GUELTIG_S = 7 * 24 * 3600
```

Am Dateiende anfügen:

```python


WILLKOMMEN_BETREFF = "Dein Zugang zur sales-claw-Oberflaeche"


def willkommenstext(name: str, link: str) -> str:
    """Fester Text, wie mailtext: kein Parameter fuer freien Inhalt."""
    return (
        f"Hallo,\n\n"
        f"fuer dich wurde ein Zugang zur sales-claw-Oberflaeche eingerichtet.\n"
        f"Dein Benutzername: {name}\n\n"
        f"Hier legst du dein Passwort fest:\n\n"
        f"{link}\n\n"
        f"Der Link gilt {WILLKOMMEN_GUELTIG_S // 86400} Tage und genau einmal.\n"
        f"Danach meldest du dich mit Benutzername und Passwort an.\n")
```

- [ ] **Step 3: `verarbeite_kontomail` kennt beide Arten**

In `sales-mcp/mail_dispatch.py`, `verarbeite_kontomail`: den Block

```python
    if zettel["art"] != "passwort_reset":
        return _schliessen("fehler", "unbekannte Art: %s" % zettel["art"])
```

ersetzen durch:

```python
    arten = {
        "passwort_reset": (passwort_reset.GUELTIG_S, passwort_reset.BETREFF,
                           passwort_reset.mailtext),
        "willkommen": (passwort_reset.WILLKOMMEN_GUELTIG_S,
                       passwort_reset.WILLKOMMEN_BETREFF,
                       passwort_reset.willkommenstext),
    }
    if zettel["art"] not in arten:
        return _schliessen("fehler", "unbekannte Art: %s" % zettel["art"])
    gueltig_s, betreff, text = arten[zettel["art"]]
```

Im `update benutzer set reset_hash`-Aufruf `passwort_reset.GUELTIG_S` durch `gueltig_s` ersetzen. Den `try`-Block ersetzen durch:

```python
    try:
        ident = system_identitaet()
        nachricht = nachricht_bauen(
            konto["email"], betreff,
            text(konto["name"],
                 passwort_reset.link_bauen(UI_BASIS_URL, konto["name"],
                                           klartext)),
            absender=ident.absender)
        senden(nachricht, identitaet=ident)
```

Die Logzeile `"Passwort-Link versendet an %s"` wird zu `"Konto-Mail (%s) versendet an %s", zettel["art"], _maskiert(konto["email"])`.

- [ ] **Step 4: Datenbank — neue Art, neue Läden bekommen die Tabelle**

In `db/provision.sql`, in der Schleife je Laden direkt nach der Zeile mit `benutzer_mails_offen_idx` (`'on %I.benutzer_mails (status, erstellt_am)', s);`) einfügen:

```sql
    -- Willkommensmail (24.09.2026). Drop+Add, weil ein CHECK sich nicht
    -- nachruesten laesst; idempotent wie drafts_channel_check.
    execute format('alter table %I.benutzer_mails drop constraint if exists benutzer_mails_art_check', s);
    execute format($chk$alter table %I.benutzer_mails add constraint benutzer_mails_art_check
      check (art in ('passwort_reset','willkommen'))$chk$, s);
```

In `db/laden-anlegen.sql` nach der Zeile `create table if not exists :"schema".kalender_quellen ...` einfügen:

```sql
-- Konto-Mails (24.09.2026). Fehlte bisher: ein neuer Laden hatte keine
-- benutzer_mails, "Passwort vergessen" legte seinen Zettel ins Leere (Ivan
-- bekam sie erst durch einen spaeteren provision.sql-Lauf, die Rechte von
-- Hand). `like ... including all` uebernimmt den art-CHECK des Basis-Ladens.
create table if not exists :"schema".benutzer_mails   (like sales.benutzer_mails   including all);
```

und nach `grant select, insert, update on :"schema".kalender_quellen to :"rolle";`:

```sql
grant select, insert, update on :"schema".benutzer_mails   to :"rolle";
```

- [ ] **Step 5: Test-DB neu provisionieren, Tests grün**

Run: `docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql`
Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest tests/test_passwort_reset.py tests/test_mail_dispatch.py -q`
Expected: alle grün.

Prüfen, dass die neue `laden-anlegen.sql`-Zeile den erweiterten CHECK wirklich mitnimmt (dieselbe `like`-Anweisung in einem Wegwerf-Schema):

```bash
docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
create schema sales_planprobe;
create table sales_planprobe.benutzer_mails (like sales.benutzer_mails including all);
select pg_get_constraintdef(oid) from pg_constraint
 where conrelid = 'sales_planprobe.benutzer_mails'::regclass and contype = 'c';
drop schema sales_planprobe cascade;
SQL
```

Expected: eine Zeile `CHECK ((art = ANY (ARRAY['passwort_reset'::text, 'willkommen'::text])))` neben dem Status-CHECK.

- [ ] **Step 6: Volle Suite, dann Commit**

Run: `docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest -q`

```bash
git add sales-mcp/passwort_reset.py sales-mcp/mail_dispatch.py db/provision.sql db/laden-anlegen.sql sales-mcp/tests/test_passwort_reset.py
git commit -m "feat(sales-claw): Willkommensmail als zweite Konto-Mail-Art, neue Laeden bekommen benutzer_mails"
```

---

### Task 3: „Laden anlegen" nimmt eine private Adresse an

**Files:**
- Modify: `sales-mcp/ui.py` (`_admin_auftrag_ergebnis_text`, `laden_anlegen_seite`, `aktion_laden_anlegen`)
- Modify: `db/provision.sql` (`admin_auftraege_email_check`)
- Modify: `sales-mcp/tests/test_laden_anlegen_seite.py`
- Modify: `sales-mcp/tests/test_admin_auftraege_tabelle.py`

**Interfaces:**
- Produces: `admin_auftraege.email` bei `art='laden_anlegen'` optional, falls gesetzt gültig. Erwartete Form von `ergebnis` bei Erfolg mit Adresse (Task 4 schreibt sie): `{"willkommen": {"an": "<adresse>", "status": "<text>"}, "port_ui": N, "port_serve": N, "hinweis": "..."}`, ohne `"passwort"`.

- [ ] **Step 1: Tests schreiben (rot)**

Am Ende von `sales-mcp/tests/test_laden_anlegen_seite.py` anfügen:

```python
def test_gute_adresse_wird_mitgespeichert():
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "email": "lena@privat.example",
               "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    z = server._q("select name, email from admin_auftraege")[0]
    assert z == {"name": "lena", "email": "lena@privat.example"}


@pytest.mark.parametrize("schlecht", ["keine-adresse", "a@b", "x y@z.de"])
def test_schlechte_adresse_wird_abgewiesen(schlecht):
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "email": schlecht, "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 400
    assert server._q("select count(*) as n from admin_auftraege")[0]["n"] == 0


def test_ohne_adresse_bleibt_alles_wie_bisher():
    r = _post("/team/laden-anlegen/anfordern",
              {"name": "lena", "email": "", "csrf": ui.CSRF_TOKEN})
    assert r.status_code == 303
    assert server._q("select email from admin_auftraege")[0]["email"] is None
    server._q(
        "update admin_auftraege set status = 'erfolg', erledigt_am = now(), "
        "ergebnis = %s::jsonb returning id",
        ('{"passwort": "Probe-ABC", "port_serve": 8446, "hinweis": "h"}',))
    assert "Probe-ABC" in _get("/team/laden-anlegen").text


def test_mit_willkommensmail_wird_kein_passwort_angezeigt():
    server._q(
        "insert into admin_auftraege (art, name, email, angefordert_von, "
        "status, ergebnis, erledigt_am) values ('laden_anlegen', 'lena', "
        "'lena@privat.example', 'test', 'erfolg', %s::jsonb, now())",
        ('{"willkommen": {"an": "lena@privat.example", "status": "verschickt"},'
         ' "port_serve": 8446, "hinweis": "h"}',))
    text = _get("/team/laden-anlegen").text
    assert "Willkommensmail an lena@privat.example: verschickt" in text
    assert "Wegwerf-Passwort" not in text
```

In `sales-mcp/tests/test_admin_auftraege_tabelle.py` anfügen:

```python
def test_laden_anlegen_mit_kaputter_adresse_scheitert_am_check():
    with server.pool.connection() as conn:
        hat_sqlstate = False
        try:
            conn.execute(
                "insert into admin_auftraege (art, name, email, angefordert_von) "
                "values ('laden_anlegen', 'lena', 'keine adresse', 'test')")
        except Exception as e:
            hat_sqlstate = "23514" in str(getattr(e, "sqlstate", "") or e)
        assert hat_sqlstate
        conn.rollback()


def test_laden_anlegen_ohne_adresse_bleibt_erlaubt():
    with server.pool.connection() as conn:
        conn.execute(
            "insert into admin_auftraege (art, name, angefordert_von) "
            "values ('laden_anlegen', 'lena', 'test')")
        conn.rollback()
```

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest tests/test_laden_anlegen_seite.py tests/test_admin_auftraege_tabelle.py -q`
Expected: FAIL.

- [ ] **Step 2: CHECK erweitern**

In `db/provision.sql`, im `admin_auftraege`-Block, die zwei Zeilen

```sql
    execute format($chk$alter table %I.admin_auftraege add constraint
      admin_auftraege_email_check
      check (art <> 'tailscale_einladen'
             or (email is not null
                 and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'))$chk$, s);
```

ersetzen durch:

```sql
    -- Seit 24.09.2026 darf auch 'laden_anlegen' eine Adresse tragen (die
    -- Willkommensmail) - optional, aber wenn, dann gueltig. Pflicht bleibt
    -- sie nur fuer 'tailscale_einladen'.
    execute format($chk$alter table %I.admin_auftraege add constraint
      admin_auftraege_email_check
      check ((email is null and art <> 'tailscale_einladen')
             or (email is not null
                 and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'))$chk$, s);
```

Dann: `docker exec -i sales-testdb psql -U postgres -v ON_ERROR_STOP=1 < db/provision.sql`

- [ ] **Step 3: Formular, Aktion, Anzeige**

In `laden_anlegen_seite` im `rumpf` die Zeile `'required placeholder="z. B. lena"></label> '` ersetzen durch:

```python
        'required placeholder="z. B. lena"></label> '
        '<label>Private E-Mail-Adresse (optional — bekommt eine '
        'Willkommensmail mit Link zum Passwort-Setzen)<br>'
        '<input type="email" name="email" '
        'placeholder="z. B. lena@example.com"></label> '
```

In `aktion_laden_anlegen` direkt vor `server._q(` (dem Insert) einfügen:

```python
    email = None
    roh = str(form.get("email") or "").strip()
    if roh:
        email, fehler = mailadresse.pruefe(roh)
        if fehler:
            return _fehlerseite(
                400, "Ungültige E-Mail-Adresse",
                f"{fehler}. Nichts wurde angelegt.")
```

und den Insert ersetzen durch:

```python
    server._q(
        "insert into admin_auftraege (art, name, email, angefordert_von) "
        "values ('laden_anlegen', %s, %s, %s) returning id",
        (name, email, _ui_akteur(request)))
```

In `_admin_auftrag_ergebnis_text` die letzte `return`-Anweisung (Wegwerf-Passwort) ersetzen durch:

```python
    port = _e(str(info.get("port_serve", "?")))
    hinweis = _e(info.get("hinweis", ""))
    willkommen = info.get("willkommen")
    if willkommen:
        return (f"Willkommensmail an {_e(willkommen.get('an', '?'))}: "
                f"{_e(willkommen.get('status', '?'))}. "
                f"Serve-Port: {port}. {hinweis}")
    return (f"Wegwerf-Passwort: {_e(info.get('passwort', '?'))} — "
            f"Serve-Port: {port}. {hinweis}")
```

- [ ] **Step 4: Tests grün, volle Suite, Commit**

Run: `docker build -t sales-mcp:dev sales-mcp && docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest tests/test_laden_anlegen_seite.py tests/test_admin_auftraege_tabelle.py tests/test_tailscale_einladen_seite.py tests/test_darstellung.py -q`
Run: `docker run --rm --env-file .env -e SALES_DB_SCHEMA=sales_test sales-mcp:dev python -m pytest -q`
Expected: alle grün.

```bash
git add sales-mcp/ui.py db/provision.sql sales-mcp/tests/test_laden_anlegen_seite.py sales-mcp/tests/test_admin_auftraege_tabelle.py
git commit -m "feat(sales-claw): Laden anlegen nimmt optional eine private Adresse fuer die Willkommensmail"
```

---

### Task 4: Orchestrator, Umgebungsdatei, Compose, Runbook

**Files:**
- Modify: `deploy/admin-auftrag-ausfuehren.sh` (Zweig `laden_anlegen`, Schritte 5-7)
- Modify: `deploy/laden-anlegen.sh` (Heredoc der Umgebungsdatei)
- Modify: `docker-compose.yml` (Dienst `sales-mail`, `environment:`)
- Modify: `docs/03_RUNBOOK.md` (Abschnitt 7)

**Interfaces:**
- Consumes: `EINLADEN_EMAIL` (in Schritt 1 des Skripts schon aus `admin_auftraege.email` gelesen), `benutzer_mails` mit `art='willkommen'` im neuen Schema (Task 2), `ergebnis`-Form aus Task 3.

- [ ] **Step 1: Drei Dienste statt zwei**

In `deploy/admin-auftrag-ausfuehren.sh` den Kommentar-Kopf `# --- 5. Nur die zwei Dienste ohne externe Zugangsdaten ---` und den Aufruf ersetzen:

```bash
  # --- 5. Die drei Dienste ohne Kundenzugangsdaten --------------------------
  # sales-mail seit 24.09.2026: er verschickt Konto-Mails ueber die
  # Betreiber-Identitaet (SYSTEM_*), Kundenentwuerfe erst, wenn das Postfach
  # des Ladens eingetragen ist. DIENSTSCHLUESSEL bleiben woertlich.
  docker compose --env-file "$ENVDATEI" up -d --build sales-mcp sales-ui sales-mail \
    >/dev/null
```

- [ ] **Step 2: Adresse ins Konto, Zettel ins neue Schema, auf den Versand warten**

Direkt nach `ERLEDIGT+=("konto")` einfügen:

```bash

  # --- 6b. Willkommensmail (24.09.2026) -------------------------------------
  # Nur mit Adresse. Geschrieben wird ins Schema des NEUEN Ladens - das darf
  # nur der Wirt (supabase_admin), nie die Oberflaeche des Basis-Ladens.
  # Name und Adresse sind keine Geheimnisse; psql -v quotet sie per :'…'.
  WILLKOMMEN_STATUS=""
  if [ -n "$EINLADEN_EMAIL" ]; then
    ZETTEL_ID="$(psql_admin -tAq -v schema="sales_$LADEN_NAME" \
        -v name="$LADEN_NAME" -v mail="$EINLADEN_EMAIL" <<'SQL' | head -n1
update :"schema".benutzer set email = :'mail' where name = :'name';
insert into :"schema".benutzer_mails (benutzer, art)
  values (:'name', 'willkommen') returning id;
SQL
)"
    ERLEDIGT+=("willkommen-zettel")
    # Der Dienst wurde eben erst gestartet und fragt alle 10 s ab. Bis zu
    # 60 s warten; was danach noch offen ist, meldet die Seite ehrlich so.
    WILLKOMMEN_STATUS="noch unterwegs"
    # Abfrage als Heredoc, nicht per -c: psql setzt :"schema"/:'id' nur in
    # Eingabe von stdin/Datei ein, nicht in einem -c-Befehl.
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
      STAND="$(psql_admin -tAq -v schema="sales_$LADEN_NAME" -v id="$ZETTEL_ID" \
        2>/dev/null <<'SQL' || true
select status || chr(31) || grund from :"schema".benutzer_mails where id = :'id'::uuid;
SQL
)"
      case "${STAND%%$'\037'*}" in
        gesendet) WILLKOMMEN_STATUS="verschickt"; break ;;
        fehler)   WILLKOMMEN_STATUS="fehlgeschlagen: ${STAND#*$'\037'}"; break ;;
      esac
      sleep 5
    done
  fi
```

- [ ] **Step 3: Ergebnis mit Mailstatus statt Passwort**

Den `ERGEBNIS_JSON`-Aufruf in Schritt 7 ersetzen durch:

```bash
  ERGEBNIS_JSON="$(KONTO_PW="$KONTO_PW" WILLKOMMEN_AN="$EINLADEN_EMAIL" \
    WILLKOMMEN_STATUS="$WILLKOMMEN_STATUS" python3 -c '
import json, os, sys
ui_port, serve_port = sys.argv[1], sys.argv[2]
ergebnis = {
    "port_ui": int(ui_port),
    "port_serve": int(serve_port),
    "hinweis": ("Als naechstes von Hand: tailscale serve --https " +
                serve_port + " http://127.0.0.1:" + ui_port +
                " einrichten, danach die Zugriffsregel fuer den neuen "
                "Menschen und die vier Kanaele (Postfach, Telegram, "
                "LinkedIn, WhatsApp)."),
}
# Mit Willkommensmail kennt NIEMAND das Wegwerf-Passwort - es wird nicht
# angezeigt, der Mensch setzt sein eigenes ueber den Link.
if os.environ["WILLKOMMEN_AN"]:
    ergebnis["willkommen"] = {"an": os.environ["WILLKOMMEN_AN"],
                              "status": os.environ["WILLKOMMEN_STATUS"]}
else:
    ergebnis["passwort"] = os.environ["KONTO_PW"]
print(json.dumps(ergebnis))' "$PORT_UI" "$PORT_SERVE")"
```

- [ ] **Step 4: Umgebungsdatei und Compose**

In `deploy/laden-anlegen.sh` direkt vor `cat > "$ENVDATEI" <<EOF` einfügen:

```bash
# Betreiber-Identitaet fuer Konto-Mails (24.09.2026): die SMTP_*-Werte des
# Basis-Ladens, woertlich uebernommen (nur \r entfernt - ein Passwort darf
# Leerzeichen tragen). Sie landen NUR als SYSTEM_* in dieser Datei; die
# SMTP_* des neuen Ladens bleiben leer, bis sein eigenes Postfach steht -
# bis dahin verschickt <laden>-mail ausschliesslich Konto-Mails.
basis_wert() { grep -E "^$1=" "$WURZEL/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }
SYS_HOST="$(basis_wert SMTP_HOST)"; SYS_PORT="$(basis_wert SMTP_PORT)"
SYS_USER="$(basis_wert SMTP_USER)"; SYS_PASSWORT="$(basis_wert SMTP_PASSWORT)"
SYS_ABSENDER="$(basis_wert EMAIL_ABSENDER)"
if [ -z "$SYS_HOST" ] || [ -z "$SYS_USER" ] || [ -z "$SYS_PASSWORT" ] || [ -z "$SYS_ABSENDER" ]; then
  echo "WARNUNG: SMTP_* des Basis-Ladens unvollstaendig in $WURZEL/.env —" \
       "$NAME-mail kann keine Konto-Mails verschicken." >&2
fi
```

Im Heredoc nach der Zeile `MEDIEN_ERZEUGT_ORDNER=./laeden-daten/$NAME/media-erzeugt` einfügen:

```
# Konto-Mails ueber die Adresse des Betreibers (Spec 2026-09-24).
SYSTEM_SMTP_HOST=$SYS_HOST
SYSTEM_SMTP_PORT=${SYS_PORT:-587}
SYSTEM_SMTP_USER=$SYS_USER
SYSTEM_SMTP_PASSWORT=$SYS_PASSWORT
SYSTEM_ABSENDER=$SYS_ABSENDER
```

In `docker-compose.yml`, Dienst `sales-mail`, nach `- EMAIL_ABSENDER=${EMAIL_ABSENDER:-}` einfügen:

```yaml
      # Betreiber-Identitaet NUR fuer Konto-Mails (Spec 2026-09-24). Nur
      # dieser Dienst bekommt sie - nie sales-ui/sales-mcp (T5a).
      - SYSTEM_SMTP_HOST=${SYSTEM_SMTP_HOST:-}
      - SYSTEM_SMTP_PORT=${SYSTEM_SMTP_PORT:-587}
      - SYSTEM_SMTP_USER=${SYSTEM_SMTP_USER:-}
      - SYSTEM_SMTP_PASSWORT=${SYSTEM_SMTP_PASSWORT:-}
      - SYSTEM_ABSENDER=${SYSTEM_ABSENDER:-}
```

- [ ] **Step 5: Prüfen**

1. `bash -n deploy/admin-auftrag-ausfuehren.sh && bash -n deploy/laden-anlegen.sh`
2. T5a: `docker compose --env-file /dev/null config` darf `SYSTEM_SMTP_PASSWORT` nur im Block von `sales-mail` zeigen:
   `docker compose --env-file /dev/null config | awk '/^  [a-z-]+:$/{d=$1} /SYSTEM_SMTP_PASSWORT/{print d}'` → genau `sales-mail:`.
3. Den neuen SQL-Block von Step 2 (Update, Insert, Heredoc-Abfrage) wörtlich gegen die Test-DB laufen lassen, mit `-v schema=sales_test`, einem vorher angelegten Testkonto `lena` und `mail=lena@privat.example`: Die Ausgabe ist genau eine UUID (dank `-tAq` und `head -n1`), die Abfrage liefert `offen` und den Trenner. Danach aufräumen: `truncate sales_test.benutzer, sales_test.benutzer_mails`.
4. Die `laden-anlegen.sh`-Ergänzung isoliert prüfen: In einem Wegwerf-Verzeichnis mit Fake-`.env` (`SMTP_PASSWORT=pa ss word`) die Funktion `basis_wert` ausführen. `pa ss word` muss unverändert herauskommen.
5. Das `ERGEBNIS_JSON`-Python einmal mit und einmal ohne `WILLKOMMEN_AN` ausführen. Mit Adresse steht kein `"passwort"` im JSON, ohne Adresse schon.

- [ ] **Step 6: Runbook**

In `docs/03_RUNBOOK.md`, Abschnitt „7. Laden anlegen aus der Oberfläche", unter „#### Weg" nach Schritt 3 einen Schritt einfügen: „Optional die private E-Mail-Adresse des neuen Menschen eintragen. Er bekommt von der Betreiber-Adresse eine Willkommensmail mit Link zum Passwort-Setzen (7 Tage gültig). Dann erscheint auf der Ergebnisseite **kein** Wegwerf-Passwort, sondern der Versandstatus (verschickt / fehlgeschlagen: Grund / noch unterwegs)." Außerdem einen kurzen Absatz „#### Konto-Mails in jedem Laden": Jeder Laden hat `<laden>-mail`. Konto-Mails gehen über `SYSTEM_*` (Betreiber), Kundenentwürfe nur über die eigenen `SMTP_*` und bleiben ohne sie liegen.

- [ ] **Step 7: Commit**

```bash
git add deploy/admin-auftrag-ausfuehren.sh deploy/laden-anlegen.sh docker-compose.yml docs/03_RUNBOOK.md
git commit -m "feat(sales-claw): jeder Laden bekommt einen Mail-Dienst, Laden anlegen verschickt die Willkommensmail"
```

---

### Task 5: Rollout auf der VM (nur mit Freigabe des Betreibers)

Kein Subagent. Der Controller führt das mit dem Betreiber aus.

- [ ] **Step 1:** WORKBOARD-Claim setzen. Auf der VM `git pull --ff-only`, dann **sofort** `db/provision.sql` einspielen (sonst legt der Pull den Timer lahm, siehe 23.09.). Dann `sales-mail` und `sales-ui` des Basis-Ladens neu bauen und starten: `docker compose up -d --build sales-mail sales-ui`.
- [ ] **Step 2:** Basis-Laden abnehmen: Das Startlog von `sales-mail` zeigt `kundenmails=ja kontomails=ja (identitaet=kunde)`.
- [ ] **Step 3:** Ivan nachziehen: die fünf `SYSTEM_*`-Zeilen per Pipe (nie ausgeben) aus den `SMTP_*` der VM-`.env` an `deploy/laeden/ivan.env` anhängen. Für `sales_ivan` einmal den `benutzer_mails`-CHECK prüfen (kommt aus `provision.sql`). Dann `docker compose --env-file deploy/laeden/ivan.env up -d --build sales-mail`. Das Startlog zeigt `kundenmails=nein — Entwuerfe bleiben liegen kontomails=ja (identitaet=system)`.
- [ ] **Step 4:** Echter Probelauf: Laden `probelauf` mit einer Adresse des Betreibers anlegen. Die Ergebnisseite zeigt „Willkommensmail an …: verschickt", die Mail kommt von felix@vibemind.space an. Über den Link wird ein Passwort gesetzt, die Anmeldung am Laden gelingt. Danach Abbau wie am 22.09.: Container inkl. `probelauf-mail`, Volumes, Schema, Rolle (vorher `compliance`-Rechte entziehen), Env-Datei, Wegwerf-Konto.
- [ ] **Step 5:** WORKBOARD-Eintrag, Claim schließen.
