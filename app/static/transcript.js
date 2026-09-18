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
