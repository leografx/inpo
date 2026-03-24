#!/usr/bin/env python3
"""
PDF Imposition Tool

Takes an input PDF and a sheet size, then tiles as many copies of each page
as possible onto the sheet. Uses the CropBox to determine layout and
rotation for maximum yield.

Usage:
    python impose.py input.pdf --sheet 320x450mm
    python impose.py input.pdf --sheet tabloid
    python impose.py input.pdf --sheet 13x19in
"""

import argparse
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter, Transformation, PageObject
import pypdf.filters as pf
pf.MAX_DECLARED_STREAM_LENGTH = 10_000_000_000

# ---------- preset sheet sizes (in points, 1pt = 1/72 inch) ----------

MM_TO_PT = 72 / 25.4
IN_TO_PT = 72

PRESETS = {
    # Name:            (width_pt, height_pt)
    "letter":          (8.5 * IN_TO_PT,  11 * IN_TO_PT),
    "legal":           (8.5 * IN_TO_PT,  14 * IN_TO_PT),
    "tabloid":         (11 * IN_TO_PT,   17 * IN_TO_PT),
    "ledger":          (17 * IN_TO_PT,   11 * IN_TO_PT),
    "a5":              (148 * MM_TO_PT,   210 * MM_TO_PT),
    "a4":              (210 * MM_TO_PT,   297 * MM_TO_PT),
    "a3":              (297 * MM_TO_PT,   420 * MM_TO_PT),
    "a2":              (420 * MM_TO_PT,   594 * MM_TO_PT),
    "a1":              (594 * MM_TO_PT,   841 * MM_TO_PT),
    "a0":              (841 * MM_TO_PT,   1189 * MM_TO_PT),
    "b5":              (176 * MM_TO_PT,   250 * MM_TO_PT),
    "b4":              (250 * MM_TO_PT,   353 * MM_TO_PT),
    "b3":              (353 * MM_TO_PT,   500 * MM_TO_PT),
    "sra4":            (225 * MM_TO_PT,   320 * MM_TO_PT),
    "sra3":            (320 * MM_TO_PT,   450 * MM_TO_PT),
    "12x18":           (12 * IN_TO_PT,    18 * IN_TO_PT),
    "13x19":           (13 * IN_TO_PT,    19 * IN_TO_PT),
    "19x25":            (19 * IN_TO_PT,    25 * IN_TO_PT),
    "20x26":            (20 * IN_TO_PT,    26 * IN_TO_PT),
    "25x38":           (25 * IN_TO_PT,    38 * IN_TO_PT),
    "26x40":           (26 * IN_TO_PT,    40 * IN_TO_PT)
}


def parse_sheet_size(spec: str) -> tuple[float, float]:
    """Parse a sheet size like '320x450mm', '13x19in', or a preset name."""
    spec = spec.strip().lower()

    if spec in PRESETS:
        return PRESETS[spec]

    # Try WxH with unit suffix
    for unit_suffix, factor in [("mm", MM_TO_PT), ("in", IN_TO_PT), ("pt", 1)]:
        if spec.endswith(unit_suffix):
            nums = spec[: -len(unit_suffix)]
            if "x" in nums:
                w, h = nums.split("x", 1)
                return float(w) * factor, float(h) * factor

    # Bare WxH defaults to mm
    if "x" in spec:
        w, h = spec.split("x", 1)
        return float(w) * MM_TO_PT, float(h) * MM_TO_PT

    print(f"Error: Cannot parse sheet size '{spec}'")
    print(f"Use a preset ({', '.join(sorted(PRESETS))}) or WxHmm / WxHin")
    sys.exit(1)


def best_layout(crop_w, crop_h, sheet_w, sheet_h):
    """
    Find the layout (cols, rows, rotated) that fits the most copies.
    Tests both orientations of the cropbox on the sheet, butting them
    together against each other with no gap.
    """
    options = []
    for rotated, pw, ph in [(False, crop_w, crop_h), (True, crop_h, crop_w)]:
        cols = int(sheet_w / pw) if pw > 0 else 0
        rows = int(sheet_h / ph) if ph > 0 else 0
        if cols > 0 and rows > 0:
            options.append((cols * rows, cols, rows, rotated, pw, ph))

    if not options:
        return None

    options.sort(key=lambda x: x[0], reverse=True)
    return options[0]  # (count, cols, rows, rotated, eff_pw, eff_ph)


def _get_box(page, name):
    """Get a page box by name, returning (left, bottom, width, height)."""
    box = getattr(page, name, None)
    if box is None:
        box = page.mediabox
    return (float(box.left), float(box.lower_left[1]),
            float(box.width), float(box.height))


def _create_clip_page(sheet_w, sheet_h, clip_rects):
    """
    Create a PDF page that clips (masks) everything outside the given
    rectangles. Each rect is (x, y, w, h) on the output sheet.
    Uses a white fill outside the clip areas.
    """
    import io
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(sheet_w, sheet_h))

    path = c.beginPath()
    # Outer rect (full sheet) — clockwise
    path.moveTo(0, 0)
    path.lineTo(sheet_w, 0)
    path.lineTo(sheet_w, sheet_h)
    path.lineTo(0, sheet_h)
    path.close()
    # Inner rects (clip areas) — counter-clockwise to punch holes
    for (rx, ry, rw, rh) in clip_rects:
        path.moveTo(rx, ry)
        path.lineTo(rx, ry + rh)
        path.lineTo(rx + rw, ry + rh)
        path.lineTo(rx + rw, ry)
        path.close()

    c.setFillColorRGB(1, 1, 1)  # white
    c.setStrokeColorRGB(1, 1, 1)
    c.drawPath(path, fill=1, stroke=0)

    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _create_trim_outline_page(sheet_w, sheet_h, trim_rects, bleed_rects, group_rect):
    """
    Create a PDF page with:
    - Orange outline: group box (grid + 0.25in padding)
    - Blue outlines: bleed boxes
    - Red outlines: trim boxes
    group_rect: (x, y, w, h) for the overall group box.
    """
    import io
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(sheet_w, sheet_h))
    c.setLineWidth(0.5)

    gx, gy, gw, gh = group_rect

    # Yellow trim guide lines spanning the full group box
    c.setStrokeColorRGB(0, 0.5, 0)  # green
    c.setLineWidth(0.3)
    # Collect unique trim x and y coordinates
    trim_xs = set()
    trim_ys = set()
    for (rx, ry, rw, rh) in trim_rects:
        trim_xs.add(round(rx, 4))
        trim_xs.add(round(rx + rw, 4))
        trim_ys.add(round(ry, 4))
        trim_ys.add(round(ry + rh, 4))
    # Vertical lines at each trim x, spanning group box top to bottom
    for vx in trim_xs:
        c.line(vx, gy, vx, gy + gh)
    # Horizontal lines at each trim y, spanning group box left to right
    for hy in trim_ys:
        c.line(gx, hy, gx + gw, hy)

    # Orange group outline
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(1, 0.647, 0)  # orange
    c.rect(gx, gy, gw, gh, fill=0, stroke=1)

    # Blue bleed outlines — skip edges shared between two bleed rects
    c.setStrokeColorRGB(0, 0, 1)
    # Collect all edges as ((x1,y1,x2,y2), index) and count occurrences
    from collections import Counter
    bleed_edges = Counter()
    bleed_rect_edges = []
    for idx, (rx, ry, rw, rh) in enumerate(bleed_rects):
        edges = [
            (round(rx, 4), round(ry, 4), round(rx + rw, 4), round(ry, 4)),         # bottom
            (round(rx + rw, 4), round(ry, 4), round(rx + rw, 4), round(ry + rh, 4)),  # right
            (round(rx, 4), round(ry + rh, 4), round(rx + rw, 4), round(ry + rh, 4)),  # top
            (round(rx, 4), round(ry, 4), round(rx, 4), round(ry + rh, 4)),         # left
        ]
        # Normalize each edge so (x1,y1)-(x2,y2) is canonical
        norm_edges = []
        for e in edges:
            x1, y1, x2, y2 = e
            key = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            norm_edges.append(key)
            bleed_edges[key] += 1
        bleed_rect_edges.append(norm_edges)
    # Draw only edges that appear once (not shared)
    for idx, (rx, ry, rw, rh) in enumerate(bleed_rects):
        for edge_key in bleed_rect_edges[idx]:
            if bleed_edges[edge_key] == 1:
                x1, y1, x2, y2 = edge_key
                c.line(x1, y1, x2, y2)

    # Red trim outlines (on top)
    c.setStrokeColorRGB(1, 0, 0)
    for (rx, ry, rw, rh) in trim_rects:
        c.rect(rx, ry, rw, rh, fill=0, stroke=1)

    # Black crop marks where green trim lines pass between group box and bleed box
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    # Find outermost bleed boundaries
    bleed_xs = set()
    bleed_ys = set()
    for (rx, ry, rw, rh) in bleed_rects:
        bleed_xs.add(round(rx, 4))
        bleed_xs.add(round(rx + rw, 4))
        bleed_ys.add(round(ry, 4))
        bleed_ys.add(round(ry + rh, 4))
    bleed_left = min(bleed_xs)
    bleed_right = max(bleed_xs)
    bleed_bottom = min(bleed_ys)
    bleed_top = max(bleed_ys)
    # Vertical marks at each trim x
    for vx in trim_xs:
        # Bottom gap: group box bottom to outermost bleed bottom
        if gy < bleed_bottom:
            c.line(vx, gy, vx, bleed_bottom)
        # Top gap: outermost bleed top to group box top
        if bleed_top < gy + gh:
            c.line(vx, bleed_top, vx, gy + gh)
    # Horizontal marks at each trim y
    for hy in trim_ys:
        # Left gap: group box left to outermost bleed left
        if gx < bleed_left:
            c.line(gx, hy, bleed_left, hy)
        # Right gap: outermost bleed right to group box right
        if bleed_right < gx + gw:
            c.line(bleed_right, hy, gx + gw, hy)

    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _create_marks_page(sheet_w, sheet_h, trim_rects, bleed_rects, group_rect):
    """
    Create a PDF page with only black crop marks — no overlay boxes.
    Marks are drawn where trim guide lines pass between the group box
    edge and the outermost bleed box edge.
    """
    import io
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(sheet_w, sheet_h))

    gx, gy, gw, gh = group_rect

    # Collect unique trim x and y coordinates
    trim_xs = set()
    trim_ys = set()
    for (rx, ry, rw, rh) in trim_rects:
        trim_xs.add(round(rx, 4))
        trim_xs.add(round(rx + rw, 4))
        trim_ys.add(round(ry, 4))
        trim_ys.add(round(ry + rh, 4))

    # Find outermost bleed boundaries
    bleed_xs = set()
    bleed_ys = set()
    for (rx, ry, rw, rh) in bleed_rects:
        bleed_xs.add(round(rx, 4))
        bleed_xs.add(round(rx + rw, 4))
        bleed_ys.add(round(ry, 4))
        bleed_ys.add(round(ry + rh, 4))
    bleed_left = min(bleed_xs)
    bleed_right = max(bleed_xs)
    bleed_bottom = min(bleed_ys)
    bleed_top = max(bleed_ys)

    # Black crop marks
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    # Vertical marks at each trim x
    for vx in trim_xs:
        if gy < bleed_bottom:
            c.line(vx, gy, vx, bleed_bottom)
        if bleed_top < gy + gh:
            c.line(vx, bleed_top, vx, gy + gh)
    # Horizontal marks at each trim y
    for hy in trim_ys:
        if gx < bleed_left:
            c.line(gx, hy, bleed_left, hy)
        if bleed_right < gx + gw:
            c.line(bleed_right, hy, gx + gw, hy)

    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _impose_single_page(
    src_page, sheet_w, sheet_h, avail_w, avail_h, margin,
    outline, marks, is_back=False, front_layout=None,
    margin_left=None, margin_bottom=None,
):
    """
    Impose a single source page onto a sheet.
    If is_back=True, uses the front_layout but mirrors columns and
    rotates in the opposite direction for duplex alignment.
    Returns (out_page, layout_info) or None if page doesn't fit.
    """
    cb_x, cb_y, crop_w, crop_h = _get_box(src_page, "cropbox")

    if front_layout is not None:
        # Back page: reuse front grid exactly
        count, cols, rows, front_rotated, eff_pw, eff_ph = front_layout
        rotated = front_rotated
        # back_rotation_angle: if front was rotated 90° CW, back rotates 90° CCW
        back_rotation = True  # flag: this is a back page
        # Keep cell dimensions identical to front
    else:
        layout = best_layout(crop_w, crop_h, avail_w, avail_h)
        if layout is None:
            return None
        count, cols, rows, rotated, eff_pw, eff_ph = layout
        back_rotation = False

    # Center the grid within the available area (respecting asymmetric margins)
    grid_w = cols * eff_pw
    grid_h = rows * eff_ph
    ml = margin_left if margin_left is not None else margin
    mb = margin_bottom if margin_bottom is not None else margin
    offset_x = ml + (avail_w - grid_w) / 2
    offset_y = mb + (avail_h - grid_h) / 2

    # Create a blank output page
    out_page = PageObject.create_blank_page(width=sheet_w, height=sheet_h)

    clip_rects = []

    for row in range(rows):
        for col in range(cols):
            # For back pages, mirror columns so content aligns when sheet flips
            if is_back:
                draw_col = cols - 1 - col
            else:
                draw_col = col

            x = offset_x + draw_col * eff_pw
            y = offset_y + row * eff_ph

            if rotated and not (is_back and back_rotation):
                # Front rotated 90° CW
                tx = Transformation()
                tx = tx.translate(tx=-cb_x, ty=-cb_y)
                tx = tx.rotate(90)
                tx = tx.translate(tx=x + eff_pw, ty=y)
            elif rotated and is_back and back_rotation:
                # Back rotated 90° CCW (opposite of front)
                tx = Transformation()
                tx = tx.translate(tx=-cb_x, ty=-cb_y)
                tx = tx.rotate(-90)
                tx = tx.translate(tx=x, ty=y + eff_ph)
            else:
                tx = Transformation()
                tx = tx.translate(tx=-cb_x, ty=-cb_y)
                tx = tx.translate(tx=x, ty=y)

            out_page.merge_transformed_page(src_page, tx)
            clip_rects.append((x, y, eff_pw, eff_ph))

    # Apply mask: white-out everything outside the cropbox cells
    clip_page = _create_clip_page(sheet_w, sheet_h, clip_rects)
    out_page.merge_page(clip_page)

    if outline or marks:
        tb_x, tb_y, trim_w, trim_h = _get_box(src_page, "trimbox")
        bb_x, bb_y, bleed_w, bleed_h = _get_box(src_page, "bleedbox")

        if rotated:
            trim_inset_left = tb_y - cb_y
            trim_inset_bottom = tb_x - cb_x
            trim_eff_w = trim_h
            trim_eff_h = trim_w
            bleed_inset_left = bb_y - cb_y
            bleed_inset_bottom = bb_x - cb_x
            bleed_eff_w = bleed_h
            bleed_eff_h = bleed_w
        else:
            trim_inset_left = tb_x - cb_x
            trim_inset_bottom = tb_y - cb_y
            trim_eff_w = trim_w
            trim_eff_h = trim_h
            bleed_inset_left = bb_x - cb_x
            bleed_inset_bottom = bb_y - cb_y
            bleed_eff_w = bleed_w
            bleed_eff_h = bleed_h

        trim_rects = []
        bleed_rects = []
        for row in range(rows):
            for col in range(cols):
                if is_back:
                    draw_col = cols - 1 - col
                else:
                    draw_col = col
                tx = offset_x + draw_col * eff_pw + trim_inset_left
                ty = offset_y + row * eff_ph + trim_inset_bottom
                trim_rects.append((tx, ty, trim_eff_w, trim_eff_h))
                bx = offset_x + draw_col * eff_pw + bleed_inset_left
                by = offset_y + row * eff_ph + bleed_inset_bottom
                bleed_rects.append((bx, by, bleed_eff_w, bleed_eff_h))

        # Group box: entire grid + 0.25in padding on all sides
        pad = 0.25 * 72
        group_rect = (
            offset_x - pad,
            offset_y - pad,
            grid_w + 2 * pad,
            grid_h + 2 * pad,
        )

        if outline:
            overlay_page = _create_trim_outline_page(
                sheet_w, sheet_h, trim_rects, bleed_rects, group_rect
            )
            out_page.merge_page(overlay_page)

        if marks:
            marks_page = _create_marks_page(
                sheet_w, sheet_h, trim_rects, bleed_rects, group_rect
            )
            out_page.merge_page(marks_page)

    layout_info = (count, cols, rows, rotated, eff_pw, eff_ph)
    return out_page, layout_info


def impose(
    input_path: str,
    sheet_size: tuple[float, float],
    output_path: str | None = None,
    outline: bool = False,
    marks: bool = False,
    margin: float = 0.375 * 72,
    margin_left: float | None = None,
    margin_right: float | None = None,
    margin_top: float | None = None,
    margin_bottom: float | None = None,
):
    reader = PdfReader(input_path)
    writer = PdfWriter()

    sheet_w, sheet_h = sheet_size

    # Resolve independent margins (fall back to uniform margin)
    ml = margin_left if margin_left is not None else margin
    mr = margin_right if margin_right is not None else margin
    mt = margin_top if margin_top is not None else margin
    mb = margin_bottom if margin_bottom is not None else margin

    # Available area after margins
    avail_w = sheet_w - ml - mr
    avail_h = sheet_h - mt - mb

    total_placed = 0
    first_layout = None  # track first layout for return info
    pages = list(reader.pages)
    num_pages = len(pages)

    page_idx = 0
    while page_idx < num_pages:
        src_page = pages[page_idx]
        cb_x, cb_y, crop_w, crop_h = _get_box(src_page, "cropbox")

        # Front page — determine best layout
        result = _impose_single_page(
            src_page, sheet_w, sheet_h, avail_w, avail_h, margin,
            outline, marks, is_back=False, front_layout=None,
            margin_left=ml, margin_bottom=mb,
        )
        if result is None:
            print(f"Warning: Page {page_idx + 1} ({crop_w:.1f}x{crop_h:.1f}pt crop) "
                  f"does not fit on sheet ({sheet_w:.1f}x{sheet_h:.1f}pt). Skipping.")
            page_idx += 1
            continue

        out_page, layout_info = result
        count, cols, rows, rotated, eff_pw, eff_ph = layout_info
        if first_layout is None:
            first_layout = layout_info
        writer.add_page(out_page)
        placed = cols * rows
        total_placed += placed

        orient = "rotated " if rotated else ""
        print(
            f"Page {page_idx + 1} (front): {cols}x{rows} = {placed} copies "
            f"({orient}{eff_pw:.1f}x{eff_ph:.1f}pt on {sheet_w:.1f}x{sheet_h:.1f}pt sheet, "
            f"crop {crop_w:.1f}x{crop_h:.1f}pt)"
        )

        # Back page (even page) — if it exists
        if page_idx + 1 < num_pages:
            back_page = pages[page_idx + 1]
            back_cb_x, back_cb_y, back_crop_w, back_crop_h = _get_box(back_page, "cropbox")

            back_result = _impose_single_page(
                back_page, sheet_w, sheet_h, avail_w, avail_h, margin,
                outline, marks, is_back=True, front_layout=layout_info,
                margin_left=ml, margin_bottom=mb,
            )
            if back_result is None:
                print(f"Warning: Page {page_idx + 2} does not fit. Skipping.")
            else:
                back_out_page, back_layout = back_result
                writer.add_page(back_out_page)
                b_count, b_cols, b_rows, b_rotated, b_eff_pw, b_eff_ph = back_layout
                back_placed = b_cols * b_rows
                total_placed += back_placed

                back_orient = "rotated " if b_rotated else ""
                print(
                    f"Page {page_idx + 2} (back):  {b_cols}x{b_rows} = {back_placed} copies "
                    f"({back_orient}{b_eff_pw:.1f}x{b_eff_ph:.1f}pt, mirrored for duplex)"
                )
            page_idx += 2
        else:
            page_idx += 1

    if not output_path:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_imposed.pdf")

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"\nTotal copies placed: {total_placed}")
    print(f"Output: {output_path}")

    layout_result = None
    if first_layout:
        layout_result = {
            "cols": first_layout[1],
            "rows": first_layout[2],
            "count_per_sheet": first_layout[0],
            "total_placed": total_placed,
        }

    return output_path, layout_result


def main():
    parser = argparse.ArgumentParser(
        description="PDF Imposition — tile input pages onto larger sheets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Sheet size formats:\n"
            "  Preset name:   a3, a4, sra3, tabloid, letter, 13x19, etc.\n"
            "  Custom (mm):   320x450mm  or  320x450  (mm is default)\n"
            "  Custom (in):   13x19in\n"
            "  Custom (pt):   936x1296pt\n"
            "\n"
            f"Available presets: {', '.join(sorted(PRESETS))}"
        ),
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--sheet", "-s", required=True,
        help="Sheet size (preset name or WxH with unit)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <input>_imposed.pdf)",
    )
    parser.add_argument(
        "--outline", action="store_true",
        help="Draw red outline boxes at trim edges",
    )
    parser.add_argument(
        "--marks", action="store_true",
        help="Draw crop marks only (no overlay boxes)",
    )
    parser.add_argument(
        "--margin", type=float, default=0.375,
        help="Uniform margin around the sheet in inches (default: 0.375). Overridden by individual margin flags.",
    )
    parser.add_argument("--margin-left", type=float, default=None, help="Left margin in inches (overrides --margin)")
    parser.add_argument("--margin-right", type=float, default=None, help="Right margin in inches (overrides --margin)")
    parser.add_argument("--margin-top", type=float, default=None, help="Top margin in inches (overrides --margin)")
    parser.add_argument("--margin-bottom", type=float, default=None, help="Bottom margin in inches (overrides --margin)")
    parser.add_argument(
        "--orientation", choices=["portrait", "landscape"],
        default=None,
        help="Force sheet orientation: portrait (tall) or landscape (wide)",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    sheet_size = parse_sheet_size(args.sheet)

    # Apply orientation override
    sw, sh = sheet_size
    if args.orientation == "portrait" and sw > sh:
        sheet_size = (sh, sw)
    elif args.orientation == "landscape" and sh > sw:
        sheet_size = (sh, sw)

    print(f"Sheet: {sheet_size[0]:.1f} x {sheet_size[1]:.1f} pt "
          f"({sheet_size[0]/MM_TO_PT:.1f} x {sheet_size[1]/MM_TO_PT:.1f} mm)")
    print()

    impose(
        input_path=args.input,
        sheet_size=sheet_size,
        output_path=args.output,
        outline=args.outline,
        marks=args.marks,
        margin=args.margin * IN_TO_PT,
        margin_left=args.margin_left * IN_TO_PT if args.margin_left is not None else None,
        margin_right=args.margin_right * IN_TO_PT if args.margin_right is not None else None,
        margin_top=args.margin_top * IN_TO_PT if args.margin_top is not None else None,
        margin_bottom=args.margin_bottom * IN_TO_PT if args.margin_bottom is not None else None,
    )


if __name__ == "__main__":
    main()
