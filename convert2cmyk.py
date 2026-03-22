#!/usr/bin/env python3
"""
Convert PDF from RGB to CMYK color space.

Converts images, vector content, and text color operators from RGB to CMYK.
- Images: extracted, ICC-converted via Pillow, and replaced
- Content streams: RGB operators (rg/RG) rewritten to CMYK operators (k/K)
- Resource color spaces: ICCBased-RGB and DeviceRGB entries replaced with DeviceCMYK

Usage:
    python convert2cmyk.py input.pdf
    python convert2cmyk.py input.pdf -o output_cmyk.pdf
    python convert2cmyk.py input.pdf --rgb-profile sRGB.icc --cmyk-profile USWebCoatedSWOP.icc
"""

import argparse
import io
import re
import sys
from pathlib import Path

import pikepdf
from PIL import Image, ImageCms


# ---------- default ICC profile paths ----------

# macOS system profiles
_SYSTEM_PROFILES = "/System/Library/ColorSync/Profiles"
_DEFAULT_RGB_PROFILE = None  # use sRGB built-in
_DEFAULT_CMYK_PROFILE = f"{_SYSTEM_PROFILES}/Generic CMYK Profile.icc"


def _get_rgb_profile(path=None):
    """Return an RGB ICC profile (PIL CmsProfile)."""
    if path:
        return ImageCms.getOpenProfile(path)
    return ImageCms.createProfile("sRGB")


def _get_cmyk_profile(path=None):
    """Return a CMYK ICC profile (PIL CmsProfile)."""
    p = path or _DEFAULT_CMYK_PROFILE
    if not Path(p).exists():
        print(f"Error: CMYK ICC profile not found: {p}")
        print("Provide one with --cmyk-profile")
        sys.exit(1)
    return ImageCms.getOpenProfile(p)


def _convert_image_to_cmyk(image_data, rgb_profile, cmyk_profile, rendering_intent=1):
    """
    Convert a PIL Image to CMYK using ICC profiles.
    rendering_intent: 0=Perceptual, 1=Relative Colorimetric, 2=Saturation, 3=Absolute
    Returns the converted PIL Image.
    """
    img = image_data

    # Already CMYK — nothing to do
    if img.mode == "CMYK":
        return img

    # Convert to RGB first if needed (e.g. palette, grayscale, RGBA)
    if img.mode == "RGBA":
        # Flatten alpha onto white background
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    transform = ImageCms.buildTransform(
        rgb_profile, cmyk_profile, "RGB", "CMYK",
        renderingIntent=rendering_intent,
    )
    return ImageCms.applyTransform(img, transform)


def _image_from_pikepdf(pdf_image):
    """Extract a PIL Image from a pikepdf image object."""
    return pdf_image.as_pil_image()


def _replace_image(pdf_image_obj, pil_cmyk, pdf):
    """Replace a pikepdf image stream with CMYK JPEG data (DCTDecode)."""
    w, h = pil_cmyk.size

    # Write CMYK JPEG — PDF supports CMYK JPEG natively via DCTDecode
    jpeg_buf = io.BytesIO()
    pil_cmyk.save(jpeg_buf, format="JPEG", quality=95)
    jpeg_data = jpeg_buf.getvalue()

    # Write raw JPEG bytes with DCTDecode — PDF reads them directly
    pdf_image_obj.write(jpeg_data)
    pdf_image_obj.Width = w
    pdf_image_obj.Height = h
    pdf_image_obj.ColorSpace = pikepdf.Name.DeviceCMYK
    pdf_image_obj.BitsPerComponent = 8
    pdf_image_obj[pikepdf.Name.Filter] = pikepdf.Name.DCTDecode
    # Pillow writes CMYK JPEG with inverted values (0=full ink)
    # Decode array tells PDF to invert back: 1→0 means flip
    pdf_image_obj[pikepdf.Name.Decode] = pikepdf.Array(
        [1, 0, 1, 0, 1, 0, 1, 0]
    )
    # Clean up old encoding params
    if pikepdf.Name.DecodeParms in pdf_image_obj:
        del pdf_image_obj[pikepdf.Name.DecodeParms]


def _rgb_to_cmyk_color(r, g, b):
    """Convert RGB floats (0-1) to CMYK floats (0-1)."""
    k = 1.0 - max(r, g, b)
    if k >= 1.0:
        return (0.0, 0.0, 0.0, 1.0)
    c = (1.0 - r - k) / (1.0 - k)
    m = (1.0 - g - k) / (1.0 - k)
    y = (1.0 - b - k) / (1.0 - k)
    return (c, m, y, k)


def _convert_content_stream(data):
    """
    Rewrite RGB color operators in a PDF content stream to CMYK.
    - rg (fill RGB) → k (fill CMYK)
    - RG (stroke RGB) → K (stroke CMYK)
    - cs/CS with DeviceRGB → cs/CS with DeviceCMYK
    Returns (new_data_bytes, conversion_count).
    """
    text = data.decode("latin-1")
    count = 0

    def _replace_rgb_op(match):
        nonlocal count
        r = float(match.group(1))
        g = float(match.group(2))
        b = float(match.group(3))
        op = match.group(4)  # 'rg' or 'RG'
        c, m, y, k = _rgb_to_cmyk_color(r, g, b)
        cmyk_op = "k" if op == "rg" else "K"
        count += 1
        return f"{c:.4f} {m:.4f} {y:.4f} {k:.4f} {cmyk_op}"

    # Match: R G B rg  or  R G B RG
    pattern = r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(rg|RG)\b"
    text = re.sub(pattern, _replace_rgb_op, text)

    # Replace /DeviceRGB references in cs/CS operators
    text = re.sub(r"/DeviceRGB\s+cs\b", "/DeviceCMYK cs", text)
    text = re.sub(r"/DeviceRGB\s+CS\b", "/DeviceCMYK CS", text)

    return text.encode("latin-1"), count


def _convert_resource_colorspaces(resources, pdf):
    """
    Replace ICCBased-RGB and DeviceRGB entries in the page's
    /Resources/ColorSpace dictionary with DeviceCMYK.
    Returns number of entries converted.
    """
    count = 0
    if "/ColorSpace" not in resources:
        return count

    cs_dict = resources["/ColorSpace"]
    keys_to_convert = []

    for name, cs_obj in cs_dict.items():
        resolved = cs_obj
        if isinstance(resolved, pikepdf.Object):
            try:
                resolved = resolved.resolve() if hasattr(resolved, 'resolve') else resolved
            except Exception:
                pass

        cs_str = str(resolved)

        # Direct /DeviceRGB
        if resolved == pikepdf.Name.DeviceRGB:
            keys_to_convert.append(name)
            continue

        # Array form [/ICCBased stream] — check if it's 3-component (RGB)
        if isinstance(resolved, pikepdf.Array) and len(resolved) >= 2:
            if str(resolved[0]) == "/ICCBased":
                try:
                    stream = resolved[1]
                    if isinstance(stream, pikepdf.Object):
                        stream = stream.resolve() if hasattr(stream, 'resolve') else stream
                    n = int(stream.get("/N", 0))
                    if n == 3:  # RGB
                        keys_to_convert.append(name)
                except Exception:
                    pass

    for name in keys_to_convert:
        cs_dict[name] = pikepdf.Name.DeviceCMYK
        count += 1

    return count


def convert_to_cmyk(
    input_path: str,
    output_path: str | None = None,
    rgb_profile_path: str | None = None,
    cmyk_profile_path: str | None = None,
    rendering_intent: int = 1,
):
    """Convert all RGB content in a PDF to CMYK — images, vectors, and text."""
    rgb_prof = _get_rgb_profile(rgb_profile_path)
    cmyk_prof = _get_cmyk_profile(cmyk_profile_path)

    pdf = pikepdf.Pdf.open(input_path)
    img_converted = 0
    img_skipped = 0
    stream_converted = 0
    cs_converted = 0

    for page_num, page in enumerate(pdf.pages, 1):
        if "/Resources" not in page:
            continue
        resources = page["/Resources"]

        # --- Convert resource color space entries ---
        rc = _convert_resource_colorspaces(resources, pdf)
        if rc:
            cs_converted += rc
            print(f"  Page {page_num}: converted {rc} resource color space(s) to DeviceCMYK")

        # --- Convert content stream RGB operators ---
        if "/Contents" in page:
            contents = page["/Contents"]
            if isinstance(contents, pikepdf.Array):
                streams = [s.resolve() if hasattr(s, 'resolve') else s for s in contents]
            else:
                resolved = contents.resolve() if hasattr(contents, 'resolve') else contents
                streams = [resolved]

            for stream in streams:
                try:
                    raw = stream.read_bytes()
                    new_data, cnt = _convert_content_stream(raw)
                    if cnt > 0:
                        stream.write(new_data)
                        stream_converted += cnt
                        print(f"  Page {page_num}: converted {cnt} RGB color operator(s) to CMYK")
                except Exception as e:
                    print(f"  Page {page_num}: could not process content stream: {e}")

        # --- Convert images ---
        if "/XObject" not in resources:
            continue

        xobjects = resources["/XObject"]
        for name, obj_ref in xobjects.items():
            obj = obj_ref
            if not isinstance(obj, pikepdf.Stream):
                continue
            if obj.get("/Subtype") != pikepdf.Name.Image:
                continue

            # Check color space
            cs = obj.get("/ColorSpace")
            if cs is None:
                cs = pikepdf.Name.DeviceRGB

            # Resolve arrays (e.g. [/ICCBased stream])
            is_rgb = False
            if isinstance(cs, pikepdf.Name):
                cs_name = str(cs)
                if "CMYK" in cs_name or "Gray" in cs_name:
                    img_skipped += 1
                    continue
                if "RGB" in cs_name:
                    is_rgb = True
            elif isinstance(cs, pikepdf.Array) and len(cs) >= 2:
                if str(cs[0]) == "/ICCBased":
                    try:
                        s = cs[1]
                        if hasattr(s, 'resolve'):
                            s = s.resolve()
                        n = int(s.get("/N", 0))
                        if n == 4:
                            img_skipped += 1
                            continue
                        if n == 1:
                            img_skipped += 1
                            continue
                        if n == 3:
                            is_rgb = True
                    except Exception:
                        pass

            if not is_rgb:
                img_skipped += 1
                continue

            try:
                pdfimg = pikepdf.PdfImage(obj)
                pil_img = pdfimg.as_pil_image()
                cmyk_img = _convert_image_to_cmyk(
                    pil_img, rgb_prof, cmyk_prof, rendering_intent
                )
                _replace_image(obj, cmyk_img, pdf)
                img_converted += 1
                print(f"  Page {page_num}: converted image '{name}' "
                      f"({pil_img.size[0]}x{pil_img.size[1]}) to CMYK")
            except Exception as e:
                print(f"  Page {page_num}: skipped image '{name}': {e}")
                img_skipped += 1

    if not output_path:
        stem = Path(input_path).stem
        output_path = str(Path(input_path).parent / f"{stem}_cmyk.pdf")

    pdf.save(output_path)
    pdf.close()

    print(f"\nImages converted:        {img_converted}")
    print(f"Images skipped:          {img_skipped} (already CMYK/Gray)")
    print(f"Color operators changed: {stream_converted}")
    print(f"Color spaces changed:    {cs_converted}")
    print(f"Output:                  {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF images from RGB to CMYK color space",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Rendering intents:\n"
            "  0 = Perceptual (best for photos)\n"
            "  1 = Relative Colorimetric (default, preserves white point)\n"
            "  2 = Saturation (best for business graphics)\n"
            "  3 = Absolute Colorimetric (proof simulation)\n"
        ),
    )
    parser.add_argument("input", help="Input PDF file")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <input>_cmyk.pdf)",
    )
    parser.add_argument(
        "--rgb-profile", default=None,
        help="RGB ICC profile path (default: built-in sRGB)",
    )
    parser.add_argument(
        "--cmyk-profile", default=None,
        help=f"CMYK ICC profile path (default: {_DEFAULT_CMYK_PROFILE})",
    )
    parser.add_argument(
        "--intent", type=int, default=1, choices=[0, 1, 2, 3],
        help="ICC rendering intent (default: 1 = Relative Colorimetric)",
    )

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: File not found: {args.input}")
        sys.exit(1)

    print(f"Converting: {args.input}")
    print(f"CMYK profile: {args.cmyk_profile or _DEFAULT_CMYK_PROFILE}")
    print()

    convert_to_cmyk(
        input_path=args.input,
        output_path=args.output,
        rgb_profile_path=args.rgb_profile,
        cmyk_profile_path=args.cmyk_profile,
        rendering_intent=args.intent,
    )


if __name__ == "__main__":
    main()
