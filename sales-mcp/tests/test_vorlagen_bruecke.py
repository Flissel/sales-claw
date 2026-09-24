"""Die Bruecke zu marketing.* — Sales ruft NUR Funktionen, nie Tabellen."""
import vorlagen_bruecke as b


class _Q:
    def __init__(self, antwort):
        self.antwort, self.aufrufe = antwort, []

    def __call__(self, sql, params=()):
        self.aufrufe.append((sql, params))
        return self.antwort


def test_anlegen_ruft_die_funktion_mit_bytes():
    q = _Q([{"ergebnis": {"ok": True, "id": "x"}}])
    assert b.anlegen(q, b"\x89PNG", "image/png", "", "bitte quer")["ok"]
    sql, params = q.aufrufe[0]
    assert "marketing.vorlagenauftrag_anlegen(" in sql and params[1] == b"\x89PNG"


def test_keine_bruecke_liest_eine_marketing_tabelle_direkt():
    """Keine SQL-Zeile darf die TABELLE `marketing.vorlagenauftraege` direkt
    lesen — nur die Funktion `marketing.vorlagenauftraege_des_ladens()`. Ein
    blosser Substring-Test wuerde hier faelschlich anschlagen, weil der
    Funktionsname mit dem Tabellennamen beginnt; die negative Lookahead
    grenzt genau den Funktionsaufruf aus, nicht jede Erwaehnung."""
    import inspect
    import re
    quelle = inspect.getsource(b)
    assert re.search(r"marketing\.vorlagenauftraege(?!_des_ladens)", quelle) is None
    assert "from marketing.layout_vorlagen" not in quelle


def test_vorlage_liefert_none_wenn_es_keine_gibt():
    assert b.vorlage(_Q([]), "terminkarte") is None
