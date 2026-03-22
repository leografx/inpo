#!/usr/bin/env python3
"""
Remove Marks — removes all content outside the BleedBox.

Masks everything outside the bleed area so that printer marks, slugs,
and any other objects beyond the bleed are eliminated. The bleed and
trim content are preserved.

Usage:
    python removeMarks.py input.pdf
    python removeMarks.py input.pdf -o output.pdf
"""

import argparse
import io
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import ArrayObject, FloatObject, NameObject


def remove_marks(input_path: str, output_path: str | None = None):
    reader = PdfReader(input_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        mb = page.mediabox
        mb_w = float(mb.width)
        mb_h = float(mb.height)

        bleed = page.bleedbox if "/BleedBox" in page else mb
        bb_x = float(bleed.left)
        bb_y = float(bleed.lower_left[1])
        bb_w = float(bleed.width)
        bb_h = float(bleed.height)

        # White-out everything outside the BleedBox using even-odd fill
        from reportlab.pdfgen import canvas as rl_canvas

        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(mb_w, mb_h))
        path = c.beginPath()
        # Outer rect (full media) — clockwise
        path.moveTo(float(mb.left), float(mb.lower_left[1]))
        path.lineTo(float(mb.left) + mb_w, float(mb.lower_left[1]))
        path.lineTo(float(mb.left) + mb_w, float(mb.lower_left[1]) + mb_h)
        path.lineTo(float(mb.left), float(mb.lower_left[1]) + mb_h)
        path.close()
        # Inner rect (bleed area) — counter-clockwise to punch a hole
        path.moveTo(bb_x, bb_y)
        path.lineTo(bb_x, bb_y + bb_h)
        path.lineTo(bb_x + bb_w, bb_y + bb_h)
        path.lineTo(bb_x + bb_w, bb_y)
        path.close()

        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(1, 1, 1)
        c.drawPath(path, fill=1, stroke=0)
        c.save()
        buf.seek(0)
        mask_page = PdfReader(buf).pages[0]

        # Merge the white mask on top of the original page
        page.merge_page(mask_page)

        writer.add_page(page)
        print(f"Page {i + 1}: masked outside bleed {bb_w:.1f}x{bb_h:.1f}pt "
              f"({bb_w / 72:.3f}x{bb_h / 72:.3f}in), "
              f"page size {mb_w:.1f}x{mb_h:.1f}pt preserved")

    if not output_path:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_clean.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"\nOutput: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Remove all content outside the BleedBox (marks, slugs)",
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <input>_clean.pdf)",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    remove_marks(args.input, args.output)


if __name__ == "__main__":
    main()
