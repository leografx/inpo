# Inpo — PDF Imposition & Prepress Tools

A suite of Python scripts for PDF imposition, cropping, and prepress preparation.

## Requirements

```
pip install pypdf reportlab pikepdf Pillow
```

## Tools

### impose.py — PDF Imposition

Takes an input PDF and a sheet size, then tiles as many copies of each page as possible onto the sheet. Uses the CropBox to determine layout and automatically rotates pages for maximum yield.

```
python impose.py <input.pdf> --sheet <size> [options]
```

**Required arguments:**

| Argument | Description |
|----------|-------------|
| `input` | Input PDF file |
| `--sheet`, `-s` | Sheet size (preset name or WxH with unit) |

**Optional arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--output`, `-o` | `<input>_imposed.pdf` | Output PDF path |
| `--margin` | `0.375` | Uniform margin around the sheet in inches |
| `--margin-left` | `--margin` | Left margin in inches (overrides `--margin`) |
| `--margin-right` | `--margin` | Right margin in inches (overrides `--margin`) |
| `--margin-top` | `--margin` | Top margin in inches (overrides `--margin`) |
| `--margin-bottom` | `--margin` | Bottom margin in inches (overrides `--margin`) |
| `--orientation` | auto | Force sheet orientation: `portrait` (tall) or `landscape` (wide) |
| `--outline` | off | Draw debug overlay (red trim, blue bleed, orange group box, green trim guides, black crop marks) |
| `--marks` | off | Draw crop marks only (no overlay boxes) |

**Sheet size formats:**

| Format | Example | Notes |
|--------|---------|-------|
| Preset name | `a3`, `sra3`, `tabloid`, `13x19` | See full list below |
| Custom (mm) | `320x450mm` or `320x450` | mm is the default unit |
| Custom (in) | `13x19in` | |
| Custom (pt) | `936x1296pt` | 72pt = 1 inch |

**Available presets:** `12x18`, `13x19`, `a0`, `a1`, `a2`, `a3`, `a4`, `a5`, `b3`, `b4`, `b5`, `ledger`, `legal`, `letter`, `sra3`, `sra4`, `tabloid`

**Examples:**

```bash
# Basic imposition onto SRA3 sheet
python impose.py flyer.pdf --sheet sra3

# Custom sheet size with crop marks
python impose.py card.pdf --sheet 320x450mm --marks

# Tabloid with debug overlay and custom margin
python impose.py label.pdf --sheet tabloid --outline --margin 0.5

# Force landscape orientation
python impose.py card.pdf --sheet a3 --orientation landscape --marks

# No margin (edge-to-edge)
python impose.py sticker.pdf --sheet 13x19in --margin 0

# Independent margins (gripper edge needs more space)
python impose.py card.pdf --sheet sra3 --margin-left 0.5 --margin-right 0.25 --marks

# Custom output path
python impose.py input.pdf --sheet a3 -o output_imposed.pdf
```

**How it works:**

1. Reads each page's CropBox to determine tile size
2. Tests both orientations (normal and rotated 90°) to maximize yield
3. Tiles pages edge-to-edge (butted together by CropBox) within the available area (sheet minus margins)
4. Centers the grid on the sheet
5. Applies a white mask to clip content outside CropBox boundaries
6. Optionally adds crop marks (`--marks`) or a full debug overlay (`--outline`)

**Duplex handling:**

Pages are treated as front/back pairs for double-sided printing:
- Odd pages (1, 3, 5…) are **fronts** — layout is calculated normally
- Even pages (2, 4, 6…) are **backs** — use the same grid but:
  - Columns are **mirrored** (reversed left-to-right) so content aligns when the sheet is flipped
  - Rotation is **opposite** to the front (if front rotates 90° CW, back rotates 90° CCW)
- If the PDF has an odd number of pages, the last page is treated as front-only

---

### crop2bleed.py — Crop to Bleed

Sets each page's CropBox and MediaBox to its BleedBox, stripping everything outside the bleed area.

```
python crop2bleed.py <input.pdf> [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | — | Input PDF file |
| `--output`, `-o` | `<input>_cropped.pdf` | Output PDF path |

```bash
python crop2bleed.py input.pdf
python crop2bleed.py input.pdf -o output.pdf
```

---

### crop2trim.py — Crop to Trim

Sets each page's CropBox and MediaBox to its TrimBox, producing a PDF at the final cut size.

```
python crop2trim.py <input.pdf> [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | — | Input PDF file |
| `--output`, `-o` | `<input>_trimmed.pdf` | Output PDF path |

```bash
python crop2trim.py input.pdf
python crop2trim.py input.pdf -o output.pdf
```

---

### removeMarks.py — Remove Marks

Masks all content outside the BleedBox (printer marks, slugs, registration marks, etc.) with a white fill. Preserves the original page size.

```
python removeMarks.py <input.pdf> [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | — | Input PDF file |
| `--output`, `-o` | `<input>_clean.pdf` | Output PDF path |

```bash
python removeMarks.py input.pdf
python removeMarks.py input.pdf -o output.pdf
```

---

### merge.py — Merge PDFs

Merges multiple PDF files into a single PDF. Files are combined in the order given, with optional sorting.

```
python merge.py <file1.pdf> <file2.pdf> [file3.pdf ...] [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `inputs` | — | Two or more input PDF files |
| `--output`, `-o` | `merged.pdf` | Output PDF path |
| `--sort` | none | Sort files before merging: `name`, `date`, or `size` |
| `--reverse` | off | Reverse the sort order |

```bash
# Merge in specified order
python merge.py cover.pdf body.pdf appendix.pdf -o book.pdf

# Merge all PDFs in directory, sorted by name
python merge.py *.pdf --sort name

# Merge sorted by date (newest last), reversed (newest first)
python merge.py *.pdf --sort date --reverse
```

---

### pdfinfo.py — PDF Info

Outputs all page box dimensions (MediaBox, CropBox, BleedBox, TrimBox, ArtBox) and color space information in JSON format, with sizes in points, inches, and millimeters.

```
python pdfinfo.py <input.pdf> [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | — | Input PDF file |
| `--output`, `-o` | stdout | Output JSON file path |
| `--pretty`, `-p` | off | Pretty-print JSON with indentation |

```bash
# Print to terminal
python pdfinfo.py input.pdf --pretty

# Save to file
python pdfinfo.py input.pdf -o info.json
```

**Example output:**

```json
{
  "file": "/path/to/input.pdf",
  "page_count": 1,
  "pages": [
    {
      "page": 1,
      "boxes": {
        "mediabox": {
          "origin": {"x_pt": 0, "y_pt": 0},
          "size": {
            "width_pt": 612, "height_pt": 792,
            "width_in": 8.5, "height_in": 11.0,
            "width_mm": 215.9, "height_mm": 279.4
          },
          "rect_pt": [0, 0, 612, 792]
        },
        "trimbox": { "..." : "..." }
      },
      "color": {
        "color_spaces": ["DeviceCMYK", "DeviceGray"],
        "images": {"count": 2, "color_spaces": ["ICCBased-CMYK"]},
        "spot_colors": ["PANTONE 186 C"]
      }
    }
  ],
  "color_summary": {
    "color_spaces": ["DeviceCMYK", "DeviceGray", "ICCBased-CMYK", "Separation(PANTONE 186 C)"],
    "spot_colors": ["PANTONE 186 C"],
    "has_rgb": false,
    "has_cmyk": true,
    "has_gray": true,
    "has_spot": true
  }
}
```

---

### convert2cmyk.py — Convert to CMYK

Converts all RGB images in a PDF to CMYK color space using ICC profiles. Already-CMYK and grayscale images are left untouched.

```
python convert2cmyk.py <input.pdf> [options]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | — | Input PDF file |
| `--output`, `-o` | `<input>_cmyk.pdf` | Output PDF path |
| `--rgb-profile` | built-in sRGB | Path to RGB ICC profile |
| `--cmyk-profile` | System Generic CMYK | Path to CMYK ICC profile |
| `--intent` | `1` | ICC rendering intent (0=Perceptual, 1=Relative Colorimetric, 2=Saturation, 3=Absolute) |

```bash
# Basic conversion using system defaults
python convert2cmyk.py input.pdf

# With custom ICC profiles
python convert2cmyk.py input.pdf --cmyk-profile USWebCoatedSWOP.icc

# Perceptual intent (best for photos)
python convert2cmyk.py input.pdf --intent 0

# Custom output path
python convert2cmyk.py input.pdf -o print_ready.pdf
```

---

## PDF Box Reference

| Box | Purpose |
|-----|---------|
| **MediaBox** | Full page size including all content |
| **CropBox** | Visible area when displayed; drives imposition layout |
| **BleedBox** | Content area including bleed allowance |
| **TrimBox** | Final cut size (finished piece) |

Typical nesting: MediaBox >= CropBox >= BleedBox >= TrimBox

## Common Workflows

**Impose with crop marks for print:**
```bash
python impose.py artwork.pdf --sheet sra3 --marks
```

**Clean up marks, then impose:**
```bash
python removeMarks.py artwork.pdf -o artwork_clean.pdf
python impose.py artwork_clean.pdf --sheet 13x19in --marks
```

**Crop to final size:**
```bash
python crop2trim.py artwork.pdf
```

**Convert to CMYK and impose for print:**
```bash
python convert2cmyk.py artwork.pdf -o artwork_cmyk.pdf
python impose.py artwork_cmyk.pdf --sheet sra3 --marks
```

**Preview imposition layout:**
```bash
python impose.py artwork.pdf --sheet sra3 --outline
```
