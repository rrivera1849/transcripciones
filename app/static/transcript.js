// Seek-on-click, highlight the playing turn, inline edit toggles, copy all.
(function () {
  const audio = document.getElementById("audio");
  function turns() { return Array.from(document.querySelectorAll(".turn")); }

  document.addEventListener("click", (e) => {
    const seek = e.target.closest("[data-seek]");
    if (seek && audio) { audio.currentTime = parseFloat(seek.dataset.seek); audio.play(); return; }
    const edit = e.target.closest(".edit-btn");
    if (edit) { const t = edit.closest(".turn"); t.querySelector(".turn-edit").hidden = false; t.querySelector(".turn-text").hidden = true; return; }
    const cancel = e.target.closest(".cancel-btn");
    if (cancel) { const t = cancel.closest(".turn"); t.querySelector(".turn-edit").hidden = true; t.querySelector(".turn-text").hidden = false; }
  });

  if (audio) {
    audio.addEventListener("timeupdate", () => {
      const t = audio.currentTime;
      turns().forEach((el) => {
        const on = t >= parseFloat(el.dataset.start) && t < parseFloat(el.dataset.end) + 0.5;
        el.classList.toggle("playing", on);
      });
    });
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
    document.querySelectorAll(".turn-text mark").forEach((m) => m.replaceWith(m.textContent));
    document.querySelectorAll(".turn-text").forEach((p) => p.normalize());
    marks = []; current = -1;
  }

  function highlight(query) {
    clearMarks();
    const q = fold(query.trim()).text;
    if (!q) { findCount.textContent = ""; return; }
    document.querySelectorAll(".turn-text").forEach((p) => {
      const original = p.textContent;
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
      p.replaceChildren(frag);
    });
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
    document.body.addEventListener("htmx:afterSwap", () => { if (find.value) highlight(find.value); });
    if (find.value) highlight(find.value);
  }

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
