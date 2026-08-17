"""Build the PDF fixtures used by the parser tests.

The fixtures are committed as binary, which makes them impossible to review in a diff.
This script is what makes them reviewable instead: the PDFs are written here in full,
by hand, so what a fixture contains can be read rather than inferred from test failures.

Regenerate with:  uv run python tests/fixtures/pdfs/make_fixtures.py

Regeneration is byte-for-byte deterministic — there are no timestamps or identifiers in
the output — so a rebuild that changes a file means this script changed, not the run.
"""

from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).parent

# US Letter, in PDF user-space points.
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792


def _text_ops(lines: list[tuple[float, float, int, str]]) -> str:
    """Text-drawing operators for (x, y, size, content), y measured from the bottom."""
    return "\n".join(
        f"BT /F1 {size} Tf {x} {y} Td ({_escape(text)}) Tj ET"
        for x, y, size, text in lines
    )


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


# A note for whoever edits the strings below. Text here is written with the base-14
# Helvetica face, whose StandardEncoding maps byte 0x27 to "quoteright" rather than to
# the typewriter apostrophe. An ASCII "'" therefore comes back out of extraction as
# U+2019, and the golden file records it that way. That is the PDF being read correctly,
# not the parser being wrong, and the fixture is left carrying one apostrophe on purpose
# so the behaviour stays covered.


def _build(pages: list[str], *, rotation: int = 0, with_image: bool = False) -> bytes:
    """Assemble a PDF from per-page content streams, fixing up the xref offsets.

    `with_image` adds a tiny grayscale image XObject that every page can draw. It exists
    so a fixture can carry a real embedded image rather than a stand-in, because image
    detection reads the page's resources and a stand-in would not be there to find.
    """
    page_ids = [4 + i * 2 for i in range(len(pages))]
    content_ids = [5 + i * 2 for i in range(len(pages))]
    # Must be contiguous with the rest: the cross-reference table lists every
    # number from one to the highest, and a gap makes the file unreadable.
    image_id = (max(content_ids) if content_ids else 3) + 1

    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] "
            f"/Count {len(pages)} >>"
        ),
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    if with_image:
        # Two-by-two grayscale. The content is irrelevant; its presence is the point.
        objects[image_id] = (
            "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
            "/ColorSpace /DeviceGray /BitsPerComponent 8 /Length 4 >>\n"
            "stream\n\x00\x40\x80\xff\nendstream"
        )

    resources = "/Font << /F1 3 0 R >>"
    if with_image:
        resources += f" /XObject << /Im1 {image_id} 0 R >>"

    for page_id, content_id, content in zip(page_ids, content_ids, pages, strict=True):
        rotate = f" /Rotate {rotation}" if rotation else ""
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}]"
            f"{rotate} /Resources << {resources} >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects[content_id] = f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1")

    xref_at = len(out)
    highest = max(objects) + 1
    out += f"xref\n0 {highest}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number in range(1, highest):
        out += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {highest} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode(
        "latin-1"
    )
    return bytes(out)


def _prose_block(
    start_y: float,
    lines: list[str],
    *,
    size: int = 10,
) -> list[tuple[float, float, int, str]]:
    """Consecutive lines at ordinary leading — 1.4 times the type size."""
    leading = size * 1.4
    return [(72, start_y - i * leading, size, text) for i, text in enumerate(lines)]


def _native_text_sample() -> bytes:
    """Two pages of ordinary prose at a realistic density.

    Density matters as much as structure here. A page holding six short lines has a text
    area under 3% of the page and classifies by falling through the rules rather than by
    satisfying the one about a usable text layer, so a sparse fixture would leave the
    interesting path untested while still passing. These pages run to full measure and
    roughly thirty lines, which is what an actual page of a textbook looks like.

    Leading is 1.4 times the type size within a paragraph and the gaps between them are
    far wider, so paragraph grouping has an unambiguous signal rather than a marginal one.
    """
    page_one = _text_ops(
        [
            (72, 720, 16, "Introduction to Backpropagation"),
            *_prose_block(
                686,
                [
                    "Backpropagation computes the gradient of the loss function with",
                    "respect to every weight in the network by applying the chain rule",
                    "backwards through each layer in turn. The algorithm is what makes",
                    "training a deep network tractable, because it reuses the partial",
                    "results of one layer when computing the gradients of the next.",
                    "Without it, each weight would need its own forward evaluation.",
                ],
            ),
            *_prose_block(
                580,
                [
                    "The algorithm proceeds in two passes over the network. The forward",
                    "pass computes the activation of every unit and stores it, because",
                    "the backward pass will need those stored values to evaluate the",
                    "local derivatives. Memory therefore grows with the depth of the",
                    "network and the size of the batch being processed.",
                ],
            ),
            *_prose_block(
                480,
                [
                    "The backward pass begins at the loss and works towards the input.",
                    "At each layer it receives the gradient of the loss with respect to",
                    "that layer's output, and produces two things from it: the gradient",
                    "with respect to the layer's parameters, which the optimiser will",
                    "use, and the gradient with respect to the layer's input, which is",
                    "what the preceding layer receives in its turn.",
                ],
            ),
            *_prose_block(
                380,
                [
                    "Numerical stability deserves attention at this point. Gradients",
                    "that are repeatedly multiplied by values below one shrink towards",
                    "zero as they travel backwards, and the layers nearest the input",
                    "stop learning altogether. Multiplying by values above one has the",
                    "opposite effect and the gradients diverge. Both failures are",
                    "properties of the composition rather than of any single layer.",
                ],
            ),
            *_prose_block(
                280,
                [
                    "Practical implementations address this with careful initialisation,",
                    "normalisation between layers, and architectural choices that give",
                    "gradients a shorter path back to the input. None of these change",
                    "the algorithm itself. They change the numbers it operates on so",
                    "that the arithmetic stays within a usable range.",
                ],
            ),
        ]
    )
    page_two = _text_ops(
        [
            (72, 720, 16, "The Backward Pass in Detail"),
            *_prose_block(
                686,
                [
                    "Gradients flow backwards from the output layer towards the input.",
                    "Each layer receives the gradient of the layer above it and applies",
                    "the local derivative of its own operation before passing the result",
                    "along. The composition of these local derivatives is exactly what",
                    "the chain rule describes.",
                ],
            ),
            *_prose_block(
                594,
                [
                    "Weight updates follow the optimiser's rule rather than the gradient",
                    "directly. Stochastic gradient descent subtracts a scaled gradient,",
                    "while adaptive methods maintain per-parameter statistics and scale",
                    "each update by them. The gradient computation is identical in both",
                    "cases; only what is done with the result differs.",
                ],
            ),
        ]
    )
    return _build([page_one, page_two])


def _single_line_sample() -> bytes:
    """One page holding one short line — the smallest thing that is still a document."""
    return _build([_text_ops([(72, 720, 12, "Only one line.")])])


def _rotated_sample() -> bytes:
    """A landscape-rotated page, to pin rotation normalisation."""
    return _build([_text_ops([(72, 720, 12, "Rotated ninety degrees.")])], rotation=90)


def _empty_page_sample() -> bytes:
    """A page with a valid structure and nothing drawn on it."""
    return _build([""])


def _structured_sample() -> bytes:
    """One page carrying every element type this parser can tell apart.

    A heading set larger than the body, a paragraph, a bulleted list, a ruled table, a
    caption under it, and an embedded image. The table is drawn with real stroked lines
    because table detection looks for them — a table implied only by alignment would not
    be found, which is itself a limitation worth knowing rather than papering over.
    """
    text = _text_ops(
        [
            (72, 720, 18, "Results and Discussion"),
            *_prose_block(
                690,
                [
                    "The measurements below were collected over three runs of the",
                    "training procedure, with the learning rate held constant.",
                ],
            ),
            (72, 640, 10, "- Accuracy improved on every run"),
            (72, 626, 10, "- Loss decreased monotonically"),
            (72, 612, 10, "- Variance across runs stayed small"),
            # Cells of the ruled table below.
            (110, 545, 10, "Run"),
            (310, 545, 10, "Accuracy"),
            (110, 505, 10, "1"),
            (310, 505, 10, "0.91"),
            (110, 465, 10, "2"),
            (310, 465, 10, "0.94"),
            (72, 420, 9, "Table 1: Accuracy by run."),
            (72, 250, 9, "Figure 1: Loss curve over training steps."),
        ]
    )
    # A three-row grid: outer box, two horizontal rules, one vertical rule.
    table = "\n".join(
        [
            "1 w",
            "100 450 400 120 re S",
            "100 530 m 500 530 l S",
            "100 490 m 500 490 l S",
            "300 450 m 300 570 l S",
        ]
    )
    image = "q 200 150 0 0 0 0 cm Q\nq 200 0 0 150 100 270 cm /Im1 Do Q"
    return _build(["\n".join([table, image, text])], with_image=True)


def _no_pages_sample() -> bytes:
    """Structurally valid, and containing no pages at all.

    Distinct from a blank page: there is nothing to iterate, so a parser that assumes at
    least one page returns an empty document rather than reporting that it cannot read it.
    """
    return _build([])


_FIXTURES = {
    "native_text_sample.pdf": _native_text_sample,
    "single_line_sample.pdf": _single_line_sample,
    "rotated_sample.pdf": _rotated_sample,
    "empty_page_sample.pdf": _empty_page_sample,
    "structured_sample.pdf": _structured_sample,
    "no_pages_sample.pdf": _no_pages_sample,
}


def main() -> None:
    for name, build in _FIXTURES.items():
        path = _HERE / name
        path.write_bytes(build())
        sys.stdout.write(f"wrote {path.name} ({path.stat().st_size} bytes)\n")


if __name__ == "__main__":
    main()
