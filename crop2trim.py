#!/usr/bin/env python3
"""
Crop to Trim — sets each page's CropBox to its TrimBox.

Strips everything outside the trim area, producing a PDF where
each page is exactly the final cut size.

Usage:
    python crop2trim.py input.pdf
    python crop2trim.py input.pdf -o output.pdf
"""

import argparse
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject


def crop_to_trim(input_path: str, output_path: str | None = None):
    reader = PdfReader(input_path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        trim = page.trimbox if "/TrimBox" in page else page.mediabox

        tb_x = float(trim.left)
        tb_y = float(trim.lower_left[1])
        tb_w = float(trim.width)
        tb_h = float(trim.height)

        page[NameObject("/CropBox")] = ArrayObject([
            FloatObject(tb_x), FloatObject(tb_y),
            FloatObject(tb_x + tb_w), FloatObject(tb_y + tb_h),
        ])
        page[NameObject("/MediaBox")] = ArrayObject([
            FloatObject(tb_x), FloatObject(tb_y),
            FloatObject(tb_x + tb_w), FloatObject(tb_y + tb_h),
        ])

        writer.add_page(page)
        print(f"Page {i + 1}: cropped to trim {tb_w:.1f}x{tb_h:.1f}pt "
              f"({tb_w / 72:.3f}x{tb_h / 72:.3f}in)")

    if not output_path:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_trimmed.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"\nOutput: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Crop each page's CropBox and MediaBox to its TrimBox",
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <input>_trimmed.pdf)",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    crop_to_trim(args.input, args.output)


if __name__ == "__main__":
    main()
