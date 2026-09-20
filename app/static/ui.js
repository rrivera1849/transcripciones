// Text size and contrast, remembered in this browser.
(function () {
  const menu = document.querySelector(".ui-menu");
  if (!menu) return;
  const h = document.documentElement;
  function load() { try { return JSON.parse(localStorage.getItem("ui") || "{}"); } catch (_) { return {}; } }
  function save(u) { try { localStorage.setItem("ui", JSON.stringify(u)); } catch (_) {} }
  function apply(u) {
    if (u.size) h.dataset.size = u.size; else delete h.dataset.size;
    if (u.contrast) h.dataset.contrast = "1"; else delete h.dataset.contrast;
  }
  const u = load();
  menu.querySelectorAll("input[name=size]").forEach((r) => { r.checked = (u.size || "") === r.value; });
  menu.querySelector("input[name=contrast]").checked = !!u.contrast;
  menu.addEventListener("change", () => {
    const size = menu.querySelector("input[name=size]:checked");
    const next = { size: size ? size.value : "", contrast: menu.querySelector("input[name=contrast]").checked };
    apply(next); save(next);
  });
})();

// Popover-style <details> (the Aa menu, the history panel) close on a click outside or Escape.
(function () {
  const pops = () => document.querySelectorAll("details.ui-menu[open], details.history-box[open]");
  document.addEventListener("click", (e) => pops().forEach((d) => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") pops().forEach((d) => { d.open = false; }); });
})();
