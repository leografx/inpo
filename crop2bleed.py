#!/usr/bin/env python3
"""
Crop to Bleed — sets each page's CropBox to its BleedBox.

Strips everything outside the bleed area, producing a PDF where
each page is exactly the bleed size.

Usage:
    python crop2bleed.py input.pdf
    python crop2bleed.py input.pdf -o output.pdf
"""

import argparse
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject
import pypdf.filters as pf
pf.MAX_DECLARED_STREAM_LENGTH = 10_000_000_000


def crop_to_bleed(input_path: str, output_path: str | None = None):
    reader = PdfReader(input_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        bleed = page.bleedbox if "/BleedBox" in page else page.mediabox

        bb_x = float(bleed.left)
        bb_y = float(bleed.lower_left[1])
        bb_w = float(bleed.width)
        bb_h = float(bleed.height)

        page[NameObject("/CropBox")] = ArrayObject([
            FloatObject(bb_x), FloatObject(bb_y),
            FloatObject(bb_x + bb_w), FloatObject(bb_y + bb_h),
        ])
        page[NameObject("/MediaBox")] = ArrayObject([
            FloatObject(bb_x), FloatObject(bb_y),
            FloatObject(bb_x + bb_w), FloatObject(bb_y + bb_h),
        ])

        writer.add_page(page)
        print(f"Page {i + 1}: cropped to bleed {bb_w:.1f}x{bb_h:.1f}pt "
              f"({bb_w / 72:.3f}x{bb_h / 72:.3f}in)")

    if not output_path:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_cropped.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"\nOutput: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Crop each page's CropBox and MediaBox to its BleedBox",
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <input>_cropped.pdf)",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    crop_to_bleed(args.input, args.output)


if __name__ == "__main__":
    main()
