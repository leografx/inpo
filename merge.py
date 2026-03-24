#!/usr/bin/env python3
"""
Merge multiple PDF files into a single PDF.

Usage:
    python merge.py file1.pdf file2.pdf file3.pdf
    python merge.py file1.pdf file2.pdf -o combined.pdf
    python merge.py *.pdf --sort name
"""

import argparse
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
import pypdf.filters as pf
pf.MAX_DECLARED_STREAM_LENGTH = 10_000_000_000


def merge_pdfs(
    input_files: list[str],
    output_path: str | None = None,
    sort_by: str | None = None,
    reverse: bool = False,
):
    """Merge multiple PDF files into one."""
    paths = [Path(f) for f in input_files]

    # Validate all files exist
    for p in paths:
        if not p.exists():
            print(f"Error: File not found: {p}")
            sys.exit(1)
        if p.suffix.lower() != ".pdf":
            print(f"Warning: '{p}' may not be a PDF file")

    # Sort if requested
    if sort_by == "name":
        paths.sort(key=lambda p: p.name.lower(), reverse=reverse)
    elif sort_by == "date":
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=reverse)
    elif sort_by == "size":
        paths.sort(key=lambda p: p.stat().st_size, reverse=reverse)

    if not output_path:
        output_path = "merged.pdf"

    writer = PdfWriter()
    total_pages = 0

    for p in paths:
        reader = PdfReader(str(p))
        page_count = len(reader.pages)
        for page in reader.pages:
            writer.add_page(page)
        total_pages += page_count
        print(f"  + {p.name} ({page_count} page{'s' if page_count != 1 else ''})")

    writer.write(output_path)
    writer.close()

    print(f"\nMerged {len(paths)} files ({total_pages} total pages)")
    print(f"Output: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Merge multiple PDF files into a single PDF",
    )
    parser.add_argument(
        "inputs", nargs="+",
        help="Input PDF files (in order)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: merged.pdf)",
    )
    parser.add_argument(
        "--sort", choices=["name", "date", "size"], default=None,
        help="Sort input files before merging",
    )
    parser.add_argument(
        "--reverse", action="store_true",
        help="Reverse sort order",
    )

    args = parser.parse_args()

    if len(args.inputs) < 2:
        print("Error: Need at least 2 PDF files to merge")
        sys.exit(1)

    merge_pdfs(
        input_files=args.inputs,
        output_path=args.output,
        sort_by=args.sort,
        reverse=args.reverse,
    )


if __name__ == "__main__":
    main()
