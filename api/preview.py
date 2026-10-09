"""Self-contained interactive HTML preview for the API.

Served at ``GET /`` -- lets a reviewer upload a .zip or .kml file, see
the file info + measurements as JSON, and visualise every feature's
geometry on a Leaflet map.

The page is deliberately vanilla (no React, no build step): one HTML
string, served via ``HTMLResponse``.  Leaflet + Prism (syntax
highlighting) come from public CDNs.
"""

from __future__ import annotations

PREVIEW_HTML: str = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Geospatial File Measurement API -- Preview</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />
  <style>
    :root {
      --bg: #0f1419;
      --panel: #161b22;
      --panel-2: #1c2230;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #2f81f7;
      --accent-2: #3fb950;
      --warn: #d29922;
      --err: #f85149;
      --border: #30363d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.55;
    }
    header {
      padding: 18px 24px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    }
    header h1 { margin: 0; font-size: 18px; font-weight: 600; }
    header .sub { color: var(--muted); font-size: 13px; }
    header a { color: var(--accent); text-decoration: none; font-size: 13px; }
    header a:hover { text-decoration: underline; }
    .health-pill {
      padding: 2px 8px; border-radius: 12px; background: rgba(63,185,80,.15);
      color: var(--accent-2); font-size: 12px; border: 1px solid rgba(63,185,80,.3);
    }
    main { padding: 24px; max-width: 1400px; margin: 0 auto; }
    .grid { display: grid; grid-template-columns: 420px 1fr; gap: 20px; }
    @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
    .panel {
      background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 14px 0; font-size: 14px; font-weight: 600; color: var(--muted);
      text-transform: uppercase; letter-spacing: .04em;
    }
    .dropzone {
      border: 2px dashed var(--border); border-radius: 8px; padding: 28px 18px;
      text-align: center; cursor: pointer; transition: all .2s;
    }
    .dropzone:hover, .dropzone.dragover {
      border-color: var(--accent); background: rgba(47,129,247,.06);
    }
    .dropzone .big { font-size: 13px; color: var(--text); margin-bottom: 4px; }
    .dropzone .small { font-size: 12px; color: var(--muted); }
    .dropzone input { display: none; }
    button, .btn {
      background: var(--accent); color: white; border: 0; border-radius: 6px;
      padding: 8px 16px; font-size: 13px; font-weight: 500; cursor: pointer;
      transition: background .15s;
    }
    button:hover, .btn:hover { background: #1f6feb; }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .file-list { margin-top: 16px; }
    .file-row {
      padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px;
      margin-bottom: 8px; cursor: pointer; transition: all .15s;
    }
    .file-row:hover { border-color: var(--accent); background: var(--panel-2); }
    .file-row.active { border-color: var(--accent); background: var(--panel-2); }
    .file-row .name { font-weight: 500; font-size: 13px; word-break: break-all; }
    .file-row .meta {
      color: var(--muted); font-size: 11px; margin-top: 3px;
      display: flex; gap: 12px; flex-wrap: wrap;
    }
    .file-row .meta .stat { display: inline-flex; gap: 4px; }
    .file-row .meta .stat .k { color: var(--muted); }
    .file-row .meta .stat .v { color: var(--text); }
    .right-panel { display: flex; flex-direction: column; gap: 20px; }
    .info-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px;
    }
    .info-item .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
    .info-item .v { color: var(--text); font-size: 13px; margin-top: 2px; word-break: break-all; }
    .info-item .v.mono { font-family: "SF Mono", Consolas, monospace; font-size: 12px; }
    .info-item .v.warn { color: var(--warn); }
    .info-item .v.err  { color: var(--err); }
    .info-item .v.ok   { color: var(--accent-2); }
    .badge {
      display: inline-block; padding: 1px 6px; border-radius: 8px;
      font-size: 11px; font-weight: 500;
    }
    .badge.completed   { background: rgba(63,185,80,.18);  color: var(--accent-2); }
    .badge.not_required{ background: rgba(139,148,158,.18); color: var(--muted); }
    .badge.unavailable { background: rgba(248,81,73,.18);   color: var(--err); }
    .badge.skipped     { background: rgba(210,153,34,.18);  color: var(--warn); }
    #map {
      width: 100%; height: 380px; border-radius: 8px;
      border: 1px solid var(--border); background: var(--panel-2);
    }
    .feature-list { margin-top: 12px; max-height: 220px; overflow-y: auto; }
    .feature-row {
      padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px;
      margin-bottom: 6px; cursor: pointer; font-size: 12px;
    }
    .feature-row:hover { background: var(--panel-2); }
    .feature-row.active { background: var(--panel-2); border-color: var(--accent); }
    .feature-row .ftype { font-weight: 500; }
    .feature-row .fmeas { color: var(--muted); margin-top: 2px; }
    pre[class*="language-"] {
      margin: 0; border-radius: 6px; max-height: 380px; overflow: auto;
      font-size: 12px;
    }
    .toast {
      position: fixed; bottom: 20px; right: 20px; padding: 10px 16px;
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 6px; font-size: 13px; z-index: 1000;
      box-shadow: 0 4px 12px rgba(0,0,0,.4); transition: opacity .25s;
    }
    .toast.err { border-color: var(--err); color: var(--err); }
    .toast.ok  { border-color: var(--accent-2); color: var(--accent-2); }
    .empty { color: var(--muted); font-size: 13px; padding: 12px 0; }
    details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
    .spinner {
      display: inline-block; width: 14px; height: 14px; border-radius: 50%;
      border: 2px solid var(--border); border-top-color: var(--accent);
      animation: spin .8s linear infinite; vertical-align: middle;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <header>
    <h1>Geospatial File Measurement API</h1>
    <span class="sub">Upload a Shapefile (.zip) or KML, see features + measurements + map</span>
    <span style="flex:1"></span>
    <span id="health" class="health-pill">checking…</span>
    <a href="/docs" target="_blank">Swagger UI ↗</a>
    <a href="/redoc" target="_blank">ReDoc ↗</a>
  </header>

  <main>
    <div class="grid">
      <!-- LEFT: upload + file list -->
      <div class="panel">
        <h2>Upload</h2>
        <form id="upload-form">
          <label class="dropzone" id="dropzone" for="file-input">
            <div class="big" id="dz-big">Drop a .zip or .kml here</div>
            <div class="small" id="dz-small">or click to choose</div>
            <input type="file" id="file-input" accept=".zip,.kml" />
          </label>
          <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
            <button type="submit" id="upload-btn" disabled>Upload &amp; process</button>
            <span id="upload-status" style="font-size:12px; color:var(--muted)"></span>
          </div>
        </form>

        <h2 style="margin-top:24px">Uploaded files</h2>
        <div id="file-list" class="file-list">
          <div class="empty">No files uploaded yet.</div>
        </div>
      </div>

      <!-- RIGHT: details + map + json -->
      <div class="right-panel">
        <div class="panel" id="detail-panel">
          <h2>File details</h2>
          <div id="detail-body" class="empty">Select a file on the left.</div>
        </div>

        <div class="panel" id="map-panel" style="display:none">
          <h2>Feature geometries (source CRS)</h2>
          <div id="map"></div>
          <div id="feature-list" class="feature-list"></div>
        </div>

        <div class="panel" id="json-panel" style="display:none">
          <h2>Measurements JSON</h2>
          <pre><code id="json-out" class="language-json"></code></pre>
        </div>
      </div>
    </div>
  </main>

  <div id="toast" class="toast" style="display:none"></div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js"></script>
  <script>
  (function () {
    "use strict";
    const $ = (id) => document.getElementById(id);
    const toast = (msg, kind) => {
      const t = $("toast");
      t.textContent = msg;
      t.className = "toast " + (kind || "");
      t.style.display = "block";
      clearTimeout(toast._t);
      toast._t = setTimeout(() => (t.style.display = "none"), 3500);
    };

    let map = null;
    let mapLayer = null;
    let activeFileId = null;

    // ---------------------- health ----------------------
    async function checkHealth() {
      try {
        const r = await fetch("/health");
        const j = await r.json();
        const el = $("health");
        if (j.status === "ok") {
          el.textContent = "● online · db " + j.database;
        } else {
          el.textContent = "● " + (j.status || "degraded");
          el.style.background = "rgba(248,81,73,.15)";
          el.style.color = "#f85149";
          el.style.borderColor = "rgba(248,81,73,.3)";
        }
      } catch (e) {
        const el = $("health");
        el.textContent = "● offline";
        el.style.background = "rgba(248,81,73,.15)";
        el.style.color = "#f85149";
        el.style.borderColor = "rgba(248,81,73,.3)";
      }
    }
    checkHealth();

    // ---------------------- file picker ----------------------
    const fileInput = $("file-input");
    const uploadBtn = $("upload-btn");
    const dz = $("dropzone");

    function setFileName(name) {
      $("dz-big").textContent = name ? "Selected: " + name : "Drop a .zip or .kml here";
      $("dz-small").textContent = name ? "click to change" : "or click to choose";
      uploadBtn.disabled = !name;
    }
    fileInput.addEventListener("change", () => setFileName(fileInput.files[0]?.name || ""));
    ["dragover"].forEach(ev => dz.addEventListener(ev, e => {
      e.preventDefault(); dz.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => {
      e.preventDefault(); dz.classList.remove("dragover");
    }));
    dz.addEventListener("drop", e => {
      const f = e.dataTransfer.files?.[0];
      if (f) {
        fileInput.files = e.dataTransfer.files;
        setFileName(f.name);
      }
    });

    // ---------------------- upload ----------------------
    $("upload-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const file = fileInput.files?.[0];
      if (!file) return;
      uploadBtn.disabled = true;
      $("upload-status").innerHTML = '<span class="spinner"></span> uploading…';
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        const r = await fetch("/api/files/", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok) {
          toast("Upload failed: " + (j.detail || r.statusText), "err");
          $("upload-status").textContent = "failed";
          return;
        }
        toast("Uploaded — " + j.feature_count + " feature(s)", "ok");
        $("upload-status").textContent = "done";
        await refreshFileList();
        selectFile(j.id);
      } catch (err) {
        toast("Network error: " + err.message, "err");
        $("upload-status").textContent = "error";
      } finally {
        uploadBtn.disabled = false;
        setTimeout(() => ($("upload-status").textContent = ""), 2500);
      }
    });

    // ---------------------- file list ----------------------
    async function refreshFileList() {
      // We don't have a list endpoint, but we can keep an in-memory list of
      // ids we've seen this session and refresh their /info individually.
      // For an empty state, just re-fetch the last known id if any.
      const list = $("file-list");
      const ids = JSON.parse(sessionStorage.getItem("file_ids") || "[]");
      if (ids.length === 0) {
        list.innerHTML = '<div class="empty">No files uploaded yet.</div>';
        return;
      }
      const items = await Promise.all(
        ids.map(id => fetch("/api/files/" + id + "/").then(r => r.ok ? r.json() : null).catch(() => null))
      );
      list.innerHTML = "";
      items.filter(Boolean).reverse().forEach(f => {
        const row = document.createElement("div");
        row.className = "file-row" + (f.id === activeFileId ? " active" : "");
        row.dataset.id = f.id;
        row.innerHTML = `
          <div class="name">${escapeHtml(f.filename)}</div>
          <div class="meta">
            <span class="stat"><span class="k">features:</span><span class="v">${f.feature_count}</span></span>
            <span class="stat"><span class="k">src:</span><span class="v">${f.source_crs || "—"}</span></span>
            <span class="stat"><span class="k">meas:</span><span class="v">${f.measurement_crs || "—"}</span></span>
            <span class="stat"><span class="k">status:</span><span class="v">${f.status}</span></span>
          </div>
        `;
        row.onclick = () => selectFile(f.id);
        list.appendChild(row);
      });
    }

    function rememberId(id) {
      const ids = JSON.parse(sessionStorage.getItem("file_ids") || "[]");
      if (!ids.includes(id)) {
        ids.push(id);
        sessionStorage.setItem("file_ids", JSON.stringify(ids));
      }
    }

    // ---------------------- select + render ----------------------
    async function selectFile(id) {
      activeFileId = id;
      rememberId(id);
      // re-render the list to mark active
      Array.from($("file-list").children).forEach(c => {
        c.classList.toggle("active", c.dataset.id === id);
      });
      const info = await fetch("/api/files/" + id + "/").then(r => r.json()).catch(() => null);
      if (!info) { toast("File info fetch failed", "err"); return; }
      renderFileDetails(info);
      const meas = await fetch("/api/files/" + id + "/measurements/").then(r => r.json()).catch(() => null);
      if (!meas) { toast("Measurements fetch failed", "err"); return; }
      renderMeasurements(info, meas);
      // refresh list to show new file
      await refreshFileList();
    }
    window.selectFile = selectFile; // expose for tests

    function renderFileDetails(info) {
      const body = $("detail-body");
      body.className = "";
      const warnCount = (info.warnings || []).length;
      body.innerHTML = `
        <div class="info-grid">
          <div class="info-item"><div class="k">id</div><div class="v mono">${info.id}</div></div>
          <div class="info-item"><div class="k">filename</div><div class="v">${escapeHtml(info.filename)}</div></div>
          <div class="info-item"><div class="k">feature count</div><div class="v">${info.feature_count}</div></div>
          <div class="info-item"><div class="k">status</div><div class="v ok">${info.status}</div></div>
          <div class="info-item"><div class="k">source CRS</div><div class="v mono">${info.source_crs || "—"}</div></div>
          <div class="info-item"><div class="k">measurement CRS</div><div class="v mono">${info.measurement_crs || "—"}</div></div>
          <div class="info-item"><div class="k">warnings</div><div class="v ${warnCount ? "warn" : "ok"}">${warnCount}</div></div>
          <div class="info-item"><div class="k">created</div><div class="v mono">${info.created_at || "—"}</div></div>
        </div>
        ${warnCount ? `<details style="margin-top:12px"><summary>Show ${warnCount} warning(s)</summary><ul style="margin:8px 0 0 16px;padding:0;font-size:12px;color:var(--warn)">${info.warnings.map(w => "<li>" + escapeHtml(w) + "</li>").join("")}</ul></details>` : ""}
      `;
    }

    function renderMeasurements(info, meas) {
      // JSON panel
      $("json-panel").style.display = "block";
      const pretty = JSON.stringify(meas, null, 2);
      $("json-out").textContent = pretty;
      if (window.Prism) Prism.highlightElement($("json-out"));

      // Map panel
      const features = meas.features || [];
      if (features.length === 0) {
        $("map-panel").style.display = "none";
        return;
      }
      $("map-panel").style.display = "block";
      $("feature-list").innerHTML = "";
      if (map) { map.remove(); map = null; }
      map = L.map("map", { scrollWheelZoom: true }).setView([0, 0], 2);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(map);
      const layerGroup = L.layerGroup().addTo(map);
      const bounds = [];

      features.forEach((f, idx) => {
        const color = pickColor(idx);
        let lyr = null;
        if (f.geometry) {
          try {
            lyr = L.geoJSON(f.geometry, {
              style: { color, weight: 2, fillColor: color, fillOpacity: 0.25 },
              pointToLayer: (feat, latlng) => L.circleMarker(latlng, {
                radius: 6, color, fillColor: color, fillOpacity: 0.7,
              }),
            });
            lyr.addTo(layerGroup);
            try {
              const b = lyr.getBounds();
              if (b && b.isValid()) bounds.push(b);
            } catch (e) { /* empty geom */ }
          } catch (e) { /* ignore */ }
        }
        // Feature row
        const row = document.createElement("div");
        row.className = "feature-row";
        const measParts = [];
        for (const [k, v] of Object.entries(f.measurements || {})) {
          measParts.push(`<span class="k">${escapeHtml(k)}:</span> <span class="v">${fmtNum(v)}</span>`);
        }
        row.innerHTML = `
          <div class="ftype">#${f.feature_index} ${f.geometry_type || "?"}
            <span class="badge ${f.measurement_status.toLowerCase()}">${f.measurement_status}</span>
          </div>
          <div class="fmeas">${measParts.length ? measParts.join(" &nbsp; ") : "—"}</div>
        `;
        row.onclick = () => {
          if (lyr) {
            try {
              const b = lyr.getBounds();
              if (b.isValid()) map.fitBounds(b, { padding: [40, 40] });
            } catch (e) {}
          }
        };
        $("feature-list").appendChild(row);
      });

      if (bounds.length > 0) {
        try {
          const combined = bounds[0];
          for (let i = 1; i < bounds.length; i++) combined.extend(bounds[i]);
          map.fitBounds(combined, { padding: [30, 30] });
        } catch (e) {}
      }
    }

    function pickColor(i) {
      const palette = ["#2f81f7", "#3fb950", "#d29922", "#a371f7", "#f85149",
                        "#39c5cf", "#ff7b72", "#7ee787"];
      return palette[i % palette.length];
    }
    function fmtNum(v) {
      if (typeof v !== "number") return escapeHtml(String(v));
      if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
      return v.toFixed(4);
    }
    function escapeHtml(s) {
      return String(s).replace(/[&<>"]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;" }[c]));
    }

    // refresh on focus (in case the user uploaded from another tab)
    window.addEventListener("focus", refreshFileList);
    refreshFileList();
  })();
  </script>
</body>
</html>
"""
