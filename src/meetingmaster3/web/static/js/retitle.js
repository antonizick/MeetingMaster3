/* MeetingMaster3 review page: "Title & date…" (Phase 15d). Preview, then apply, a rename and
   re-date of the meeting; afterwards the page reloads at the note's new path. Works on read-only
   notes too, so it does not depend on the editor (review.js). */
(function () {
  "use strict";

  const TOAST_KEY = "mm3-retitle-toast";
  const toast = (kind, msg, hint) => (window.mm3Toast ? window.mm3Toast(kind, msg, hint) : null);
  try {
    const pending = sessionStorage.getItem(TOAST_KEY);
    if (pending) {
      sessionStorage.removeItem(TOAST_KEY);
      const t = JSON.parse(pending);
      // after the reload, so the toast is seen on the renamed note
      window.addEventListener("load", () => toast("info", t.message, t.hint));
    }
  } catch (e) { /* private window: no toast after the reload */ }

  const dialog = document.getElementById("dlg-retitle");
  const button = document.getElementById("btn-retitle");
  if (!dialog || !button) return;
  const form = document.getElementById("form-retitle");
  const result = document.getElementById("retitle-result");
  const base = "/ui/review/" + dialog.dataset.mm3Id;
  const csrf = () => { const m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ""; };
  let digest = null;

  async function call(path, body) {
    const res = await fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf() },
      body: JSON.stringify(body),
    });
    let out = {};
    try { out = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      const err = new Error(out.message || "The request failed (" + res.status + ").");
      err.data = out;
      throw err;
    }
    return out;
  }

  function fields() {
    const f = new FormData(form);
    return {
      path: dialog.dataset.path,
      base_sha: dialog.dataset.sha,
      title: String(f.get("title") || ""),
      date: String(f.get("date") || ""),
      time: String(f.get("time") || ""),
    };
  }

  async function busy(el, fn) {
    el.disabled = true;
    el.setAttribute("aria-busy", "true");
    try { return await fn(); }
    catch (err) { toast("error", err.message, (err.data && err.data.hint) || ""); return undefined; }
    finally { el.disabled = false; el.removeAttribute("aria-busy"); }
  }

  button.addEventListener("click", () => {
    if (window.mm3ReviewDirty && window.mm3ReviewDirty()) {
      toast("error", "Save your edits first.", "Changing the title and date works on the note as saved in the vault.");
      return;
    }
    result.innerHTML = "";
    digest = null;
    dialog.showModal();
  });
  form.addEventListener("input", () => { result.innerHTML = ""; digest = null; });
  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const out = await busy(form.querySelector('button[type="submit"]'), () => call("/retitle/preview", fields()));
    if (!out) return;
    digest = out.blocked || out.empty ? null : out.digest;
    result.innerHTML = out.html; // server-rendered, escaped
    const heading = result.querySelector("h3");
    if (heading) heading.focus();
  });
  dialog.addEventListener("click", async (evt) => {
    if (evt.target.closest("[data-close]")) { dialog.close(); return; }
    const apply = evt.target.closest("#retitle-apply");
    if (!apply || !digest) return;
    await busy(apply, async () => {
      const out = await call("/retitle/apply", Object.assign(fields(), { digest }));
      const links = out.links ? " " + out.links + " link" + (out.links === 1 ? "" : "s") + " in other notes updated." : "";
      try {
        sessionStorage.setItem(TOAST_KEY, JSON.stringify({
          message: "Renamed to " + out.note.split("/").pop() + "." + links,
          hint: "Backups of the changed files: " + out.backup + (out.warnings.length ? " · " + out.warnings.join(" ") : ""),
        }));
      } catch (e) { /* no toast after the reload */ }
      window.location.assign(out.url);
    });
  });
})();
