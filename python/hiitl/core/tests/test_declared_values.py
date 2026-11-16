"""A bound is read from one located source declaration, never an empty/ambiguous parse (HTL-30)."""

import pytest

from hiitl.core.tests import declared_values


@pytest.mark.parametrize("text", ["No declared limit here", "Budget: 7\nBudget: 8"])
def test_missing_or_ambiguous_declaration_is_refused(tmp_path, monkeypatch, text):
    (tmp_path / "spec.md").write_text(text)
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="Expected one declaration"):
        declared_values.declared_number("spec.md", r"^Budget: ([\d.]+)$")


def test_declared_value_is_read_from_the_named_sentence(tmp_path, monkeypatch):
    bound = 7.25
    (tmp_path / "spec.md").write_text(f"Example: 999\nBudget: {bound}\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    assert declared_values.declared_number("spec.md", r"^Budget: ([\d.]+)$") == bound


def test_typical_core_budget_reads_public_timing_metadata(tmp_path, monkeypatch):
    path = tmp_path / "docs/specs/decision_response.md"
    path.parent.mkdir(parents=True)
    bound = 7.25
    path.write_text(f"Example: 999ms\n- **Typical core evaluation**: < {bound}ms for typical policies.\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    assert declared_values.typical_core_budget_ms() == bound


def test_typical_core_budget_refuses_missing_public_declaration(tmp_path, monkeypatch):
    path = tmp_path / "docs/specs/decision_response.md"
    path.parent.mkdir(parents=True)
    path.write_text("- **Pure local mode**: Single-digit milliseconds (< 10ms)\n")
    monkeypatch.setattr(declared_values, "_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="Expected one declaration"):
        declared_values.typical_core_budget_ms()
