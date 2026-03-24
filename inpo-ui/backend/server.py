#!/Users/leom1/miniconda3/bin/python3
"""
Inpo Web API — Flask backend for the PDF imposition pipeline.

Runs the pipeline: removeMarks → crop2bleed → convert2cmyk → impose
and serves the resulting PDF for preview.

Start:
    cd inpo-ui/backend
    python server.py
"""

import os
import sys
import uuid
import shutil
import time
import json
from pathlib import Path

from flask import Flask, request, jsonify, send_file, abort
from flask_cors import CORS

# Add parent (Inpo root) to path so we can import the scripts
INPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(INPO_ROOT))

# Disable pypdf stream length limit BEFORE any pypdf-using modules are imported
import pypdf.filters as _pf
_pf.MAX_DECLARED_STREAM_LENGTH = 10_000_000_000

from removeMarks import remove_marks
from crop2bleed import crop_to_bleed
from convert2cmyk import convert_to_cmyk
from impose import impose, parse_sheet_size, PRESETS
from pdfinfo import pdf_info

app = Flask(__name__)
CORS(app)

UPLOAD_DIR = Path("/tmp/inpo-jobs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_JOB_AGE_SECS = 3600  # 1 hour


def _cleanup_old_jobs():
    """Remove job directories older than MAX_JOB_AGE_SECS."""
    now = time.time()
    try:
        for d in UPLOAD_DIR.iterdir():
            if d.is_dir() and (now - d.stat().st_mtime) > MAX_JOB_AGE_SECS:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def _job_dir(job_id):
    """Return the job directory path, abort 404 if not found."""
    d = UPLOAD_DIR / job_id
    if not d.exists():
        abort(404, description="Job not found")
    return d


@app.route("/api/presets", methods=["GET"])
def get_presets():
    """Return available sheet size presets."""
    presets = {}
    for name, (w, h) in sorted(PRESETS.items()):
        presets[name] = {
            "width_pt": round(w, 2),
            "height_pt": round(h, 2),
            "width_in": round(w / 72, 2),
            "height_in": round(h / 72, 2),
            "width_mm": round(w * 25.4 / 72, 1),
            "height_mm": round(h * 25.4 / 72, 1),
        }
    return jsonify(presets)


@app.route("/api/upload", methods=["POST"])
def upload():
    """Upload a PDF file and return job ID + PDF info."""
    _cleanup_old_jobs()

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "File must be a PDF"}), 400

    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)

    input_path = job_dir / "input.pdf"
    f.save(str(input_path))

    try:
        info = pdf_info(str(input_path))
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": f"Invalid PDF: {e}"}), 400

    return jsonify({
        "job_id": job_id,
        "filename": f.filename,
        "info": info,
    })


@app.route("/api/process", methods=["POST"])
def process():
    """Run the imposition pipeline on an uploaded PDF."""
    data = request.get_json()
    if not data or "job_id" not in data:
        return jsonify({"error": "Missing job_id"}), 400

    job_id = data["job_id"]
    job_dir = _job_dir(job_id)
    input_path = job_dir / "input.pdf"

    if not input_path.exists():
        return jsonify({"error": "Input file not found"}), 404

    current_file = str(input_path)
    steps_completed = []

    try:
        # Step 1: Remove marks
        if data.get("remove_marks", True):
            out = str(job_dir / "step1_clean.pdf")
            remove_marks(current_file, output_path=out)
            current_file = out
            steps_completed.append("remove_marks")

        # Step 2: Crop to bleed
        if data.get("crop_to_bleed", True):
            out = str(job_dir / "step2_cropped.pdf")
            crop_to_bleed(current_file, output_path=out)
            current_file = out
            steps_completed.append("crop_to_bleed")

        # Step 3: Convert to CMYK
        if data.get("convert_to_cmyk", True):
            out = str(job_dir / "step3_cmyk.pdf")
            intent = data.get("cmyk_intent", 1)
            convert_to_cmyk(
                current_file,
                output_path=out,
                rendering_intent=intent,
            )
            current_file = out
            steps_completed.append("convert_to_cmyk")

        # Step 4: Impose
        sheet_spec = data.get("sheet", "sra3")
        sheet_size = parse_sheet_size(sheet_spec)

        # Apply orientation
        orientation = data.get("orientation")
        sw, sh = sheet_size
        if orientation == "portrait" and sw > sh:
            sheet_size = (sh, sw)
        elif orientation == "landscape" and sh > sw:
            sheet_size = (sh, sw)

        margin_in = float(data.get("margin", 0.375))
        outline = data.get("outline", False)
        marks = data.get("marks", False)

        # Independent margins (in inches → points)
        margins = data.get("margins", {})
        ml = float(margins.get("left", margin_in)) * 72 if margins.get("left") is not None else None
        mr = float(margins.get("right", margin_in)) * 72 if margins.get("right") is not None else None
        mt = float(margins.get("top", margin_in)) * 72 if margins.get("top") is not None else None
        mb = float(margins.get("bottom", margin_in)) * 72 if margins.get("bottom") is not None else None

        result_path = str(job_dir / "result.pdf")
        _, layout_result = impose(
            input_path=current_file,
            sheet_size=sheet_size,
            output_path=result_path,
            outline=outline,
            marks=marks,
            margin=margin_in * 72,
            margin_left=ml,
            margin_right=mr,
            margin_top=mt,
            margin_bottom=mb,
        )
        steps_completed.append("impose")

        # Get result info
        result_info = pdf_info(result_path)

        return jsonify({
            "job_id": job_id,
            "steps_completed": steps_completed,
            "result_url": f"/api/jobs/{job_id}/result.pdf",
            "result_info": result_info,
            "layout": layout_result,
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "steps_completed": steps_completed,
            "failed_step": len(steps_completed),
        }), 500


@app.route("/api/jobs/<job_id>/input.pdf", methods=["GET"])
def get_input(job_id):
    """Serve the original uploaded PDF."""
    job_dir = _job_dir(job_id)
    f = job_dir / "input.pdf"
    if not f.exists():
        abort(404)
    return send_file(str(f), mimetype="application/pdf")


@app.route("/api/jobs/<job_id>/result.pdf", methods=["GET"])
def get_result(job_id):
    """Serve the final imposed PDF."""
    job_dir = _job_dir(job_id)
    f = job_dir / "result.pdf"
    if not f.exists():
        abort(404)
    return send_file(str(f), mimetype="application/pdf")


@app.route("/api/jobs/<job_id>/info", methods=["GET"])
def get_info(job_id):
    """Return PDF info for the uploaded file."""
    job_dir = _job_dir(job_id)
    f = job_dir / "input.pdf"
    if not f.exists():
        abort(404)
    return jsonify(pdf_info(str(f)))


@app.route("/api/jobs/<job_id>/set-boxes", methods=["POST"])
def set_boxes(job_id):
    """
    Set page box dimensions on the uploaded PDF.
    Body: { pages: [ { page: 1, mediabox: [x,y,w,h], cropbox: ..., bleedbox: ..., trimbox: ... } ] }
    Values are in points. Omit a box key to leave it unchanged.
    """
    from pypdf import PdfReader as _PdfReader, PdfWriter as _PdfWriter
    from pypdf.generic import ArrayObject as _Arr, FloatObject as _Fl, NameObject as _Name

    job_dir = _job_dir(job_id)
    input_path = job_dir / "input.pdf"
    if not input_path.exists():
        abort(404)

    data = request.get_json()
    if not data or "pages" not in data:
        return jsonify({"error": "Missing pages array"}), 400

    reader = _PdfReader(str(input_path))
    writer = _PdfWriter()

    # Build lookup of changes: page_num -> {box_name: [x,y,w,h]}
    changes = {}
    for entry in data["pages"]:
        pg = entry.get("page")
        if pg is not None:
            changes[pg] = entry

    for i, page in enumerate(reader.pages):
        pg_num = i + 1
        ch = changes.get(pg_num, {})

        box_map = {
            "mediabox": "/MediaBox",
            "cropbox": "/CropBox",
            "bleedbox": "/BleedBox",
            "trimbox": "/TrimBox",
        }

        for key, pdf_key in box_map.items():
            vals = ch.get(key)
            if vals and len(vals) == 4:
                x, y, w, h = [float(v) for v in vals]
                page[_Name(pdf_key)] = _Arr([
                    _Fl(x), _Fl(y), _Fl(x + w), _Fl(y + h),
                ])

        writer.add_page(page)

    # Overwrite the input file
    with open(str(input_path), "wb") as f:
        writer.write(f)

    info = pdf_info(str(input_path))
    return jsonify({"info": info})


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    """Clean up a job directory."""
    job_dir = _job_dir(job_id)
    shutil.rmtree(job_dir, ignore_errors=True)
    return jsonify({"deleted": job_id})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve frontend static files in dev mode (no nginx needed)."""
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if path and (frontend_dir / path).exists():
        return send_file(str(frontend_dir / path))
    return send_file(str(frontend_dir / "index.html"))


if __name__ == "__main__":
    print(f"Inpo root: {INPO_ROOT}")
    print(f"Upload dir: {UPLOAD_DIR}")
    print(f"Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=True)
