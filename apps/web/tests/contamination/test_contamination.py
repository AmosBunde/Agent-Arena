"""Tests for issue #25: contamination analysis."""

from __future__ import annotations

from pathlib import Path

from apps.runner.contamination import (
    check_prompt,
    load_corpora,
    normalise,
    render_report,
)

PROMPT = (
    "A train travels at 50 kilometres per hour for 3 hours. How many kilometres does it travel?"
)


def test_normalisation_collapses_whitespace_and_case() -> None:
    assert normalise("  A  Train\ntravels ") == "a train travels"


def test_exact_match_found_despite_cosmetic_differences() -> None:
    corpus = "benchmark dump:\nа train travels".replace("а", "a")
    corpus += " at 50 kilometres  per hour\nfor 3 hours. how many kilometres does it travel? etc"
    result = check_prompt(PROMPT, {"dump.txt": normalise(corpus)}, slug="wp-1", version="1")
    assert result.status == "contaminated"
    assert result.matches[0].corpus == "dump.txt"


def test_clean_when_absent() -> None:
    result = check_prompt(PROMPT, {"dump.txt": normalise("unrelated text entirely")})
    assert result.status == "clean"
    assert result.corpora_checked == ("dump.txt",)


def test_unchecked_without_corpora() -> None:
    result = check_prompt(PROMPT, {})
    assert result.status == "unchecked"


def test_short_prompts_never_claim_contamination() -> None:
    result = check_prompt("1 + 1", {"dump.txt": normalise("what is 1 + 1?")})
    assert result.status == "clean"


def test_load_corpora_reads_text_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Hello   World")
    (tmp_path / "b.jsonl").write_text('{"text": "sample"}')
    (tmp_path / "ignored.bin").write_bytes(b"\x00")
    corpora = load_corpora(tmp_path)
    assert set(corpora) == {"a.txt", "b.jsonl"}
    assert corpora["a.txt"] == "hello world"


def test_report_lists_every_task_and_corpus(tmp_path: Path) -> None:
    corpora = {"dump.txt": normalise(PROMPT)}
    results = [
        check_prompt(PROMPT, corpora, slug="wp-1", version="1"),
        check_prompt("Something else long enough to check.", corpora, slug="wp-2", version="1"),
    ]
    report = render_report(results, corpora)
    assert "| wp-1 | 1 | contaminated | dump.txt |" in report
    assert "| wp-2 | 1 | clean | - |" in report
    assert "dump.txt" in report


def test_record_shape_for_catalog() -> None:
    record = check_prompt(PROMPT, {"dump.txt": normalise(PROMPT)}, slug="wp-1").to_record()
    assert record["status"] == "contaminated"
    assert record["method"] == "normalised-exact-substring/v1"
    assert record["matches"][0]["corpus"] == "dump.txt"
    assert record["corpora_checked"] == ["dump.txt"]
