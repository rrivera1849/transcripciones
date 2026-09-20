// Browser notification when a hearing finishes, while this site is open in any tab.
(function () {
  const btn = document.getElementById("notify-btn");
  if (!btn || !("Notification" in window)) return;
  const statuses = new Map();
  function snapshot() {
    document.querySelectorAll("#jobs tr[data-id]").forEach((tr) => {
      const prev = statuses.get(tr.dataset.id), cur = tr.dataset.status;
      if (prev && prev !== cur && (cur === "done" || cur === "error") && Notification.permission === "granted") {
        const n = new Notification("La Transcriptora", {
          body: cur === "done" ? `«${tr.dataset.title}» está lista.` : `No se pudo transcribir «${tr.dataset.title}».`,
          icon: "/static/icon-192.png", tag: tr.dataset.id,
        });
        n.onclick = () => { window.focus(); if (cur === "done") location.href = `/t/${tr.dataset.id}`; };
      }
      statuses.set(tr.dataset.id, cur);
    });
  }
  function refreshButton() {
    const active = document.querySelector("#jobs tr[data-status=uploading], #jobs tr[data-status=queued], #jobs tr[data-status=running]");
    btn.hidden = !active || Notification.permission !== "default";
  }
  btn.addEventListener("click", async () => { await Notification.requestPermission(); refreshButton(); });
  snapshot(); refreshButton();
  document.body.addEventListener("htmx:afterSwap", (e) => { if (e.target.id === "jobs" || e.target.querySelector?.("#jobs")) { snapshot(); refreshButton(); } });
})();
