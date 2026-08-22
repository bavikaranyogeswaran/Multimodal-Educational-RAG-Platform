"""Run the real parser and chunker over a PDF and report what they did.

Run from the backend directory:

    uv run python scripts/inspect_parse.py path/to/textbook.pdf

Everything the parser and the chunker decide has so far been checked against fixtures
built to match what was expected of them. That is a test of consistency, not of
correctness: a gutter rule calibrated against a page this repository generated will pass
against that page whatever it does to a real one. This script exists to be read rather
than to pass, so it reports what actually came out and leaves the judgement to a person
holding the document.

Nothing here touches the database, object storage or any model. The parser needs only the
file, and the chunker needs only a way to count tokens, so this runs anywhere the file
does.

The numbers worth looking at hardest are the ones with no fixture behind them: how many
pages were judged to need recognition, whether the headings match the real section titles,
and whether any element failed to reach a chunk at all — the last of those being content
that was read and then silently dropped.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.configuration.settings import Settings
from app.domain.documents.chunker import Chunker, ChunkFamily
from app.domain.documents.element_classifier import ElementClassifier
from app.domain.documents.entities import DocumentElement, DocumentPage, ParsedPage
from app.domain.documents.page_classifier import PageClassifier
from app.domain.documents.reading_order import ReadingOrderResolver
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.infrastructure.parsing.pdfplumber_parser import PdfPlumberParser
from app.infrastructure.tokenization.token_counter import HuggingFaceTokenCounter

#: A child this short is unlikely to be worth retrieving on its own. Not a rule the
#: chunker enforces — a section really can be two lines long — but a lot of them means
#: the document is being cut somewhere it should not be.
_TINY_CHILD_TOKENS = 40

_RULE = "-" * 78


# ---------------------------------------------------------------------------
# Building the real things
# ---------------------------------------------------------------------------


def _parser(settings: Settings) -> PdfPlumberParser:
    """The same parser the worker builds, with the same configured thresholds."""
    return PdfPlumberParser(
        PageClassifier(
            min_native_characters=settings.ocr.min_native_characters,
            native_text_coverage_threshold=settings.ocr.native_text_coverage_threshold,
            image_coverage_threshold=settings.ocr.image_coverage_threshold,
            complex_vector_drawing_threshold=settings.ocr.complex_vector_drawing_threshold,
        ),
        ElementClassifier(
            heading_size_ratio=settings.parsing.heading_size_ratio,
            heading_max_lines=settings.parsing.heading_max_lines,
            formula_symbol_ratio=settings.parsing.formula_symbol_ratio,
        ),
        ReadingOrderResolver(
            min_gutter_width=settings.parsing.min_gutter_width,
            min_column_width=settings.parsing.min_column_width,
        ),
        paragraph_gap_multiplier=settings.parsing.paragraph_gap_multiplier,
        min_element_characters=settings.parsing.min_element_characters,
        min_gutter_width=settings.parsing.min_gutter_width,
    )


def _chunker(settings: Settings, count: Callable[[str], int]) -> Chunker:
    return Chunker(
        count,
        target_tokens=settings.chunking.child_target_tokens,
        max_tokens=settings.chunking.child_max_tokens,
        overlap_tokens=settings.chunking.child_overlap_tokens,
        parent_target_tokens=settings.chunking.parent_target_tokens,
        parent_max_tokens=settings.chunking.parent_max_tokens,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _heading(title: str) -> None:
    print(f"\n{title}\n{_RULE}")


def _spread(label: str, values: Sequence[int]) -> None:
    """Where the mass of a distribution sits, which an average hides."""
    if not values:
        print(f"  {label:<22} none")
        return
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    print(
        f"  {label:<22} min {ordered[0]:>5}   median {int(statistics.median(ordered)):>5}"
        f"   p90 {p90:>5}   max {ordered[-1]:>5}"
    )


def _tally(label: str, counts: Counter[str], total: int) -> None:
    print(f"  {label}")
    if not counts:
        print("    none")
        return
    for name, n in counts.most_common():
        share = f"{100 * n / total:.0f}%" if total else "-"
        print(f"    {name:<24} {n:>6}  {share:>5}")


def report_pages(parsed: Sequence[ParsedPage], settings: Settings) -> None:
    _heading("PAGES")
    kinds = Counter(item.page.kind.value for item in parsed)
    _tally("kind", kinds, len(parsed))

    unreadable = [item.page.page_number for item in parsed if not item.elements]
    needing_recognition = [
        item.page.page_number for item in parsed if item.page.kind.value != "NATIVE_TEXT"
    ]
    print(f"\n  pages with no elements   {len(unreadable)}")
    if unreadable:
        print(f"    {_compress(unreadable)}")
    print(f"  pages needing recognition {len(needing_recognition)}")
    if needing_recognition:
        print(f"    {_compress(needing_recognition)}")

    share = 100 * len(needing_recognition) / len(parsed) if parsed else 0
    print(
        f"\n  {share:.1f}% of pages defeat the text layer at the configured thresholds "
        f"(complex vector drawings above {settings.ocr.complex_vector_drawing_threshold})"
    )

    rotated = [item.page.page_number for item in parsed if item.page.rotation]
    if rotated:
        print(f"  rotated pages            {_compress(rotated)}")


def report_elements(parsed: Sequence[ParsedPage]) -> None:
    _heading("ELEMENTS")
    elements = [element for item in parsed for element in item.elements]
    print(f"  total                    {len(elements)}")
    if not elements:
        return

    _tally(
        "type",
        Counter(element.element_type.value for element in elements),
        len(elements),
    )
    _spread("per page", [len(item.elements) for item in parsed])
    _spread("characters", [len(element.text.value) for element in elements])

    multi_column = [
        item.page.page_number
        for item in parsed
        if _reads_as_columns(item.elements)
    ]
    print(f"\n  pages read as columns    {len(multi_column)}")
    if multi_column:
        print(f"    {_compress(multi_column)}")


def report_headings(parsed: Sequence[ParsedPage], limit: int) -> None:
    """The section hierarchy the parser believed it saw.

    This is the one to read against the document itself. A heading path is what a
    retrieved fragment is labelled with, and a wrong one mislabels every chunk beneath it
    without failing anything.
    """
    _heading("HEADINGS INFERRED")
    seen: dict[tuple[str, ...], list[int]] = {}
    for item in parsed:
        for element in item.elements:
            seen.setdefault(element.heading_path.segments, []).append(item.page.page_number)

    print(f"  distinct paths           {len(seen)}")
    rootless = len(seen.get((), []))
    if rootless:
        print(f"  elements under no heading {rootless}")

    for index, (segments, pages) in enumerate(seen.items()):
        if index >= limit:
            print(f"    ... {len(seen) - limit} more (use --headings 0 for all)")
            break
        label = " > ".join(segments) if segments else "(no heading)"
        print(f"    p{min(pages):<4} {len(pages):>4} el   {label[:60]}")


def report_chunks(families: Sequence[ChunkFamily], settings: Settings) -> None:
    _heading("CHUNKS")
    children = [child for family in families for child in family.children]
    parents = [family.parent for family in families]

    print(f"  parents                  {len(parents)}")
    print(f"  children                 {len(children)}")
    if not children:
        return

    child_tokens = [child.token_count for child in children]
    parent_tokens = [parent.token_count for parent in parents]
    _spread("child tokens", child_tokens)
    _spread("parent tokens", parent_tokens)
    _spread("children per parent", [len(family.children) for family in families])

    over = sum(1 for n in child_tokens if n > settings.chunking.child_max_tokens)
    tiny = sum(1 for n in child_tokens if n < _TINY_CHILD_TOKENS)
    parents_over = sum(1 for n in parent_tokens if n > settings.chunking.parent_max_tokens)
    lonely = sum(1 for family in families if len(family.children) == 1)

    print(
        f"\n  children over the ceiling of {settings.chunking.child_max_tokens}: {over}"
        f"  ({100 * over / len(children):.1f}%)"
    )
    print(
        f"  children under {_TINY_CHILD_TOKENS} tokens: {tiny}"
        f"  ({100 * tiny / len(children):.1f}%)"
    )
    print(
        f"  parents over the ceiling of {settings.chunking.parent_max_tokens}: {parents_over}"
    )
    print(
        f"  parents holding one child: {lonely}"
        f"  ({100 * lonely / len(families):.1f}%); each duplicates its child"
    )

    print()
    _tally(
        "chunk type",
        Counter(child.chunk_type.value for child in children),
        len(children),
    )
    _spread(
        "pages spanned",
        [child.page_end - child.page_start + 1 for child in children],
    )


def report_coverage(parsed: Sequence[ParsedPage], families: Sequence[ChunkFamily]) -> None:
    """Whether anything the parser read failed to reach a chunk.

    Content dropped here is invisible everywhere else: it was extracted, so the parse
    looks complete, and it is in no chunk, so no search can return it.
    """
    _heading("COVERAGE")
    elements = [
        element
        for item in parsed
        for element in item.elements
        if element.text.value.strip()
    ]
    haystack = " ".join(
        " ".join(child.text.split()) for family in families for child in family.children
    )

    missing = [
        element
        for element in elements
        if " ".join(element.text.value.split()) not in haystack
    ]
    print(f"  elements with text       {len(elements)}")
    print(f"  absent from every chunk  {len(missing)}")
    for element in missing[:10]:
        preview = " ".join(element.text.value.split())[:60]
        print(f"    p{element.page_number:<4} {element.element_type.value:<10} {preview}")
    if len(missing) > 10:
        print(f"    ... {len(missing) - 10} more")


def report_samples(families: Sequence[ChunkFamily], count: int) -> None:
    _heading("SAMPLE CHILDREN")
    children = [
        (family, child) for family in families for child in family.children
    ][:count]
    for family, child in children:
        path = str(child.heading_path) or "(no heading)"
        print(
            f"\n  [{child.chunk_type.value}] p{child.page_start}-{child.page_end}"
            f"  {child.token_count} tokens  under: {path[:50]}"
        )
        print(f"  parent is {family.parent.token_count} tokens")
        preview = " ".join(child.text.split())
        print(f"    {preview[:300]}{'...' if len(preview) > 300 else ''}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compress(numbers: Sequence[int]) -> str:
    """Page numbers as ranges, since a scanned chapter is a run rather than a scatter."""
    if not numbers:
        return ""
    runs: list[tuple[int, int]] = []
    start = previous = numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        runs.append((start, previous))
        start = previous = number
    runs.append((start, previous))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def _reads_as_columns(elements: Sequence[DocumentElement]) -> bool:
    """Whether reading order steps sideways at the same height, which is a column break.

    Not a jump back up the page, which is what column detection looks like in most
    layouts: this resolver works band by band, so a two-column page is read left, right,
    left, right within each horizontal band rather than down one column and back up to
    the top of the next. The signature is therefore a step to the right with no descent.
    """
    boxes = [element.bounding_box for element in elements if element.bounding_box]
    return any(
        later.x0 >= earlier.x1 and later.y0 < earlier.y1 and later.y1 > earlier.y0
        for earlier, later in pairwise(boxes)
    )


async def main() -> int:
    argv = argparse.ArgumentParser(description=__doc__)
    argv.add_argument("pdf", type=Path, help="the PDF to read")
    argv.add_argument("--headings", type=int, default=40, help="0 for all")
    argv.add_argument("--samples", type=int, default=5)
    args = argv.parse_args()

    if not args.pdf.is_file():
        print(f"no such file: {args.pdf}")
        return 2

    settings = Settings()
    data = args.pdf.read_bytes()

    counter = HuggingFaceTokenCounter(
        model_id=settings.embedding.model_id,
        max_input_tokens=settings.embedding.max_input_tokens,
    )

    print(f"\n{args.pdf.name}  ({len(data) / 1_048_576:.1f} MB)")

    started = time.perf_counter()
    try:
        parsed = await _parser(settings).parse(
            data,
            document_id=uuid.uuid4(),
            scope=ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4()),
        )
    except UploadValidationError as refusal:
        # The parser refusing a file is an answer, not a crash, and it is the same
        # answer an upload would have got. A traceback would suggest otherwise.
        print(f"  the parser rejected this file: {refusal}")
        return 1
    parse_seconds = time.perf_counter() - started

    elements = [element for item in parsed for element in item.elements]
    started = time.perf_counter()
    families = _chunker(settings, counter.count).chunk(elements)
    chunk_seconds = time.perf_counter() - started

    pages = len(parsed) or 1
    print(
        f"  parsed in {parse_seconds:.1f}s ({1000 * parse_seconds / pages:.0f} ms/page), "
        f"chunked in {chunk_seconds:.1f}s"
    )

    report_pages(parsed, settings)
    report_elements(parsed)
    report_headings(parsed, args.headings or 10**9)
    report_chunks(families, settings)
    report_coverage(parsed, families)
    report_samples(families, args.samples)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
