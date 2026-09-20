// Chunked upload: 5 MB parts, sequential, retried; survives a flaky Wi-Fi drop.
// Several files can be queued at once; they upload one after another.
(function () {
  const cfg = window.UPLOAD;
  const $ = (id) => document.getElementById(id);
  const drop = $("drop"), fileInput = $("file"), chosen = $("chosen"), start = $("start");
  const progress = $("progress"), bar = $("bar"), ptext = $("ptext"), errBox = $("upload-error");
  const title = $("title"), titleHint = $("title-hint");
  let files = [];

  function setFiles(list) {
    files = Array.from(list || []);
    chosen.hidden = !files.length;
    chosen.textContent = files.map((f) => `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`).join(" · ");
    start.disabled = !files.length;
    start.textContent = files.length > 1 ? `Transcribir ${files.length} archivos` : "Transcribir";
    errBox.hidden = true;
    const many = files.length > 1;
    title.disabled = many; titleHint.hidden = !many;
    if (many) title.value = "";
    else if (files.length && !title.value) title.value = files[0].name.replace(/\.[^.]+$/, "");
  }
  $("pick").addEventListener("click", () => fileInput.click());
  drop.addEventListener("click", (e) => { if (e.target === drop || e.target.classList.contains("drop-text")) fileInput.click(); });
  fileInput.addEventListener("change", () => setFiles(fileInput.files));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) setFiles(e.dataTransfer.files); });

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

  async function uploadOne(file, n, total) {
    const label = total > 1 ? `Archivo ${n} de ${total} · ` : "";
    const { job_id } = await api("POST", "/upload/init", {
      filename: file.name, size: file.size,
      title: total > 1 ? file.name.replace(/\.[^.]+$/, "") : title.value,
      min_speakers: $("speakers").value, vocabulary: $("vocabulary").value,
    });
    const parts = Math.ceil(file.size / cfg.chunk);
    for (let i = 0; i < parts; i++) {
      await putChunk(job_id, i, file.slice(i * cfg.chunk, (i + 1) * cfg.chunk));
      const pct = Math.round(((i + 1) / parts) * 100);
      bar.style.width = pct + "%"; ptext.textContent = `${label}Subiendo ${pct} %`;
    }
    await api("POST", `/upload/${job_id}/complete`, {});
  }

  start.addEventListener("click", async () => {
    if (!files.length) return;
    const big = files.find((f) => f.size > cfg.maxBytes);
    if (big) return fail(`«${big.name}» es demasiado grande.`);
    start.disabled = true; progress.hidden = false; bar.style.width = "0%"; ptext.textContent = "Preparando…";
    const errors = [];
    for (let i = 0; i < files.length; i++) {
      try { await uploadOne(files[i], i + 1, files.length); }
      catch (e) { errors.push(`${files[i].name}: ${e.message || "no se pudo subir"}`); }
    }
    if (errors.length === files.length) return fail(errors.join(" · "));
    ptext.textContent = errors.length ? `Subido con errores: ${errors.join(" · ")}` : "Subido. Transcribiendo…";
    setTimeout(() => location.reload(), errors.length ? 4000 : 800);
  });
})();
