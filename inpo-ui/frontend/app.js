const API = "/api";

// ---------- State ----------
const state = {
    jobId: null,
    filename: null,
    pdfInfo: null,
    resultInfo: null,
    processing: false,
    pdfDoc: null,
    currentPage: 1,
    totalPages: 0,
    previewSource: "input", // "input" or "result"
    zoomMode: "fit", // "fit" or "manual"
    zoomScale: 1.0,
};

// ---------- DOM refs ----------
const $ = (sel) => document.querySelector(sel);
const dropZone = $("#drop-zone");
const fileInput = $("#file-input");
const fileInfo = $("#file-info");
const fileName = $("#file-name");
const filePages = $("#file-pages");
const btnClear = $("#btn-clear-file");
const btnProcess = $("#btn-process");
const btnDownload = $("#btn-download");
const btnPrev = $("#btn-prev-page");
const btnNext = $("#btn-next-page");
const pageIndicator = $("#page-indicator");
const previewControls = $("#preview-controls");
const previewPlaceholder = $("#preview-placeholder");
const previewSource = $("#preview-source");
const canvas = $("#pdf-canvas");
const statusEl = $("#status");
const statusSpinner = $("#status-spinner");
const statusText = $("#status-text");
const selSheet = $("#sel-sheet");
const customSize = $("#custom-size");
const infoSection = $("#info-section");
const infoContent = $("#info-content");
const chkConvertCmyk = $("#chk-convert-cmyk");
const cmykOptions = $("#cmyk-options");
const btnZoomIn = $("#btn-zoom-in");
const btnZoomOut = $("#btn-zoom-out");
const btnZoomFit = $("#btn-zoom-fit");
const zoomLevel = $("#zoom-level");

// ---------- PDF.js setup ----------
let pdfjsLib;

async function initPdfJs() {
    pdfjsLib = await import("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs");
    pdfjsLib.GlobalWorkerOptions.workerSrc =
        "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";
}

// ---------- PDF rendering ----------
async function loadPdf(url) {
    if (!pdfjsLib) await initPdfJs();
    try {
        const doc = await pdfjsLib.getDocument(url).promise;
        state.pdfDoc = doc;
        state.totalPages = doc.numPages;
        state.currentPage = 1;
        await renderPage(1);
        updatePageControls();
        previewPlaceholder.classList.add("hidden");
        canvas.style.display = "block";
        previewControls.classList.remove("hidden");
    } catch (e) {
        console.error("PDF load error:", e);
        showStatus("Failed to load PDF preview", "error");
    }
}

function getFitScale(pageViewport) {
    const container = $("#preview-area");
    const maxW = container.clientWidth - 20;
    const maxH = container.clientHeight - 20;
    return Math.min(maxW / pageViewport.width, maxH / pageViewport.height, 2);
}

// Cache the rendered PDF so overlays can be redrawn without re-rendering the PDF
let _pdfImageData = null;
let _lastViewport = null;

async function renderPage(num) {
    if (!state.pdfDoc) return;
    const page = await state.pdfDoc.getPage(num);
    const unscaled = page.getViewport({ scale: 1 });

    let scale;
    if (state.zoomMode === "fit") {
        scale = getFitScale(unscaled);
        state.zoomScale = scale;
    } else {
        scale = state.zoomScale;
    }

    const viewport = page.getViewport({ scale });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const ctx = canvas.getContext("2d");
    await page.render({ canvasContext: ctx, viewport }).promise;

    // Cache the rendered PDF pixels
    _pdfImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    _lastViewport = viewport;

    // Draw box overlays on top
    drawBoxOverlays(ctx, viewport, scale);

    state.currentPage = num;
    updatePageControls();
    updateZoomDisplay();
    // Show grab cursor when zoomed past container OR on Page Spec tab for drag-reposition
    const area = $("#preview-area");
    requestAnimationFrame(() => {
        const overflows = area.scrollWidth > area.clientWidth || area.scrollHeight > area.clientHeight;
        const isSpecTab = document.querySelector('#tab-bar .tab[data-tab="tab-page-spec"]')?.classList.contains("active");
        area.classList.toggle("pannable", overflows || isSpecTab);
    });
}

function redrawOverlaysOnly() {
    if (!_pdfImageData || !_lastViewport) return;
    const ctx = canvas.getContext("2d");
    ctx.putImageData(_pdfImageData, 0, 0);
    drawBoxOverlays(ctx, _lastViewport, state.zoomScale);
}

// ---------- Box Overlays ----------
// Colors: media=orange, crop=red, bleed=blue, trim=green
const BOX_COLORS = {
    media:  { stroke: "rgba(255, 165, 0, 0.9)", label: "Media" },
    crop:   { stroke: "rgba(255, 0, 0, 0.9)",   label: "Crop" },
    bleed:  { stroke: "rgba(0, 100, 255, 0.9)",  label: "Bleed" },
    trim:   { stroke: "rgba(0, 160, 0, 0.9)",    label: "Trim" },
};

function getBoxValuesFromSpec(prefix) {
    const xEl = $(`#spec-${prefix}-x`);
    if (!xEl) return null;
    const x = parseFloat(xEl.value);
    const y = parseFloat($(`#spec-${prefix}-y`).value);
    const w = parseFloat($(`#spec-${prefix}-w`).value);
    const h = parseFloat($(`#spec-${prefix}-h`).value);
    if (isNaN(x) || isNaN(y) || isNaN(w) || isNaN(h)) return null;
    // Convert from display unit to points
    const f = specUnitFactor();
    return { x: x * f, y: y * f, w: w * f, h: h * f };
}

function getBoxValuesFromInfo(pageNum, boxName) {
    if (!state.pdfInfo) return null;
    const pg = state.pdfInfo.pages.find((p) => p.page === pageNum);
    if (!pg || !pg.boxes[boxName]) return null;
    const b = pg.boxes[boxName];
    return { x: b.origin.x_pt, y: b.origin.y_pt, w: b.size.width_pt, h: b.size.height_pt };
}

function drawBoxOverlays(ctx, viewport, scale) {
    if (!state.pdfInfo) return;

    // Only draw when Page Spec tab is active
    const isSpecTab = document.querySelector('#tab-bar .tab[data-tab="tab-page-spec"]').classList.contains("active");
    if (!isSpecTab) return;

    const pageNum = state.currentPage;
    const specPage = parseInt($("#spec-page-select")?.value || "0");

    // PDF coordinate system: origin bottom-left. Canvas: origin top-left.
    // viewport.height = page height in canvas pixels
    const canvasH = viewport.height;

    const boxKeys = ["media", "crop", "bleed", "trim"];
    const boxNameMap = { media: "mediabox", crop: "cropbox", bleed: "bleedbox", trim: "trimbox" };

    for (const key of boxKeys) {
        let box;
        // If viewing the edited page, read live from inputs
        if (pageNum === specPage) {
            box = getBoxValuesFromSpec(key);
        }
        // Otherwise (or if inputs empty), read from stored pdfInfo
        if (!box) {
            box = getBoxValuesFromInfo(pageNum, boxNameMap[key]);
        }
        if (!box) continue;

        const color = BOX_COLORS[key];
        // Convert PDF coords to canvas coords
        const cx = box.x * scale;
        const cy = canvasH - (box.y + box.h) * scale; // flip Y
        const cw = box.w * scale;
        const ch = box.h * scale;

        ctx.save();
        ctx.strokeStyle = color.stroke;
        ctx.lineWidth = key === "media" ? 2 : 1.5;
        if (key === "crop" || key === "media") {
            ctx.setLineDash([6, 3]);
        } else {
            ctx.setLineDash([]);
        }
        ctx.strokeRect(cx, cy, cw, ch);

        // Label
        ctx.setLineDash([]);
        ctx.font = `bold ${Math.max(10, 11 * scale)}px sans-serif`;
        ctx.fillStyle = color.stroke;
        const labelX = cx + 3;
        const labelY = cy + Math.max(12, 13 * scale);
        // Background for readability
        const metrics = ctx.measureText(color.label);
        ctx.fillStyle = "rgba(255,255,255,0.75)";
        ctx.fillRect(labelX - 1, labelY - Math.max(10, 11 * scale), metrics.width + 4, Math.max(12, 13 * scale) + 2);
        ctx.fillStyle = color.stroke;
        ctx.fillText(color.label, labelX, labelY);
        ctx.restore();
    }
}

function updatePageControls() {
    pageIndicator.textContent = `${state.currentPage} / ${state.totalPages}`;
    btnPrev.disabled = state.currentPage <= 1;
    btnNext.disabled = state.currentPage >= state.totalPages;
}

function updateZoomDisplay() {
    if (state.zoomMode === "fit") {
        zoomLevel.textContent = "Fit";
    } else {
        zoomLevel.textContent = Math.round(state.zoomScale * 100) + "%";
    }
}

function zoomIn() {
    state.zoomMode = "manual";
    state.zoomScale = Math.min(state.zoomScale * 1.25, 10);
    renderPage(state.currentPage);
}

function zoomOut() {
    state.zoomMode = "manual";
    state.zoomScale = Math.max(state.zoomScale / 1.25, 0.1);
    renderPage(state.currentPage);
}

function zoomFit() {
    state.zoomMode = "fit";
    renderPage(state.currentPage);
}

// ---------- Presets ----------
async function loadPresets() {
    try {
        const res = await fetch(`${API}/presets`);
        const presets = await res.json();
        selSheet.innerHTML = '<option value="">-- select --</option>';
        for (const [name, info] of Object.entries(presets)) {
            const opt = document.createElement("option");
            opt.value = name;
            opt.textContent = `${name}  (${info.width_mm}x${info.height_mm}mm)`;
            selSheet.appendChild(opt);
        }
        const customOpt = document.createElement("option");
        customOpt.value = "custom";
        customOpt.textContent = "Custom...";
        selSheet.appendChild(customOpt);
    } catch (e) {
        console.error("Failed to load presets:", e);
    }
}

// ---------- Upload ----------
async function handleFile(file) {
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
        showStatus("Please select a PDF file", "error");
        return;
    }

    const form = new FormData();
    form.append("file", file);

    showStatus("Uploading...", "loading");

    try {
        const res = await fetch(`${API}/upload`, { method: "POST", body: form });
        const data = await res.json();
        if (!res.ok) {
            showStatus(data.error || "Upload failed", "error");
            return;
        }

        state.jobId = data.job_id;
        state.filename = data.filename;
        state.pdfInfo = data.info;

        // UI updates
        fileName.textContent = data.filename;
        filePages.textContent = `${data.info.page_count} page(s)`;
        dropZone.classList.add("hidden");
        fileInfo.classList.remove("hidden");
        updateProcessButton();
        showInfo(data.info);
        showPageSpecEditor();
        showStatus("Uploaded", "success");

        // Load preview
        await loadPdf(`${API}/jobs/${state.jobId}/input.pdf`);
        previewSource.value = "input";
        previewSource.querySelector('[value="result"]').disabled = true;

    } catch (e) {
        showStatus(`Upload error: ${e.message}`, "error");
    }
}

function clearFile() {
    state.jobId = null;
    state.filename = null;
    state.pdfInfo = null;
    state.resultInfo = null;
    state.pdfDoc = null;
    state.totalPages = 0;

    fileInfo.classList.add("hidden");
    dropZone.classList.remove("hidden");
    btnDownload.classList.add("hidden");
    previewControls.classList.add("hidden");
    previewPlaceholder.classList.remove("hidden");
    canvas.style.display = "none";
    infoSection.classList.add("hidden");
    statusEl.classList.add("hidden");
    fileInput.value = "";
    updateProcessButton();
    showPageSpecEditor();
}

// ---------- Process ----------
async function processFile() {
    if (!state.jobId || state.processing) return;

    state.processing = true;
    btnProcess.disabled = true;
    showStatus("Processing pipeline...", "loading");

    const body = {
        job_id: state.jobId,
        remove_marks: $("#chk-remove-marks").checked,
        crop_to_bleed: $("#chk-crop-bleed").checked,
        convert_to_cmyk: chkConvertCmyk.checked,
        cmyk_intent: parseInt($("#sel-cmyk-intent").value),
        sheet: getSheetSpec(),
        orientation: $("#sel-orientation").value || null,
        margin: parseFloat($("#inp-margin").value) || 0.375,
        outline: $("#chk-outline").checked,
        marks: $("#chk-marks").checked,
    };

    try {
        const res = await fetch(`${API}/process`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json();

        if (!res.ok) {
            const steps = data.steps_completed?.join(", ") || "none";
            showStatus(`Error: ${data.error} (completed: ${steps})`, "error");
            return;
        }

        state.resultInfo = data.result_info;

        // Enable result preview & download
        previewSource.querySelector('[value="result"]').disabled = false;
        previewSource.value = "result";
        state.previewSource = "result";
        await loadPdf(`${API}/jobs/${state.jobId}/result.pdf`);

        btnDownload.href = `${API}/jobs/${state.jobId}/result.pdf`;
        btnDownload.classList.remove("hidden");

        const steps = data.steps_completed.join(" -> ");
        showStatus(`Done: ${steps}`, "success");

    } catch (e) {
        showStatus(`Process error: ${e.message}`, "error");
    } finally {
        state.processing = false;
        updateProcessButton();
    }
}

function getSheetSpec() {
    const val = selSheet.value;
    if (val === "custom") {
        const w = $("#custom-w").value;
        const h = $("#custom-h").value;
        const unit = $("#custom-unit").value;
        return `${w}x${h}${unit}`;
    }
    return val;
}

function updateProcessButton() {
    const hasFile = !!state.jobId;
    const hasSheet = selSheet.value && selSheet.value !== "";
    btnProcess.disabled = !hasFile || !hasSheet || state.processing;
}

// ---------- Info display ----------
function showInfo(info) {
    if (!info || !info.pages || info.pages.length === 0) {
        infoSection.classList.add("hidden");
        return;
    }

    let html = "";
    for (const pg of info.pages) {
        html += `<strong>Page ${pg.page}</strong>`;
        html += '<table><tr><th>Box</th><th>Size (in)</th><th>Size (mm)</th></tr>';
        for (const [boxName, box] of Object.entries(pg.boxes)) {
            const s = box.size;
            html += `<tr>
                <td>${boxName}</td>
                <td>${s.width_in} x ${s.height_in}</td>
                <td>${s.width_mm} x ${s.height_mm}</td>
            </tr>`;
        }

        // Color info merged across columns in the same table
        if (pg.color) {
            const c = pg.color;
            html += `<tr><td colspan="3" style="padding-top:8px"><strong>Colors:</strong> ${c.color_spaces.join(", ") || "none"}</td></tr>`;
            if (c.images.count > 0) {
                html += `<tr><td colspan="3"><strong>Images:</strong> ${c.images.count} (${c.images.color_spaces.join(", ")})</td></tr>`;
            }
            if (c.spot_colors.length > 0) {
                html += `<tr><td colspan="3"><strong>Spot:</strong> ${c.spot_colors.join(", ")}</td></tr>`;
            }
        }
        html += "</table><div style='margin-bottom:12px'></div>";
    }

    if (info.color_summary) {
        const cs = info.color_summary;
        html += `<hr style="border-color:var(--border);margin:10px 0">`;
        html += `<p><strong>Summary:</strong> `;
        html += cs.has_rgb ? '<span style="color:#e85555">RGB</span> ' : "";
        html += cs.has_cmyk ? '<span style="color:#4caf80">CMYK</span> ' : "";
        html += cs.has_gray ? "Gray " : "";
        html += cs.has_spot ? `Spot(${cs.spot_colors.join(",")})` : "";
        html += `</p>`;
    }

    infoContent.innerHTML = html;
    infoSection.classList.remove("hidden");
}

// ---------- Status ----------
function showStatus(msg, type) {
    statusEl.classList.remove("hidden");
    statusText.textContent = msg;
    statusText.className = "";
    statusSpinner.classList.add("hidden");

    if (type === "error") statusText.classList.add("error");
    else if (type === "success") statusText.classList.add("success");
    else if (type === "loading") statusSpinner.classList.remove("hidden");
}

// ---------- Resize Handle ----------
function setupResize() {
    const handle = $("#resize-handle");
    const controlsPanel = $("#controls-panel");
    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener("mousedown", (e) => {
        dragging = true;
        startX = e.clientX;
        startWidth = controlsPanel.offsetWidth;
        handle.classList.add("dragging");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        // Controls is on the right, so dragging left = wider controls
        const delta = startX - e.clientX;
        const newWidth = Math.min(800, Math.max(360, startWidth + delta));
        controlsPanel.style.width = newWidth + "px";
    });

    document.addEventListener("mouseup", () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove("dragging");
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        // Re-render PDF to fit new preview size
        if (state.pdfDoc) renderPage(state.currentPage);
    });
}

// ---------- Event Listeners ----------
function setupEvents() {
    // File input
    fileInput.addEventListener("change", (e) => {
        if (e.target.files[0]) handleFile(e.target.files[0]);
    });

    // Drop zone — only trigger file dialog if click is NOT on the label/input
    // (the label already opens the dialog via its nested input)
    dropZone.addEventListener("click", (e) => {
        if (!e.target.closest(".file-btn") && e.target !== fileInput) {
            fileInput.click();
        }
    });
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });

    // Clear file
    btnClear.addEventListener("click", clearFile);

    // Process
    btnProcess.addEventListener("click", processFile);

    // Sheet select
    selSheet.addEventListener("change", () => {
        customSize.classList.toggle("hidden", selSheet.value !== "custom");
        updateProcessButton();
    });

    // CMYK toggle
    chkConvertCmyk.addEventListener("change", () => {
        cmykOptions.classList.toggle("hidden", !chkConvertCmyk.checked);
    });

    // Page navigation
    btnPrev.addEventListener("click", () => {
        if (state.currentPage > 1) renderPage(state.currentPage - 1);
    });
    btnNext.addEventListener("click", () => {
        if (state.currentPage < state.totalPages) renderPage(state.currentPage + 1);
    });

    // Preview source toggle
    previewSource.addEventListener("change", async () => {
        const src = previewSource.value;
        state.previewSource = src;
        if (src === "input") {
            await loadPdf(`${API}/jobs/${state.jobId}/input.pdf`);
        } else {
            await loadPdf(`${API}/jobs/${state.jobId}/result.pdf`);
        }
    });

    // Zoom buttons
    btnZoomIn.addEventListener("click", zoomIn);
    btnZoomOut.addEventListener("click", zoomOut);
    btnZoomFit.addEventListener("click", zoomFit);

    // Scroll wheel zoom (Ctrl/Cmd + scroll)
    const previewArea = $("#preview-area");
    previewArea.addEventListener("wheel", (e) => {
        if (!state.pdfDoc) return;
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            if (e.deltaY < 0) zoomIn();
            else zoomOut();
        }
    }, { passive: false });

    // Pan by dragging (grab hand)
    let panning = false;
    let panStartX = 0;
    let panStartY = 0;
    let scrollStartX = 0;
    let scrollStartY = 0;

    previewArea.addEventListener("mousedown", (e) => {
        // Only pan when content overflows (zoomed in)
        if (previewArea.scrollWidth <= previewArea.clientWidth &&
            previewArea.scrollHeight <= previewArea.clientHeight) return;
        panning = true;
        panStartX = e.clientX;
        panStartY = e.clientY;
        scrollStartX = previewArea.scrollLeft;
        scrollStartY = previewArea.scrollTop;
        previewArea.classList.add("grabbing");
        e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
        if (!panning) return;
        previewArea.scrollLeft = scrollStartX - (e.clientX - panStartX);
        previewArea.scrollTop = scrollStartY - (e.clientY - panStartY);
    });

    document.addEventListener("mouseup", () => {
        if (!panning) return;
        panning = false;
        previewArea.classList.remove("grabbing");
    });
}

// ---------- Tabs ----------
function setupTabs() {
    const tabs = document.querySelectorAll("#tab-bar .tab");
    tabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            tabs.forEach((t) => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
            tab.classList.add("active");
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add("active");
            // Re-render to show/hide box overlays
            if (state.pdfDoc) renderPage(state.currentPage);
        });
    });
}

// ---------- Page Spec Editor ----------
const PT_PER_IN = 72;
const PT_PER_MM = 72 / 25.4;

function specUnitFactor() {
    const u = $("#spec-unit").value;
    if (u === "mm") return PT_PER_MM;
    if (u === "in") return PT_PER_IN;
    return 1; // pt
}

function updateSpecSteps() {
    const u = $("#spec-unit").value;
    let step;
    if (u === "in") step = "0.0625";       // 1/16 inch
    else if (u === "mm") step = "0.5";     // 0.5mm
    else step = "1";                        // 1pt
    document.querySelectorAll(".box-size-row input, .box-pos-row input, .box-fields input").forEach((inp) => {
        inp.step = step;
    });
}

function specFromPt(val) {
    return +(val / specUnitFactor()).toFixed(4);
}

function specToPt(val) {
    return val * specUnitFactor();
}

function populateSpecPageSelect() {
    const sel = $("#spec-page-select");
    sel.innerHTML = "";
    if (!state.pdfInfo) return;
    for (let i = 1; i <= state.pdfInfo.page_count; i++) {
        const opt = document.createElement("option");
        opt.value = i;
        opt.textContent = `Page ${i}`;
        sel.appendChild(opt);
    }
}

function loadSpecBoxes() {
    if (!state.pdfInfo) return;
    const pageNum = parseInt($("#spec-page-select").value);
    const pageData = state.pdfInfo.pages.find((p) => p.page === pageNum);
    if (!pageData) return;

    const boxes = {
        media: "mediabox",
        crop: "cropbox",
        bleed: "bleedbox",
        trim: "trimbox",
    };

    for (const [prefix, boxName] of Object.entries(boxes)) {
        const box = pageData.boxes[boxName];
        const xEl = $(`#spec-${prefix}-x`);
        const yEl = $(`#spec-${prefix}-y`);
        const wEl = $(`#spec-${prefix}-w`);
        const hEl = $(`#spec-${prefix}-h`);

        if (box) {
            xEl.value = specFromPt(box.origin.x_pt);
            yEl.value = specFromPt(box.origin.y_pt);
            wEl.value = specFromPt(box.size.width_pt);
            hEl.value = specFromPt(box.size.height_pt);
        } else {
            xEl.value = "";
            yEl.value = "";
            wEl.value = "";
            hEl.value = "";
        }
    }
}

async function applySpecChanges() {
    if (!state.jobId || !state.pdfInfo) return;

    const applyAll = $("#spec-apply-all").checked;
    const pageNums = applyAll
        ? Array.from({ length: state.pdfInfo.page_count }, (_, i) => i + 1)
        : [parseInt($("#spec-page-select").value)];

    const boxes = {
        media: "mediabox",
        crop: "cropbox",
        bleed: "bleedbox",
        trim: "trimbox",
    };

    const pages = [];
    for (const pgNum of pageNums) {
        const entry = { page: pgNum };
        for (const [prefix, boxName] of Object.entries(boxes)) {
            const x = parseFloat($(`#spec-${prefix}-x`).value);
            const y = parseFloat($(`#spec-${prefix}-y`).value);
            const w = parseFloat($(`#spec-${prefix}-w`).value);
            const h = parseFloat($(`#spec-${prefix}-h`).value);
            if (!isNaN(x) && !isNaN(y) && !isNaN(w) && !isNaN(h)) {
                entry[boxName] = [specToPt(x), specToPt(y), specToPt(w), specToPt(h)];
            }
        }
        pages.push(entry);
    }

    const specStatus = $("#spec-status");
    const specText = $("#spec-status-text");
    specStatus.classList.remove("hidden");
    specText.className = "";
    specText.textContent = "Applying...";

    try {
        const res = await fetch(`${API}/jobs/${state.jobId}/set-boxes`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pages }),
        });
        const data = await res.json();
        if (!res.ok) {
            specText.textContent = data.error || "Failed";
            specText.classList.add("error");
            return;
        }

        // Update stored info and reload preview
        state.pdfInfo = data.info;
        loadSpecBoxes();
        await loadPdf(`${API}/jobs/${state.jobId}/input.pdf`);
        showInfo(state.pdfInfo);

        const label = applyAll ? "all pages" : `page ${pageNums[0]}`;
        specText.textContent = `Applied to ${label}`;
        specText.classList.add("success");
    } catch (e) {
        specText.textContent = `Error: ${e.message}`;
        specText.classList.add("error");
    }
}

function copyBoxValues(targetPrefix, sourcePrefix) {
    const fields = ["x", "y", "w", "h"];
    for (const f of fields) {
        const src = $(`#spec-${sourcePrefix}-${f}`);
        const dst = $(`#spec-${targetPrefix}-${f}`);
        if (src && dst) dst.value = src.value;
    }
    redrawOverlaysOnly();
}

function centerBox(prefix) {
    // Center this box within the MediaBox
    const mediaW = parseFloat($("#spec-media-w").value);
    const mediaH = parseFloat($("#spec-media-h").value);
    const mediaX = parseFloat($("#spec-media-x").value);
    const mediaY = parseFloat($("#spec-media-y").value);
    const boxW = parseFloat($(`#spec-${prefix}-w`).value);
    const boxH = parseFloat($(`#spec-${prefix}-h`).value);
    if (isNaN(mediaW) || isNaN(mediaH) || isNaN(boxW) || isNaN(boxH)) return;

    const newX = (isNaN(mediaX) ? 0 : mediaX) + (mediaW - boxW) / 2;
    const newY = (isNaN(mediaY) ? 0 : mediaY) + (mediaH - boxH) / 2;
    $(`#spec-${prefix}-x`).value = +newX.toFixed(4);
    $(`#spec-${prefix}-y`).value = +newY.toFixed(4);
    redrawOverlaysOnly();
}

function setupPageSpec() {
    $("#spec-page-select").addEventListener("change", () => {
        loadSpecBoxes();
        if (state.pdfDoc) renderPage(state.currentPage);
    });
    $("#spec-unit").addEventListener("change", () => {
        updateSpecSteps();
        loadSpecBoxes();
        redrawOverlaysOnly();
    });
    $("#btn-spec-apply").addEventListener("click", applySpecChanges);
    $("#btn-spec-reset").addEventListener("click", () => {
        loadSpecBoxes();
        redrawOverlaysOnly();
    });

    // Live re-draw overlays on any spec input change (no full PDF re-render)
    const specInputs = document.querySelectorAll(".box-size-row input, .box-pos-row input");
    specInputs.forEach((inp) => {
        inp.addEventListener("input", () => {
            redrawOverlaysOnly();
        });
    });

    // Copy-from dropdowns
    document.querySelectorAll(".copy-from").forEach((sel) => {
        sel.addEventListener("change", () => {
            const target = sel.dataset.box;
            const source = sel.value;
            if (source) {
                copyBoxValues(target, source);
                sel.value = ""; // reset dropdown
            }
        });
    });

    // Center buttons
    document.querySelectorAll(".btn-center").forEach((btn) => {
        btn.addEventListener("click", () => {
            centerBox(btn.dataset.box);
        });
    });

    // Drag to reposition content within boxes
    setupSpecDrag();
}

function setupSpecDrag() {
    const previewArea = $("#preview-area");
    let specDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let startBoxPositions = {}; // { prefix: { x, y } }

    previewArea.addEventListener("mousedown", (e) => {
        // Only drag-reposition when Page Spec tab is active
        const isSpecTab = document.querySelector('#tab-bar .tab[data-tab="tab-page-spec"]').classList.contains("active");
        if (!isSpecTab || !state.pdfDoc) return;

        // Don't interfere with normal pan when zoomed
        if (previewArea.scrollWidth > previewArea.clientWidth ||
            previewArea.scrollHeight > previewArea.clientHeight) return;

        specDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;

        // Save starting positions of all boxes
        const prefixes = ["media", "crop", "bleed", "trim"];
        startBoxPositions = {};
        for (const p of prefixes) {
            const x = parseFloat($(`#spec-${p}-x`).value);
            const y = parseFloat($(`#spec-${p}-y`).value);
            if (!isNaN(x) && !isNaN(y)) {
                startBoxPositions[p] = { x, y };
            }
        }

        previewArea.classList.add("grabbing");
        e.preventDefault();
    });

    document.addEventListener("mousemove", (e) => {
        if (!specDragging) return;

        // Convert pixel delta to unit delta
        const scale = state.zoomScale;
        const factor = specUnitFactor();
        // Canvas pixels per display unit
        const pxPerUnit = scale * factor;

        const dx = (e.clientX - dragStartX) / pxPerUnit;
        const dy = -(e.clientY - dragStartY) / pxPerUnit; // flip Y: canvas down = PDF up

        for (const [prefix, start] of Object.entries(startBoxPositions)) {
            $(`#spec-${prefix}-x`).value = +(start.x + dx).toFixed(4);
            $(`#spec-${prefix}-y`).value = +(start.y + dy).toFixed(4);
        }

        redrawOverlaysOnly();
    });

    document.addEventListener("mouseup", () => {
        if (!specDragging) return;
        specDragging = false;
        previewArea.classList.remove("grabbing");
    });
}

function showPageSpecEditor() {
    if (state.pdfInfo) {
        $("#page-spec-empty").classList.add("hidden");
        $("#page-spec-editor").classList.remove("hidden");
        populateSpecPageSelect();
        loadSpecBoxes();
    } else {
        $("#page-spec-empty").classList.remove("hidden");
        $("#page-spec-editor").classList.add("hidden");
    }
}

// ---------- Init ----------
async function init() {
    await initPdfJs();
    await loadPresets();
    setupEvents();
    setupResize();
    setupTabs();
    setupPageSpec();
}

init();
