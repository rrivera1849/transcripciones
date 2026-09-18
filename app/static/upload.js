// Chunked upload: 5 MB parts, sequential, retried; survives a flaky Wi-Fi drop.
(function () {
  const cfg = window.UPLOAD;
  const $ = (id) => document.getElementById(id);
  const drop = $("drop"), fileInput = $("file"), chosen = $("chosen"), start = $("start");
  const progress = $("progress"), bar = $("bar"), ptext = $("ptext"), errBox = $("upload-error");
  let file = null;

  function setFile(f) {
    file = f;
    chosen.hidden = !f;
    chosen.textContent = f ? `${f.name} (${(f.size / 1048576).toFixed(1)} MB)` : "";
    start.disabled = !f;
    errBox.hidden = true;
    if (f && !$("title").value) $("title").value = f.name.replace(/\.[^.]+$/, "");
  }
  $("pick").addEventListener("click", () => fileInput.click());
  drop.addEventListener("click", (e) => { if (e.target === drop || e.target.classList.contains("drop-text")) fileInput.click(); });
  fileInput.addEventListener("change", () => setFile(fileInput.files[0] || null));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });

  function fail(msg) { errBox.textContent = msg; errBox.hidden = false; start.disabled = false; progress.hidden = true; }

  async function api(method, url, body, isJson = true) {
    const headers = { "X-CSRF-Token": cfg.csrf };
    if (isJson) headers["Content-Type"] = "application/json";
    const r = await fetch(url, { method, headers, body: isJson ? JSON.stringify(body) : body });
    if (!r.ok) {
      let detail = `Error ${r.status}`;
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return r.json();
  }

  async function putChunk(jobId, index, blob) {
    for (let attempt = 1; attempt <= 4; attempt++) {
      try { return await api("PUT", `/upload/${jobId}/chunk/${index}`, blob, false); }
      catch (e) { if (attempt === 4) throw e; await new Promise((r) => setTimeout(r, 1500 * attempt)); }
    }
  }

  start.addEventListener("click", async () => {
    if (!file) return;
    if (file.size > cfg.maxBytes) return fail("El archivo es demasiado grande.");
    start.disabled = true; progress.hidden = false; bar.style.width = "0%"; ptext.textContent = "Preparando…";
    try {
      const { job_id } = await api("POST", "/upload/init", {
        filename: file.name, size: file.size, title: $("title").value,
        min_speakers: $("speakers").value, vocabulary: $("vocabulary").value,
      });
      const total = Math.ceil(file.size / cfg.chunk);
      for (let i = 0; i < total; i++) {
        await putChunk(job_id, i, file.slice(i * cfg.chunk, (i + 1) * cfg.chunk));
        const pct = Math.round(((i + 1) / total) * 100);
        bar.style.width = pct + "%"; ptext.textContent = `Subiendo ${pct} %`;
      }
      await api("POST", `/upload/${job_id}/complete`, {});
      ptext.textContent = "Subido. Transcribiendo…";
      setTimeout(() => location.reload(), 800);
    } catch (e) { fail(e.message || "No se pudo subir el archivo."); }
  });
})();
