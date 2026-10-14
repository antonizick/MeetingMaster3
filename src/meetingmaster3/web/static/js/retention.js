/* MeetingMaster3 review screen: keep the recording forever, or allow its deletion again (R26).
   The server builds the sentence; this only sends the choice and swaps in the new fragment. */
(function () {
  "use strict";
  const dataEl = document.getElementById("review-data");
  const slot = document.getElementById("retention-slot");
  if (!dataEl || !slot) return;
  const data = JSON.parse(dataEl.textContent);
  const csrf = () => { const m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ""; };
  const toast = (kind, msg, hint) => (window.mm3Toast ? window.mm3Toast(kind, msg, hint) : null);
  const dialog = document.getElementById("dlg-unkeep");

  async function send(keep, button) {
    if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); }
    try {
      const res = await fetch("/ui/review/" + data.mm3_id + "/keep", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify({ path: data.path, keep }),
      });
      let out = {};
      try { out = await res.json(); } catch (e) { /* not JSON */ }
      if (!res.ok) { toast("error", out.message || "The request failed.", out.hint || ""); return; }
      slot.innerHTML = out.html; // server-rendered fragment
      const next = document.getElementById("retention-btn");
      if (next) next.focus();
    } catch (err) {
      toast("error", "The request failed.", String(err));
    } finally {
      if (button && button.isConnected) { button.disabled = false; button.removeAttribute("aria-busy"); }
    }
  }

  slot.addEventListener("click", (evt) => {
    const btn = evt.target.closest("#retention-btn");
    if (!btn) return;
    if (btn.dataset.action === "keep") { send(true, btn); return; }
    const box = document.getElementById("retention");
    document.getElementById("unkeep-message").textContent = (box && box.dataset.undoText) || "";
    dialog.showModal();
  });
  dialog.addEventListener("click", (evt) => { if (evt.target.closest("[data-close]")) dialog.close(); });
  document.getElementById("unkeep-ok").addEventListener("click", () => {
    dialog.close();
    send(false, document.getElementById("retention-btn"));
  });
})();
