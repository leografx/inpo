#!/usr/bin/env python3
"""
PDF Info — Output page box dimensions and color info in JSON format.

Reports MediaBox, CropBox, BleedBox, TrimBox, and ArtBox for every page,
with sizes in points, inches, and millimeters. Also reports color spaces
used by each page (images and content streams) and spot/separation colors.

Usage:
    python pdfinfo.py input.pdf
    python pdfinfo.py input.pdf --pretty
    python pdfinfo.py input.pdf -o info.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from pypdf import PdfReader
import pypdf.filters as pf
pf.MAX_DECLARED_STREAM_LENGTH = 10_000_000_000

MM_PER_PT = 25.4 / 72
IN_PER_PT = 1 / 72

BOX_NAMES = ["mediabox", "cropbox", "bleedbox", "trimbox", "artbox"]


def _box_data(page, box_name):
    """Extract box coordinates and dimensions, or None if not defined."""
    box = getattr(page, box_name, None)
    if box is None:
        return None

    x0 = float(box.left)
    y0 = float(box.bottom)
    x1 = float(box.right)
    y1 = float(box.top)
    w = x1 - x0
    h = y1 - y0

    return {
        "origin": {"x_pt": round(x0, 4), "y_pt": round(y0, 4)},
        "size": {
            "width_pt": round(w, 4),
            "height_pt": round(h, 4),
            "width_in": round(w * IN_PER_PT, 4),
            "height_in": round(h * IN_PER_PT, 4),
            "width_mm": round(w * MM_PER_PT, 2),
            "height_mm": round(h * MM_PER_PT, 2),
        },
        "rect_pt": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
    }


def _resolve_colorspace(cs):
    """Resolve a color space object to a readable name string or list of names."""
    results = set()

    if cs is None:
        return results

    # Direct name like /DeviceRGB
    if hasattr(cs, "name") or isinstance(cs, str):
        name = str(cs).lstrip("/")
        results.add(name)
        return results

    # Array form: [/ICCBased stream], [/Separation name alt_cs tintFunc], etc.
    from pypdf.generic import ArrayObject, IndirectObject
    if isinstance(cs, ArrayObject) and len(cs) > 0:
        cs_type = str(cs[0]).lstrip("/")

        if cs_type == "ICCBased":
            # Try to get the number of components from the stream dict
            try:
                stream = cs[1]
                if isinstance(stream, IndirectObject):
                    stream = stream.get_object()
                n = int(stream.get("/N", 0))
                icc_map = {1: "ICCBased-Gray", 3: "ICCBased-RGB", 4: "ICCBased-CMYK"}
                results.add(icc_map.get(n, f"ICCBased-{n}ch"))
            except Exception:
                results.add("ICCBased")

        elif cs_type == "Separation":
            # [/Separation /SpotName /AlternateCS tintTransform]
            try:
                spot_name = str(cs[1]).lstrip("/")
                results.add(f"Separation({spot_name})")
            except Exception:
                results.add("Separation")

        elif cs_type == "DeviceN":
            # [/DeviceN [/names...] /AlternateCS tintTransform]
            try:
                names = [str(n).lstrip("/") for n in cs[1]]
                results.add(f"DeviceN({','.join(names)})")
            except Exception:
                results.add("DeviceN")

        elif cs_type == "Indexed":
            # [/Indexed baseCS hival lookup]
            try:
                base = _resolve_colorspace(cs[1])
                for b in base:
                    results.add(f"Indexed({b})")
            except Exception:
                results.add("Indexed")

        elif cs_type == "Pattern":
            results.add("Pattern")

        else:
            results.add(cs_type)

    return results


def _get_page_color_info(page):
    """Extract color space information from a page's resources."""
    color_spaces = set()
    image_color_spaces = set()
    spot_colors = []
    image_count = 0

    resources = page.get("/Resources")
    if resources is None:
        return {"color_spaces": [], "images": {"count": 0, "color_spaces": []}, "spot_colors": []}

    # --- Color spaces defined in /Resources/ColorSpace ---
    cs_dict = resources.get("/ColorSpace")
    if cs_dict is not None:
        try:
            for name, cs_obj in cs_dict.items():
                from pypdf.generic import IndirectObject
                if isinstance(cs_obj, IndirectObject):
                    cs_obj = cs_obj.get_object()
                resolved = _resolve_colorspace(cs_obj)
                color_spaces.update(resolved)
        except Exception:
            pass

    # --- Images in /Resources/XObject ---
    xobjects = resources.get("/XObject")
    if xobjects is not None:
        try:
            for name, obj_ref in xobjects.items():
                from pypdf.generic import IndirectObject
                obj = obj_ref
                if isinstance(obj, IndirectObject):
                    obj = obj.get_object()
                if not hasattr(obj, "get"):
                    continue
                if str(obj.get("/Subtype", "")) != "/Image":
                    continue
                image_count += 1
                cs = obj.get("/ColorSpace")
                if cs is not None:
                    from pypdf.generic import IndirectObject
                    if isinstance(cs, IndirectObject):
                        cs = cs.get_object()
                    resolved = _resolve_colorspace(cs)
                    image_color_spaces.update(resolved)
        except Exception:
            pass

    # --- Detect color operators in the content stream ---
    try:
        content = page.extract_text()  # just to check it's readable
        if "/Contents" in page:
            contents = page["/Contents"]
            from pypdf.generic import IndirectObject, ArrayObject
            if isinstance(contents, IndirectObject):
                contents = contents.get_object()
            streams = []
            if isinstance(contents, ArrayObject):
                for ref in contents:
                    if isinstance(ref, IndirectObject):
                        streams.append(ref.get_object())
                    else:
                        streams.append(ref)
            else:
                streams.append(contents)

            raw = b""
            for s in streams:
                try:
                    raw += s.get_data()
                except Exception:
                    pass

            text = raw.decode("latin-1", errors="ignore")
            # Check for color-setting operators
            if re.search(r"\brg\b", text) or re.search(r"\bRG\b", text):
                color_spaces.add("DeviceRGB")
            if re.search(r"\bk\b", text) or re.search(r"\bK\b", text):
                color_spaces.add("DeviceCMYK")
            if re.search(r"\bg\b", text) or re.search(r"\bG\b", text):
                color_spaces.add("DeviceGray")
    except Exception:
        pass

    # Collect spot colors from separation entries
    for cs_name in (color_spaces | image_color_spaces):
        if cs_name.startswith("Separation("):
            spot = cs_name[len("Separation("):-1]
            if spot not in spot_colors:
                spot_colors.append(spot)

    return {
        "color_spaces": sorted(color_spaces),
        "images": {
            "count": image_count,
            "color_spaces": sorted(image_color_spaces),
        },
        "spot_colors": spot_colors,
    }


def pdf_info(input_path):
    """Return a dict with page box info for the entire PDF."""
    reader = PdfReader(input_path)
    result = {
        "file": str(Path(input_path).resolve()),
        "page_count": len(reader.pages),
        "pages": [],
    }

    all_color_spaces = set()
    all_spot_colors = []

    for i, page in enumerate(reader.pages, 1):
        page_data = {"page": i, "boxes": {}}
        for box_name in BOX_NAMES:
            data = _box_data(page, box_name)
            if data is not None:
                page_data["boxes"][box_name] = data

        # Color info
        color_info = _get_page_color_info(page)
        page_data["color"] = color_info
        all_color_spaces.update(color_info["color_spaces"])
        all_color_spaces.update(color_info["images"]["color_spaces"])
        for sc in color_info["spot_colors"]:
            if sc not in all_spot_colors:
                all_spot_colors.append(sc)

        result["pages"].append(page_data)

    # Document-level color summary
    result["color_summary"] = {
        "color_spaces": sorted(all_color_spaces),
        "spot_colors": all_spot_colors,
        "has_rgb": any("RGB" in cs for cs in all_color_spaces),
        "has_cmyk": any("CMYK" in cs for cs in all_color_spaces),
        "has_gray": any("Gray" in cs for cs in all_color_spaces),
        "has_spot": len(all_spot_colors) > 0,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Output PDF page box dimensions in JSON format",
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output JSON file (default: print to stdout)",
    )
    parser.add_argument(
        "--pretty", "-p", action="store_true",
        help="Pretty-print JSON with indentation",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    info = pdf_info(args.input)
    indent = 2 if args.pretty else None
    json_str = json.dumps(info, indent=indent)

    if args.output:
        Path(args.output).write_text(json_str + "\n")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(json_str)


if __name__ == "__main__":
    main()
