"""Task contamination analysis (issue #25).

Checks whether a task's exact prompt text appears in known public corpora.
The check is deliberately conservative and honest about its limits: it is a
whitespace-normalised exact substring search against corpus snapshots the
operator provides locally. It cannot prove absence from a corpus that was
not checked; the result therefore always names the corpora it searched.

Statuses:

- ``contaminated``: the normalised prompt appears in at least one corpus.
- ``clean``: no match in any configured corpus.
- ``unchecked``: no corpora were configured.

The result is stored per task in ``catalog.tasks.contamination`` (JSONB) by
the CLI in ``scripts/check_contamination.py`` and surfaced in the API and
the tasks view.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

METHOD = "normalised-exact-substring/v1"

# Prompts shorter than this normalise to strings too generic to attribute;
# they are reported as matches only when found, never used to claim safety.
MIN_PROMPT_CHARACTERS = 20

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class CorpusMatch:
    corpus: str
    offset: int


@dataclass(frozen=True, slots=True)
class ContaminationResult:
    slug: str
    version: str
    status: str
    matches: tuple[CorpusMatch, ...]
    corpora_checked: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        """The JSONB payload stored on ``catalog.tasks.contamination``."""
        return {
            "status": self.status,
            "method": METHOD,
            "checked_at": datetime.now(UTC).isoformat(),
            "corpora_checked": list(self.corpora_checked),
            "matches": [{"corpus": match.corpus, "offset": match.offset} for match in self.matches],
        }


def normalise(text: str) -> str:
    """Collapse whitespace and casefold so cosmetic edits do not hide reuse."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def check_prompt(
    prompt: str, corpora: dict[str, str], *, slug: str = "", version: str = ""
) -> ContaminationResult:
    """Check one prompt against normalised corpus texts."""
    if not corpora:
        return ContaminationResult(
            slug=slug, version=version, status="unchecked", matches=(), corpora_checked=()
        )
    needle = normalise(prompt)
    matches: list[CorpusMatch] = []
    if len(needle) >= MIN_PROMPT_CHARACTERS:
        for name, text in sorted(corpora.items()):
            offset = text.find(needle)
            if offset != -1:
                matches.append(CorpusMatch(corpus=name, offset=offset))
    status = "contaminated" if matches else "clean"
    return ContaminationResult(
        slug=slug,
        version=version,
        status=status,
        matches=tuple(matches),
        corpora_checked=tuple(sorted(corpora)),
    )


def load_corpora(directory: Path) -> dict[str, str]:
    """Load every text file under ``directory`` as a normalised corpus."""
    corpora: dict[str, str] = {}
    if not directory.is_dir():
        return corpora
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in (".txt", ".md", ".jsonl"):
            corpora[str(path.relative_to(directory))] = normalise(
                path.read_text(encoding="utf-8", errors="replace")
            )
    return corpora


def render_report(results: list[ContaminationResult], corpora: dict[str, str]) -> str:
    """A markdown contamination report for a task library."""
    lines = [
        "# Contamination report",
        "",
        f"Method: {METHOD}. A task is flagged when its whitespace-normalised",
        "prompt appears verbatim inside a configured corpus snapshot. The",
        "check cannot prove absence from corpora that were not configured;",
        "the corpora searched are listed below.",
        "",
        f"Corpora checked: {len(corpora)}",
    ]
    for name in sorted(corpora):
        lines.append(f"- {name}")
    if not corpora:
        lines.append("- none configured; every task is reported unchecked")
    lines += ["", "| Task | Version | Status | Matches |", "|------|---------|--------|---------|"]
    for result in results:
        matched = ", ".join(match.corpus for match in result.matches) or "-"
        lines.append(f"| {result.slug} | {result.version} | {result.status} | {matched} |")
    lines.append("")
    return "\n".join(lines)
