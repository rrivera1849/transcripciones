// Player controls + keyboard shortcuts, highlight the playing turn, inline
// edit toggles, role picker / suggestions, doubtful-word toggle, in-page
// search, copy all.
(function () {
  const audio = document.getElementById("audio");
  const transcript = document.querySelector(".transcript");
  function turns() { return Array.from(document.querySelectorAll(".turn")); }
  function inText(el) { return el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable); }

  // ---- playback -----------------------------------------------------------
  const BACKSKIP_S = 1.5; // when resuming, back up a little so she hears the last words again
  let loopTurn = null;
  const playBtn = document.getElementById("playpause"), loopBtn = document.getElementById("loop");
  function play() { if (!audio) return; audio.play().catch(() => {}); }
  function toggle() {
    if (!audio) return;
    if (audio.paused) { if (audio.currentTime > BACKSKIP_S) audio.currentTime -= BACKSKIP_S; play(); }
    else audio.pause();
  }
  function seekBy(s) { if (audio) audio.currentTime = Math.max(0, audio.currentTime + s); }
  function setSpeed(v) {
    if (!audio) return;
    v = Math.min(2, Math.max(0.5, v)); audio.playbackRate = v;
    const sel = document.getElementById("speed"); if (sel) sel.value = String(v);
  }
  function playingTurn() {
    if (!audio) return null;
    const t = audio.currentTime;
    return turns().find((el) => t >= parseFloat(el.dataset.start) && t < parseFloat(el.dataset.end) + 0.5) || null;
  }
  function setLoop(el) {
    loopTurn = el;
    turns().forEach((t) => t.classList.toggle("looping", t === el));
    if (loopBtn) { loopBtn.setAttribute("aria-pressed", el ? "true" : "false"); loopBtn.textContent = el ? "Dejar de repetir" : "Repetir párrafo"; }
  }
  function toggleLoop() {
    if (loopTurn) return setLoop(null);
    const el = playingTurn(); if (!el) return;
    setLoop(el); audio.currentTime = parseFloat(el.dataset.start); play();
  }
  if (audio) {
    audio.addEventListener("timeupdate", () => {
      const t = audio.currentTime;
      turns().forEach((el) => {
        el.classList.toggle("playing", t >= parseFloat(el.dataset.start) && t < parseFloat(el.dataset.end) + 0.5);
      });
      if (loopTurn && loopTurn.isConnected && t >= parseFloat(loopTurn.dataset.end) + 0.3) audio.currentTime = parseFloat(loopTurn.dataset.start);
      if (loopTurn && !loopTurn.isConnected) setLoop(null); // turns re-rendered after an edit
    });
    const label = () => { if (playBtn) playBtn.textContent = audio.paused ? "▶ Reproducir" : "❚❚ Pausar"; };
    audio.addEventListener("play", label); audio.addEventListener("pause", label);
    const speed = document.getElementById("speed");
    if (speed) speed.addEventListener("change", () => setSpeed(parseFloat(speed.value)));
    if (playBtn) playBtn.addEventListener("click", toggle);
    const back = document.getElementById("back"), fwd = document.getElementById("fwd");
    if (back) back.addEventListener("click", () => seekBy(-5));
    if (fwd) fwd.addEventListener("click", () => seekBy(5));
    if (loopBtn) loopBtn.addEventListener("click", toggleLoop);
  }

  document.addEventListener("keydown", (e) => {
    if (!audio) return;
    // Function keys work everywhere, including inside the edit box.
    if (e.key === "F8") { e.preventDefault(); return toggle(); }
    if (e.key === "F7") { e.preventDefault(); return seekBy(-5); }
    if (e.key === "F9") { e.preventDefault(); return seekBy(5); }
    if (inText(e.target)) {
      const form = e.target.closest(".turn-edit");
      if (form && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); }
      if (form && e.key === "Escape") { e.preventDefault(); cancelEdit(form.closest(".turn")); }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    switch (e.key) {
      case " ": e.preventDefault(); toggle(); break;
      case "ArrowLeft": e.preventDefault(); seekBy(e.shiftKey ? -30 : -5); break;
      case "ArrowRight": e.preventDefault(); seekBy(e.shiftKey ? 30 : 5); break;
      case "-": e.preventDefault(); setSpeed(Math.round((audio.playbackRate - 0.25) * 100) / 100); break;
      case "+": case "=": e.preventDefault(); setSpeed(Math.round((audio.playbackRate + 0.25) * 100) / 100); break;
      case "r": case "R": e.preventDefault(); toggleLoop(); break;
    }
  });

  // ---- clicks: seek, edit, cancel, use suggested role ------------------------
  function cancelEdit(t) { t.querySelector(".turn-edit").hidden = true; t.querySelector(".turn-text").hidden = false; }
  document.addEventListener("click", (e) => {
    const seek = e.target.closest("[data-seek]");
    if (seek && audio) { audio.currentTime = parseFloat(seek.dataset.seek); play(); return; }
    const edit = e.target.closest(".edit-btn");
    if (edit) {
      const t = edit.closest(".turn"); t.querySelector(".turn-edit").hidden = false; t.querySelector(".turn-text").hidden = true;
      const ta = t.querySelector("textarea"); ta.focus(); ta.setSelectionRange(0, 0);
      return;
    }
    const cancel = e.target.closest(".cancel-btn");
    if (cancel) { cancelEdit(cancel.closest(".turn")); return; }
    const split = e.target.closest(".split-btn");
    if (split) {
      const form = split.closest(".turn-edit"), ta = form.querySelector("textarea");
      const pos = ta.selectionStart, before = ta.value.slice(0, pos), after = ta.value.slice(pos);
      if (!before.trim() || !after.trim()) { alert("Haz clic dentro del texto, en el punto donde quieres cortar, y vuelve a pulsar «Dividir aquí»."); ta.focus(); return; }
      htmx.ajax("POST", split.dataset.url, {
        source: form, target: "#turns", swap: "outerHTML",
        values: { before, after, csrf_token: form.querySelector("input[name=csrf_token]").value },
      });
      return;
    }
    const use = e.target.closest(".use-suggestion");
    if (use) {
      const p = use.closest(".suggest"), form = document.querySelector(`.speaker[data-speaker="${p.dataset.speaker}"]`);
      const input = form.querySelector("input[name=name]");
      input.value = use.dataset.name;
      input.dispatchEvent(new Event("change", { bubbles: true })); // htmx posts the rename
      p.remove();
    }
  });

  // Role picker: copy the chosen role into the name box before htmx reads the form.
  document.addEventListener("change", (e) => {
    const sel = e.target.closest(".role-pick");
    if (!sel || !sel.value) return;
    const form = sel.closest(".speaker");
    form.querySelector("input[name=name]").value = sel.value;
    const hint = document.querySelector(`.suggest[data-speaker="${form.dataset.speaker}"]`); if (hint) hint.remove();
  }, true);
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const form = e.target.closest && e.target.closest(".speaker");
    if (form) { const sel = form.querySelector(".role-pick"); if (sel) { sel.value = ""; sel.blur(); } } // so Space plays again
  });

  // ---- doubtful words toggle ----------------------------------------------------
  const lowcToggle = document.getElementById("lowc-toggle"), lowcCount = document.getElementById("lowc-count");
  function applyLowc() {
    if (!lowcToggle) return;
    if (transcript) transcript.classList.toggle("hide-lowc", !lowcToggle.checked);
    const n = document.querySelectorAll(".lowc").length;
    if (lowcCount) lowcCount.textContent = `(${n})`;
    lowcToggle.closest("label").hidden = n === 0;
  }
  if (lowcToggle) {
    try { lowcToggle.checked = localStorage.getItem("lowc") !== "off"; } catch (_) {}
    lowcToggle.addEventListener("change", () => { try { localStorage.setItem("lowc", lowcToggle.checked ? "on" : "off"); } catch (_) {} applyLowc(); });
    applyLowc();
  }

  // ---- in-page search: accent- and case-insensitive, highlights, prev/next, scrolls ----
  const find = document.getElementById("find"), findCount = document.getElementById("find-count");
  let marks = [], current = -1;

  function fold(str) {
    // returns folded string + map from folded index -> original index
    const out = [], map = [];
    for (let i = 0; i < str.length; i++) {
      const f = str[i].normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      for (const ch of f) { out.push(ch); map.push(i); }
    }
    return { text: out.join(""), map };
  }

  function clearMarks() {
    document.querySelectorAll(".turn-text mark").forEach((m) => { const parent = m.parentNode; m.replaceWith(m.textContent); parent.normalize(); });
    marks = []; current = -1;
  }

  function textNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), out = [];
    let n; while ((n = walker.nextNode())) out.push(n);
    return out;
  }

  function highlight(query) {
    clearMarks();
    const q = fold(query.trim()).text;
    if (!q) { findCount.textContent = ""; return; }
    // Marks are applied per text node so doubtful-word spans survive.
    document.querySelectorAll(".turn-text").forEach((p) => textNodes(p).forEach((node) => {
      const original = node.textContent;
      const { text, map } = fold(original);
      const ranges = [];
      let from = 0, at;
      while ((at = text.indexOf(q, from)) !== -1) { ranges.push([map[at], map[at + q.length - 1] + 1]); from = at + q.length; }
      if (!ranges.length) return;
      const frag = document.createDocumentFragment();
      let pos = 0;
      ranges.forEach(([s, e]) => {
        frag.appendChild(document.createTextNode(original.slice(pos, s)));
        const m = document.createElement("mark"); m.textContent = original.slice(s, e); frag.appendChild(m); marks.push(m);
        pos = e;
      });
      frag.appendChild(document.createTextNode(original.slice(pos)));
      node.replaceWith(frag);
    }));
    findCount.textContent = marks.length ? `${marks.length} coincidencia${marks.length === 1 ? "" : "s"}` : "Sin coincidencias";
    if (marks.length) go(0);
  }

  function go(i) {
    if (!marks.length) return;
    if (current >= 0) marks[current].classList.remove("current");
    current = (i + marks.length) % marks.length;
    marks[current].classList.add("current");
    marks[current].scrollIntoView({ block: "center", behavior: "smooth" });
    findCount.textContent = `${current + 1} de ${marks.length}`;
  }

  if (find) {
    let timer;
    find.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => highlight(find.value), 150); });
    find.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(e.shiftKey ? current - 1 : current + 1); } });
    document.getElementById("find-next").addEventListener("click", () => go(current + 1));
    document.getElementById("find-prev").addEventListener("click", () => go(current - 1));
    if (find.value) highlight(find.value);
  }
  document.body.addEventListener("htmx:afterSwap", () => { applyLowc(); if (find && find.value) highlight(find.value); });

  // ---- find & replace across the whole hearing ----
  const replaceToggle = document.getElementById("replace-toggle"), replaceForm = document.getElementById("replace-form");
  if (replaceToggle && replaceForm) {
    const findField = document.getElementById("replace-find"), withField = document.getElementById("replace-with");
    const result = document.getElementById("replace-result");
    replaceToggle.addEventListener("click", () => {
      replaceForm.hidden = !replaceForm.hidden;
      if (!replaceForm.hidden) { if (!find.value.trim()) { find.focus(); result.textContent = "Escribe primero qué buscar."; } else withField.focus(); }
    });
    replaceForm.addEventListener("htmx:confirm", (e) => {
      e.preventDefault();
      const q = find.value.trim();
      if (!q) { find.focus(); result.textContent = "Escribe primero qué buscar."; return; }
      findField.value = q;
      if (confirm(`¿Reemplazar «${q}» por «${withField.value}» en toda la transcripción?`)) e.detail.issueRequest(true);
    });
    document.body.addEventListener("replaced", (e) => {
      const n = e.detail.value;
      result.textContent = n ? `${n} reemplazo${n === 1 ? "" : "s"} hecho${n === 1 ? "" : "s"}.` : "No se encontró nada que reemplazar.";
      const undo = document.getElementById("undo"); if (n && undo) undo.disabled = false;
    });
  }
  // Any saved edit makes "Deshacer" available.
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const undo = document.getElementById("undo");
    if (undo && e.detail.successful && e.detail.requestConfig.verb === "post") undo.disabled = false;
  });

  const copy = document.getElementById("copy-all");
  if (copy) copy.addEventListener("click", async () => {
    const text = turns().map((el) => {
      const who = el.querySelector(".turn-speaker select");
      const name = who ? who.options[who.selectedIndex].text : "";
      return `[${el.querySelector(".ts").textContent}] ${name ? name + ": " : ""}${el.querySelector(".turn-text").textContent.trim()}`;
    }).join("\n\n");
    try { await navigator.clipboard.writeText(text); copy.textContent = "¡Copiado!"; setTimeout(() => (copy.textContent = "Copiar todo"), 1500); }
    catch (_) { alert("No se pudo copiar automáticamente. Usa Descargar .txt."); }
  });
})();
