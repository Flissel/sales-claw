"""Bausteine aus ui_muster (Design-Review S3, Plan 2026-10-19-design-s3-s4.md E2):
reine Funktionen ohne DB und ohne ui."""
import ui_muster


def test_reiter_baustein():
    h = ui_muster.reiter([("a", "Überblick", None), ("b", "Verlauf", 3)], "a", lambda k: f"/x?reiter={k}")
    assert '<a href="/x?reiter=a" aria-current="page">Überblick</a>' in h
    assert '<a href="/x?reiter=b">Verlauf <span class="zahl">3</span></a>' in h


def test_reiter_escaped_name_und_url():
    h = ui_muster.reiter([("a", "<b>A & B</b>", None)], "", lambda k: '/x?a=1&b="2"')
    assert "<b>" not in h and "&lt;b&gt;A &amp; B&lt;/b&gt;" in h
    assert 'href="/x?a=1&amp;b=&quot;2&quot;"' in h
    assert h.startswith('<nav class="reiter" aria-label="Bereiche">') and h.endswith("</nav>")


def test_blaettern_wie_kontakte():
    assert ui_muster.blaettern(1, 1, str) == ""
    h = ui_muster.blaettern(2, 3, lambda s: f"/m?seite={s}")
    assert h == ('<nav class="filterleiste" aria-label="Seiten"><a href="/m?seite=1">← Zurück</a>'
                 '<span class="meta">Seite 2 von 3</span><a href="/m?seite=3">Weiter →</a></nav>')


def test_blaettern_ohne_zurueck_auf_seite_eins_und_ohne_weiter_am_ende():
    erste = ui_muster.blaettern(1, 2, lambda s: f"/m?seite={s}")
    assert "Zurück" not in erste and '<a href="/m?seite=2">Weiter →</a>' in erste
    letzte = ui_muster.blaettern(2, 2, lambda s: f"/m?seite={s}")
    assert "Weiter" not in letzte and '<a href="/m?seite=1">← Zurück</a>' in letzte


def test_kennzahlen_erste_ist_haupt_und_escaped():
    h = ui_muster.kennzahlen([(4, "Freigaben offen", "/freigaben"), (0, "A & B", "/x")])
    assert h.startswith('<div class="kpis"><a class="kpi haupt" href="/freigaben"><b>4</b>')
    assert '<a class="kpi" href="/x"><b>0</b><span>A &amp; B</span></a>' in h
    assert h.endswith("</div>")


def test_kennzahlen_escaped_auch_den_pfad():
    h = ui_muster.kennzahlen([(1, "x", '/a"><script>')])
    assert "<script>" not in h and "&quot;&gt;&lt;script&gt;" in h
