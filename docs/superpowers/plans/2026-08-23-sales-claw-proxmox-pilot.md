# Sales-Claw Proxmox-Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den persönlichen Sales-Claw-Piloten reproduzierbar für die Docker-VM `offload-vm` vorbereiten, ohne in diesem Implementierungslauf Secrets zu übertragen, VM-Zustand zu verändern oder einen echten Dispatcher zu starten.

**Architecture:** Ein dritter Compose-Layer enthält ausschließlich VM-spezifische Restart-Policies. Kleine, lokal testbare Python-Werkzeuge erstellen ein geheimnisfreies Quellpaket und prüfen die Remote-Voraussetzungen read-only. OpenWA erhält wegen seines eigenen Volumes ein separates, manifestiertes Backup. Ein Runbook hält den späteren Cutover als Folge expliziter Gates fest; die reale Migration bleibt eine separate, vom Betreiber bestätigte Operation.

**Tech Stack:** Docker Compose v2, Python 3.12, pytest, PyYAML, PowerShell 7, Docker/Alpine, OpenWA, Tailscale, SSH/SCP.

**Spec:** `docs/superpowers/specs/2026-08-23-sales-claw-proxmox-pilot-design.md`

## Global Constraints

- Der vorhandene schmutzige Arbeitsbaum ist fremder bzw. bereits begonnener Pilotstand. Keine vorhandene Änderung verwerfen, pauschal stagen oder zusammen mit den hier geplanten Dateien committen.
- Jeder Commit enthält ausschließlich die in seinem Task genannten Dateien und verwendet Conventional Commits.
- Kein Tool dieses Plans darf `.env` lesen, ausgeben oder in ein Paket aufnehmen.
- Keine VM-Mutation, kein `scp`, kein Restore, keine Tailscale-Installation und kein Start von `sales-linkedin` während der Implementierung dieses Plans.
- `sales-claw` und `sales-auto` behalten `restart: "no"`. Alle anderen in der Spec genannten Pilotdienste erhalten `unless-stopped`.
- Die UI darf nur an `127.0.0.1` und eine ausdrücklich gesetzte Tailscale-IP gebunden werden. Ein Wildcard-Binding ist ein harter Fehler.
- Remote-Prüfungen sind read-only. Ein Speicherproblem wird gemeldet, nicht durch Entfernen fremder Images, Container oder Volumes behoben.
- Der spätere Start der Dispatcher erfolgt einzeln und erst nach einer metadata-only Queue-Zählung. Der LinkedIn-Start bleibt ein eigenes Aktions-Gate für den bereits genehmigten Post.
- Nach jedem Task zuerst den fokussierten Test ausführen, dann sofort den Task abhaken und den engen Commit erstellen.

---

## Task 1: VM-spezifischen Compose-Vertrag festschreiben

**Files:**

- Create: `docker-compose.proxmox.yml`
- Create: `scripts/tests/test_proxmox_compose.py`
- Modify: `.env.example`

- [ ] **Step 1: RED-Test für Restart-Matrix, OpenWA-Autostart und Netzbindung schreiben**

  `scripts/tests/test_proxmox_compose.py` lädt die tatsächlich zusammengeführte Compose-Konfiguration. Es verwendet nur Dummy-Werte und gibt das gerenderte JSON bei Erfolg oder Fehler niemals aus:

  ```python
  from __future__ import annotations

  import json
  import os
  import subprocess
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[2]
  COMPOSE_FILES = (
      ROOT / "docker-compose.yml",
      ROOT / "docker-compose.openwa.yml",
      ROOT / "docker-compose.proxmox.yml",
  )


  def rendered_config() -> dict[str, object]:
      env = os.environ.copy()
      env.update(
          {
              "SALES_DB_URL": "postgresql://pilot:pilot@db.invalid:5432/pilot",
              "OPENROUTER_API_KEY": "test-only",
              "OPENWA_API_KEY": "test-only",
              "OPENWA_SESSION_ID": "00000000-0000-0000-0000-000000000000",
              "INBOX_WEBHOOK_SECRET": "test-only",
              "LINKEDIN_ACCESS_TOKEN": "test-only",
              "LINKEDIN_PERSON_URN": "urn:li:person:test-only",
              "LINKEDIN_API_VERSION": "202608",
              "UI_TAILSCALE_IP": "100.64.0.10",
          }
      )
      command = ["docker", "compose", "--env-file", str(ROOT / ".env.example")]
      for compose_file in COMPOSE_FILES:
          command.extend(("-f", str(compose_file)))
      command.extend(("config", "--format", "json"))
      completed = subprocess.run(
          command,
          cwd=ROOT,
          env=env,
          text=True,
          capture_output=True,
          check=False,
      )
      assert completed.returncode == 0, "Compose-Konfiguration ist ungueltig"
      return json.loads(completed.stdout)


  def test_restart_matrix_is_fail_closed() -> None:
      services = rendered_config()["services"]
      automatic = {
          "openwa",
          "sales-mcp",
          "sales-ui",
          "sales-inbox",
          "sales-dispatch",
          "sales-mail",
          "sales-linkedin",
      }
      assert all(services[name]["restart"] == "unless-stopped" for name in automatic)
      assert services["sales-claw"]["restart"] == "no"
      assert services["sales-auto"]["restart"] == "no"
      assert services["openwa"]["environment"]["AUTO_START_SESSIONS"] == "true"


  def test_ui_has_only_loopback_and_tailscale_bindings() -> None:
      ports = rendered_config()["services"]["sales-ui"]["ports"]
      host_ips = {port["host_ip"] for port in ports}
      assert host_ips == {"127.0.0.1", "100.64.0.10"}
      assert all(port["published"] == "8791" for port in ports)
  ```

- [ ] **Step 2: Test ausführen und erwartetes RED belegen**

  Run: `python -m pytest scripts/tests/test_proxmox_compose.py -q`

  Expected: FAIL, weil `docker-compose.proxmox.yml` noch nicht existiert.

- [ ] **Step 3: Minimalen Compose-Override anlegen**

  `docker-compose.proxmox.yml` enthält keine Secrets und keine duplizierten Portdefinitionen:

  ```yaml
  services:
    openwa:
      restart: unless-stopped
      environment:
        AUTO_START_SESSIONS: "true"

    sales-mcp:
      restart: unless-stopped

    sales-ui:
      restart: unless-stopped

    sales-inbox:
      restart: unless-stopped

    sales-dispatch:
      restart: unless-stopped

    sales-mail:
      restart: unless-stopped

    sales-linkedin:
      restart: unless-stopped

    sales-claw:
      restart: "no"

    sales-auto:
      restart: "no"
  ```

  Die vorhandenen UI-Ports aus `docker-compose.yml` bleiben damit die einzige Quelle: Loopback plus `${UI_TAILSCALE_IP:-127.0.0.1}`.

- [ ] **Step 4: Beispielkonfiguration vollständig dokumentieren**

  Ergänze `.env.example` um diese wertlosen Beispiele und Kommentare:

  ```dotenv
  # Auf der Proxmox-VM nach `tailscale up` mit `tailscale ip -4` ermitteln.
  # Leer lassen bedeutet: zweites UI-Binding faellt ebenfalls auf Loopback zurueck.
  UI_TAILSCALE_IP=

  # LinkedIn-Werte werden nur vom approval-gated sales-linkedin Worker verwendet.
  LINKEDIN_ACCESS_TOKEN=
  LINKEDIN_PERSON_URN=
  LINKEDIN_API_VERSION=202608
  ```

- [ ] **Step 5: GREEN und Compose-Validierung ausführen**

  Run: `python -m pytest scripts/tests/test_proxmox_compose.py -q`

  Expected: `2 passed`.

  Run: `docker compose --env-file .env.example -f docker-compose.yml -f docker-compose.openwa.yml -f docker-compose.proxmox.yml config --quiet`

  Expected: exit 0. Falls zwingende Variablen fehlen, nur für diesen Prozess Dummy-Umgebungswerte setzen; niemals die echte `.env` ausgeben.

- [ ] **Step 6: Engen Commit erstellen**

  ```powershell
  git add -- docker-compose.proxmox.yml scripts/tests/test_proxmox_compose.py .env.example
  git commit -m "feat: add proxmox compose profile"
  ```

---

## Task 2: Geheimnisfreies, manifestiertes Quellpaket bauen

**Files:**

- Create: `scripts/package_proxmox.py`
- Create: `scripts/tests/test_package_proxmox.py`
- Modify: `.gitignore`

- [ ] **Step 1: RED-Tests für Positivliste und reproduzierbares Manifest schreiben**

  Die Tests bauen einen temporären Mini-Workspace. Sie müssen beweisen, dass `.env`, `.git`, Backups, Cache-Verzeichnisse, `graphify-out` und `.superpowers` nicht im Archiv landen und dass ungetrackte, aber erlaubte Pilotdateien aufgenommen werden:

  ```python
  from __future__ import annotations

  import json
  import tarfile
  from pathlib import Path

  from scripts.package_proxmox import build_package


  def test_package_uses_allowlist_and_excludes_secrets(tmp_path: Path) -> None:
      root = tmp_path / "repo"
      output = tmp_path / "out"
      (root / ".git").mkdir(parents=True)
      (root / "sales-mcp").mkdir()
      (root / "openwa" / "upstream").mkdir(parents=True)
      (root / "graphify-out").mkdir()
      (root / "sales-mcp" / "linkedin_dispatch.py").write_text("pilot", encoding="utf-8")
      (root / "openwa" / "upstream" / "package.json").write_text("{}", encoding="utf-8")
      (root / ".env").write_text("SECRET=real", encoding="utf-8")
      (root / "graphify-out" / "graph.json").write_text("private", encoding="utf-8")

      archive_path, manifest_path = build_package(root, output)

      with tarfile.open(archive_path, "r:gz") as archive:
          names = set(archive.getnames())
      assert "sales-mcp/linkedin_dispatch.py" in names
      assert "openwa/upstream/package.json" in names
      assert ".env" not in names
      assert not any(name.startswith((".git/", "graphify-out/")) for name in names)
      manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
      assert manifest["archive_sha256"]
      assert manifest["archive_bytes"] == archive_path.stat().st_size
      assert manifest["files"] == sorted(manifest["files"])
  ```

- [ ] **Step 2: Test ausführen und erwartetes RED belegen**

  Run: `python -m pytest scripts/tests/test_package_proxmox.py -q`

  Expected: FAIL mit `ModuleNotFoundError`, weil `scripts/package_proxmox.py` fehlt.

- [ ] **Step 3: Paketierer mit festen Grenzen implementieren**

  Öffentliche Schnittstelle:

  ```python
  ALLOWED_ROOT_FILES = (
      ".env.example",
      "docker-compose.yml",
      "docker-compose.openwa.yml",
      "docker-compose.proxmox.yml",
  )
  ALLOWED_ROOT_DIRS = (
      "config",
      "db",
      "docs",
      "media",
      "reports",
      "sales-mcp",
      "scripts",
      "openwa/upstream",
  )
  EXCLUDED_PARTS = {
      ".git",
      ".pytest_cache",
      ".superpowers",
      "__pycache__",
      "backups",
      "dist",
      "graphify-out",
      "node_modules",
  }


  def build_package(source_root: Path, output_dir: Path) -> tuple[Path, Path]:
      """Create a tar.gz and JSON manifest without following symlinks."""
  ```

  Zusätzliche harte Regeln:

  - `source_root/.git` muss existieren, damit nicht versehentlich ein beliebiger Ordner paketiert wird.
  - Dateien namens `.env`, `*.pem`, `*.key`, `*.p12` und Verzeichnisse `credentials-sicherung-*` werden unabhängig von ihrer Position abgewiesen.
  - Symlinks werden weder verfolgt noch aufgenommen.
  - Jeder Manifest-Eintrag enthält relativen POSIX-Pfad, Bytezahl und SHA-256.
  - Das Archiv erhält einen stabilen Namen `sales-claw-proxmox-source.tar.gz`; das Manifest `sales-claw-proxmox-source.MANIFEST.json` wird erst nach erfolgreichem Probeöffnen des Archivs geschrieben.
  - CLI: `python scripts/package_proxmox.py --source . --output artifacts/proxmox`.
  - Die CLI gibt nur Pfade, Bytezahl, Dateizahl und SHA-256 aus, niemals Dateiinhalte.

- [ ] **Step 4: Ausgabeordner ignorieren**

  Ergänze `.gitignore` exakt um:

  ```gitignore
  /artifacts/proxmox/
  ```

- [ ] **Step 5: GREEN und echten lokalen Paket-Probelauf ausführen**

  Run: `python -m pytest scripts/tests/test_package_proxmox.py -q`

  Expected: alle Tests bestanden.

  Run: `python scripts/package_proxmox.py --source . --output artifacts/proxmox`

  Expected: exit 0; Archiv und Manifest existieren. Danach mit einem kurzen Python-Lesecheck bestätigen, dass `.env` und die ausgeschlossenen Verzeichnisse fehlen, ohne Dateien zu entpacken.

- [ ] **Step 6: Engen Commit erstellen**

  ```powershell
  git add -- scripts/package_proxmox.py scripts/tests/test_package_proxmox.py .gitignore
  git commit -m "feat: package proxmox pilot safely"
  ```

---

## Task 3: Read-only Preflight für `offload-vm` implementieren

**Files:**

- Create: `scripts/proxmox_preflight.py`
- Create: `scripts/tests/test_proxmox_preflight.py`

- [ ] **Step 1: RED-Tests gegen einen injizierten SSH-Runner schreiben**

  Die Kernlogik darf SSH nicht fest verdrahten. Der Test speist benannte Antworten ein und prüft mindestens Speicher, Tailscale, Port, Zielpfad und Ressourcenkollisionen:

  ```python
  from __future__ import annotations

  from scripts.proxmox_preflight import PreflightError, evaluate


  def healthy_probe(command: str) -> str:
      answers = {
          "docker version --format '{{.Server.Version}}'": "29.6.1",
          "docker compose version --short": "5.3.1",
          "df -Pk / | awk 'NR==2 {print $4}'": "20971520",
          "command -v tailscale >/dev/null && tailscale ip -4": "100.64.0.10",
          "ss -H -ltn 'sport = :8791'": "",
          "test ! -e /home/debian/sales-claw && echo absent": "absent",
          "docker ps -a --format '{{.Names}}'": "foreign-service",
          "docker volume ls --format '{{.Name}}'": "foreign-volume",
      }
      return answers[command]


  def test_healthy_host_passes_without_mutation() -> None:
      report = evaluate(healthy_probe, min_free_gib=10, ui_port=8791)
      assert report.tailscale_ipv4 == "100.64.0.10"
      assert report.free_gib >= 10


  def test_low_disk_space_fails_closed() -> None:
      def low_space(command: str) -> str:
          if command.startswith("df -Pk"):
              return "4194304"
          return healthy_probe(command)

      try:
          evaluate(low_space, min_free_gib=10, ui_port=8791)
      except PreflightError as error:
          assert "10 GiB" in str(error)
      else:
          raise AssertionError("low disk space must fail")
  ```

  Weitere Tests:

  - fehlendes Tailscale oder leere IPv4 schlägt fehl;
  - ein Listener auf 8791 schlägt fehl;
  - `/home/debian/sales-claw` vorhanden schlägt beim initialen Cutover fehl;
  - Namen `sales-claw`, `sales-mcp`, `sales-ui`, `sales-inbox`, `sales-dispatch`, `sales-mail`, `sales-linkedin`, `sales-auto` oder `openwa` in der Containerliste schlagen fehl;
  - Volumes `sales-claw-state`, `sales-claw-keys` oder `openwa-data` schlagen fehl;
  - fremde Container und Volumes werden nur gezählt, nicht als Fehler behandelt.

- [ ] **Step 2: Test ausführen und erwartetes RED belegen**

  Run: `python -m pytest scripts/tests/test_proxmox_preflight.py -q`

  Expected: FAIL mit `ModuleNotFoundError`.

- [ ] **Step 3: Prüfer und sichere CLI implementieren**

  Öffentliche Schnittstellen:

  ```python
  from collections.abc import Callable
  from dataclasses import dataclass

  Runner = Callable[[str], str]


  @dataclass(frozen=True)
  class PreflightReport:
      docker_version: str
      compose_version: str
      free_gib: float
      tailscale_ipv4: str
      foreign_container_count: int
      foreign_volume_count: int


  class PreflightError(RuntimeError):
      pass


  def evaluate(run_remote: Runner, *, min_free_gib: int, ui_port: int) -> PreflightReport:
      """Evaluate exact read-only probes and raise on the first unsafe gate."""
  ```

  CLI-Vertrag:

  ```text
  python scripts/proxmox_preflight.py --host offload-vm --min-free-gib 10 --ui-port 8791
  ```

  Die CLI verwendet `subprocess.run(["ssh", host, command], capture_output=True, text=True)` ohne Shell auf Windows. Sie erlaubt als Host nur ein einzelnes SSH-Alias-/Hostname-Token (`[A-Za-z0-9._-]+`). Ausgabe enthält ausschließlich Versionsnummern, freien Speicher, Tailscale-IP, Portstatus und Anzahlen; keine Umgebungswerte und keine fremden Ressourcennamen.

- [ ] **Step 4: GREEN und statischen Syntaxcheck ausführen**

  Run: `python -m pytest scripts/tests/test_proxmox_preflight.py -q`

  Expected: alle Tests bestanden.

  Run: `python -m py_compile scripts/proxmox_preflight.py`

  Expected: exit 0.

  Den echten `offload-vm`-Preflight in diesem Implementierungslauf nicht ausführen; das ist der erste Schritt des später autorisierten Cutovers.

- [ ] **Step 5: Engen Commit erstellen**

  ```powershell
  git add -- scripts/proxmox_preflight.py scripts/tests/test_proxmox_preflight.py
  git commit -m "feat: add read-only proxmox preflight"
  ```

---

## Task 4: `openwa-data` separat sichern und verifizieren

**Files:**

- Create: `scripts/backup-openwa.ps1`
- Create: `scripts/verify-openwa-backup.ps1`
- Create: `scripts/tests/test_openwa_backup.py`

- [ ] **Step 1: RED-Tests für Manifest-Verifikation schreiben**

  Der Python-Test erzeugt in einem temporären Ordner ein kleines `openwa.tar` und `MANIFEST.json`, übergibt dessen absoluten Pfad als Argument an `pwsh -File scripts/verify-openwa-backup.ps1 -Quelle` und prüft:

  - gültiges Archiv: exit 0;
  - veränderte Archivbytes: exit ungleich 0;
  - falscher Manifest-Volume-Name: exit ungleich 0;
  - fehlende Datei, Bytezahl, SHA-256 oder Dateizahl: exit ungleich 0;
  - zusätzliche Archive im Ordner: exit ungleich 0.

  Das Fixture-Manifest hat exakt dieses Schema:

  ```json
  {
    "schema": 1,
    "created_utc": "2026-08-23T12:00:00Z",
    "volume": "openwa-data",
    "archive": {
      "name": "openwa.tar",
      "bytes": 10240,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "entries": 1
    }
  }
  ```

- [ ] **Step 2: Test ausführen und erwartetes RED belegen**

  Run: `python -m pytest scripts/tests/test_openwa_backup.py -q`

  Expected: FAIL, weil das Verifikationsskript fehlt.

- [ ] **Step 3: Verifikationsskript fail-closed implementieren**

  `scripts/verify-openwa-backup.ps1`:

  - akzeptiert über `-Quelle` ausschließlich einen vorhandenen Ordner;
  - verlangt genau `MANIFEST.json` und `openwa.tar`;
  - verlangt `schema=1` und `volume=openwa-data`;
  - vergleicht Bytezahl und SHA-256 mit `Get-FileHash -Algorithm SHA256`;
  - prüft mit einem kurzlebigen `alpine:3.20`-Container, dass `tar -tf` erfolgreich ist und die gezählte Zahl der normalen Dateien dem Manifest entspricht;
  - mountet den Quellordner nur read-only;
  - verändert weder Volume noch Containerzustand;
  - gibt ausschließlich `openwa-data: verifiziert`, Bytezahl, Dateizahl und SHA-256 aus.

- [ ] **Step 4: Backupskript mit exakter Allowlist implementieren**

  `scripts/backup-openwa.ps1` orientiert sich am bestehenden `backup-state.ps1`, bleibt aber separat. Vertrag:

  ```powershell
  param(
      [Parameter(Mandatory = $true)]
      [string]$Ziel
  )

  $Volume = 'openwa-data'
  $Container = 'openwa'
  ```

  Ablauf:

  1. Docker-Verfügbarkeit und exakte Existenz von `openwa-data` prüfen.
  2. Ermitteln, ob Container `openwa` läuft; falls ja, sauber stoppen und den ursprünglichen Laufzustand für `finally` merken.
  3. In einen neu angelegten, leeren Zielordner mit `alpine:3.20` und read-only Volume-Mount `openwa.tar` schreiben.
  4. Archiv testweise listen, normale Dateien zählen, Bytezahl und SHA-256 berechnen.
  5. `MANIFEST.json` atomar zuletzt schreiben.
  6. `verify-openwa-backup.ps1` gegen den fertigen Ordner aufrufen.
  7. Den Container nur dann im `finally` wieder starten, wenn er vor dem Backup lief und der Operator nicht den Schalter `-StillgelegtLassen` gesetzt hat.

  Das Skript akzeptiert keine frei wählbaren Volume- oder Containernamen.

- [ ] **Step 5: GREEN und Parserprüfung ausführen**

  Run: `python -m pytest scripts/tests/test_openwa_backup.py -q`

  Expected: alle Tests bestanden.

  Run:

  ```powershell
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
      (Resolve-Path scripts/backup-openwa.ps1),
      [ref]$null,
      [ref]$errors
  )
  if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ } ; exit 1 }
  ```

  Expected: exit 0. Kein echtes `openwa-data`-Backup in diesem Task; das passiert erst am Cutover-Gate.

- [ ] **Step 6: Engen Commit erstellen**

  ```powershell
  git add -- scripts/backup-openwa.ps1 scripts/verify-openwa-backup.ps1 scripts/tests/test_openwa_backup.py
  git commit -m "feat: add verified openwa backup"
  ```

---

## Task 5: Bedienbares, fail-closed Cutover-Runbook schreiben

**Files:**

- Create: `docs/07_PROXMOX_PILOT.md`
- Modify: `scripts/tests/test_proxmox_compose.py`

- [ ] **Step 1: RED-Vertragstest für die zwingenden Runbook-Gates ergänzen**

  Ergänze Tests, die den Text als Betriebsvertrag behandeln:

  ```python
  RUNBOOK = ROOT / "docs" / "07_PROXMOX_PILOT.md"


  def test_runbook_contains_all_safety_gates() -> None:
      text = RUNBOOK.read_text(encoding="utf-8")
      required = (
          "python scripts/proxmox_preflight.py --host offload-vm --min-free-gib 10 --ui-port 8791",
          "scripts/backup-state.ps1",
          "scripts/backup-openwa.ps1",
          "chmod 600 .env",
          "docker-compose.proxmox.yml",
          "openwa sales-mcp sales-inbox sales-ui",
          "sales-dispatch",
          "sales-mail",
          "sales-linkedin",
          "sales-claw und sales-auto bleiben gestoppt",
      )
      assert all(fragment in text for fragment in required)
      assert "docker compose up -d" not in text


  def test_runbook_requires_queue_inventory_before_each_dispatcher() -> None:
      text = RUNBOOK.read_text(encoding="utf-8")
      assert text.count("approved-Queue nur als Anzahl") >= 3
      assert "LinkedIn-Aktions-Gate" in text
      assert "kein erneuter Versand" in text
  ```

- [ ] **Step 2: Test ausführen und erwartetes RED belegen**

  Run: `python -m pytest scripts/tests/test_proxmox_compose.py -q`

  Expected: FAIL, weil `docs/07_PROXMOX_PILOT.md` fehlt.

- [ ] **Step 3: Runbook mit nummerierten Stop-Gates schreiben**

  Das Dokument enthält exakt diese Phasen und jeweils einen klaren Abbruchzustand:

  1. **Preflight:** read-only Skript ausführen; mindestens 10 GiB frei, Tailscale-IPv4 vorhanden, Port/Projektpfad/Namen frei. Bei Rot keine weitere Aktion.
  2. **Lokale Backups:** `backup-state.ps1` für State/Keys und `backup-openwa.ps1 -StillgelegtLassen` für OpenWA. Beide Manifeste lokal vollständig prüfen.
  3. **Lokale Stilllegung:** UI und alle übrigen Projektcontainer stoppen; mit exakter Namensliste beweisen, dass nichts mehr läuft. OpenWA nicht wieder starten.
  4. **Quellpaket:** `package_proxmox.py` ausführen, Archiv gegen Manifest prüfen und nur Archiv plus Manifest übertragen.
  5. **Secrets-Gate:** erst nach erneuter Betreiberbestätigung `.env` separat per SCP übertragen; remote sofort `chmod 600 .env`; nur `test -s` und Dateimodus prüfen, niemals Inhalt ausgeben.
  6. **Archive-Transfer:** drei Archive/Manifeste übertragen, remote SHA-256 vor jeder Volume-Mutation vergleichen.
  7. **Restore:** exakt `sales-claw-state`, `sales-claw-keys`, `openwa-data` anlegen und befüllen; keine Globs und keine fremden Volumes. Bei Fehler keinen Dienst starten.
  8. **Compose-Check:** immer mit allen drei Dateien und `config --quiet`; die Standardbefehlsvariable im Runbook lautet:

     ```bash
     COMPOSE="docker compose -f docker-compose.yml -f docker-compose.openwa.yml -f docker-compose.proxmox.yml"
     ```

  9. **Core-Start:** ausschließlich `$COMPOSE up -d openwa sales-mcp sales-inbox sales-ui`; Health, DB-Lesezugriff, OpenWA-Session und UI über Tailscale prüfen.
  10. **Dispatcher-Gates:** vor `$COMPOSE up -d sales-dispatch`, `$COMPOSE up -d sales-mail` und `$COMPOSE up -d sales-linkedin` jeweils die `approved-Queue nur als Anzahl` zeigen und erst danach genau diesen einen Dienst starten.
  11. **LinkedIn-Aktions-Gate:** den bereits genehmigten Draft eindeutig per ID/Medienname identifizieren, Betreiberfreigabe referenzieren, Worker starten, externe Beitrags-URN, DB-Status `sent` und genau einen Aktivitätsbeleg prüfen. Bei externer Veröffentlichung ohne DB-Buchung: Worker stoppen, `kein erneuter Versand`.
  12. **Autostart-Abnahme:** VM/Docker-Neustart; automatische Dienste kehren zurück, `sales-claw und sales-auto bleiben gestoppt`.
  13. **Rollback:** VM-Projektcontainer vollständig stoppen, bevor Windows/OpenWA wieder gestartet wird. Niemals beide OpenWA-Instanzen parallel.

  Das Runbook zeigt für Queue-Inventar und Statusprüfungen nur IDs, Status, Kanal und Anzahl. Nachrichtentext, E-Mail-Adressen, Telefonnummern, Tokens und Secretlängen werden nicht ausgegeben.

- [ ] **Step 4: GREEN ausführen**

  Run: `python -m pytest scripts/tests/test_proxmox_compose.py -q`

  Expected: alle Compose- und Runbook-Vertragstests bestanden.

- [ ] **Step 5: Engen Commit erstellen**

  ```powershell
  git add -- docs/07_PROXMOX_PILOT.md scripts/tests/test_proxmox_compose.py
  git commit -m "docs: add proxmox pilot runbook"
  ```

---

## Task 6: Gesamten Vorbereitungsstand verifizieren und Cutover bewusst offen lassen

**Files:**

- Verify only; no product-code changes expected.

- [ ] **Step 1: Alle neuen fokussierten Tests gemeinsam ausführen**

  ```powershell
  python -m pytest `
    scripts/tests/test_proxmox_compose.py `
    scripts/tests/test_package_proxmox.py `
    scripts/tests/test_proxmox_preflight.py `
    scripts/tests/test_openwa_backup.py `
    -q
  ```

  Expected: alle Tests bestanden, 0 Fehler.

- [ ] **Step 2: Bestehenden LinkedIn-Vertrag erneut prüfen**

  Den bereits etablierten, gegen `sales_test` isolierten Befehl aus `sales-mcp/tests/test_linkedin_dispatch.py` verwenden.

  Expected: `33 passed`, echte LinkedIn-Aufrufe bleiben dreifach blockiert. Falls sich die Testanzahl durch zwischenzeitliche Änderungen erhöht hat, die neue Zahl protokollieren und nicht künstlich auf 33 begrenzen.

- [ ] **Step 3: Compose und Quellpaket final prüfen**

  ```powershell
  docker compose --env-file .env.example `
    -f docker-compose.yml `
    -f docker-compose.openwa.yml `
    -f docker-compose.proxmox.yml `
    config --quiet
  python scripts/package_proxmox.py --source . --output artifacts/proxmox
  ```

  Expected: beide Befehle exit 0. Manifest-Hash und Dateizahl protokollieren, nicht den Dateiinhalt.

- [ ] **Step 4: Scope- und Hygieneprüfung durchführen**

  ```powershell
  git diff --check
  git status --short --branch
  git log --oneline -6
  ```

  Expected: kein Whitespace-Fehler; vorhandene LinkedIn-/Stack-Änderungen bleiben unangetastet; jeder Plan-Task besitzt seinen eigenen engen Commit.

- [ ] **Step 5: Ergebnis als Deployment-Readiness, nicht als Deployment, berichten**

  Der Abschlussbericht trennt ausdrücklich:

  - lokal verifiziert: Compose-Vertrag, Paket-Exklusionen, read-only Preflight-Logik, Backup-Verifikation und Runbook-Gates;
  - nicht ausgeführt: VM-Preflight, Speichererweiterung/-freigabe, Tailscale-Anmeldung, frische reale Backups, Datei-/Secrettransfer, Restore, Containerstart, LinkedIn-Veröffentlichung und Reboot-Abnahme;
  - nächster einzelner Schritt: Betreiber bestätigt den Beginn des realen Cutovers; danach wird ausschließlich der read-only Preflight ausgeführt und dessen Ergebnis erneut vorgelegt.

- [ ] **Step 6: Keinen Sammelcommit erzeugen**

  Wenn `git status` nur die bereits zuvor vorhandenen fremden Änderungen und ignorierte Artefakte zeigt, ist Task 6 ohne Commit abgeschlossen. Unerwartete Änderungen werden nicht automatisch aufgenommen.
