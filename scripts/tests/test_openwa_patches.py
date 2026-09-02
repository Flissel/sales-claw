"""Vertraege ueber die versionierten OpenWA-Patches (deploy/openwa-patches).

02.09.2026 gemessen: Patch 0002 stellte das Dashboard-Login auf localStorage
um, aber nur in App.tsx — der API-Client und der WebSocket-Hook lasen den
Schluessel weiter aus sessionStorage, keine Anfrage trug den Schluessel,
alles lief in 401, und die Drossel (429) verdeckte das zunaechst. Diese
Vertraege lesen die PATCH-DATEI selbst (das Nested-Repo ist gitignoriert
und in der CI nicht vorhanden).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH_0002 = ROOT / "deploy" / "openwa-patches" / "0002-dashboard-embed.patch"


def _dateien(patch: str) -> set[str]:
    return set(re.findall(r"^diff --git a/(\S+) b/", patch, flags=re.M))


def _hinzugefuegt(patch: str) -> list[str]:
    return [z[1:] for z in patch.splitlines()
            if z.startswith("+") and not z.startswith("+++")]


def _entfernt(patch: str) -> list[str]:
    return [z[1:] for z in patch.splitlines()
            if z.startswith("-") and not z.startswith("---")]


def test_patch_0002_stellt_alle_schluessel_leser_auf_localstorage_um():
    patch = PATCH_0002.read_text(encoding="utf-8")
    assert {"dashboard/src/App.tsx",
            "dashboard/src/services/api.ts",
            "dashboard/src/hooks/useWebSocket.ts",
            "src/main.ts"} <= _dateien(patch)
    # Jeder sessionStorage-Zugriff auf den Schluessel wird ENTFERNT ...
    weg = [z for z in _entfernt(patch)
           if "sessionStorage" in z and "openwa_api_key" in z]
    assert len(weg) >= 5, weg          # Login(2: set+remove) + api(4) + ws(1) minus Doppel
    # ... und keiner kommt hinzu.
    assert not [z for z in _hinzugefuegt(patch)
                if "sessionStorage" in z and "openwa_api_key" in z]
    # Jede entfernte Stelle hat ein localStorage-Gegenstueck.
    hin = [z for z in _hinzugefuegt(patch)
           if "localStorage" in z and "openwa_api_key" in z]
    assert len(hin) >= len(weg)


def test_patch_0002_erweitert_frame_ancestors_nur_aus_der_umgebung():
    patch = PATCH_0002.read_text(encoding="utf-8")
    hin = "\n".join(_hinzugefuegt(patch))
    assert "DASHBOARD_FRAME_ANCESTORS" in hin
    assert "frameAncestors" in hin


def test_anwende_skript_stellt_pin_plus_patches_her():
    """Ein geaenderter Patch darf nie als 'schon drin' uebersprungen werden."""
    skript = (ROOT / "deploy" / "openwa-patch-anwenden.sh").read_text(encoding="utf-8")
    assert "checkout -- ." in skript
    assert "apply --check" in skript
    # Der alte Reverse-Check ("schon drin") ist genau die Luecke:
    assert "apply --check --reverse" not in skript
