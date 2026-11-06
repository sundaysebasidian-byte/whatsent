"""The published accuracy matrix is generated from this offline corpus."""
from whatsent import selftest
from whatsent.detect import Matcher


def test_accuracy_corpus():
    results = selftest.run_corpus()
    assert all(not row.failures for row in results), selftest.render(results)
    assert sum(r.cases for r in results) > 1000


def test_accuracy_markdown_matches_document():
    from pathlib import Path
    assert (Path(__file__).resolve().parents[1] / 'docs' / 'ACCURACY.md').read_text(encoding='utf-8') == selftest.render(selftest.run_corpus(), markdown=True)


def test_selftest_exits_nonzero_on_a_miss_or_false_positive(monkeypatch, capsys):
    monkeypatch.setattr(Matcher, 'scan', lambda *a, **kw: {'incorrect'})
    assert selftest.main() == 1
    assert '✗' in capsys.readouterr().out
