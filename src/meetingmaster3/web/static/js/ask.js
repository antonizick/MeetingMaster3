/* MeetingMaster3 Ask page (Phase 15j, R31): send the question, follow it with the shared progress
   widget (progress.js), then open the saved answer. A question keeps running on the server if the
   page is left; coming back reattaches to it. */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const form = $("#ask-form");
  if (!form) return;
  const toast = (kind, msg, hint) => (window.mm3Toast ? window.mm3Toast(kind, msg, hint) : null);
  const csrf = () => { const m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };
  const backend = $("#ask-backend");
  const model = $("#ask-model");
  const submit = $("#ask-submit");
  const progress = $("#ask-progress");
  const inline = $("#ask-inline");

  async function call(path, body, method) {
    const res = await fetch(path, {
      method: method || "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf() },
      body: body === undefined ? undefined : JSON.stringify(body),
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

  function showError(message, hint) {
    const box = document.createElement("div");
    box.className = "alert error";
    box.setAttribute("role", "alert");
    const p = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = message;
    p.append(strong);
    if (hint) p.append(document.createTextNode(" " + hint));
    box.append(p);
    inline.replaceChildren(box);
  }

  if (backend && model) {
    backend.addEventListener("change", () => {
      const opt = backend.selectedOptions[0];
      if (opt) model.value = opt.dataset.model || "";
    });
  }

  async function follow(snapshot) {
    submit.disabled = true;
    inline.replaceChildren();
    try {
      const final = await window.mm3Progress.run(progress, {
        snapshot, csrf,
        taskUrl: "/ask/task/" + snapshot.id,
        cancelUrl: "/ask/task/" + snapshot.id + "/cancel",
        title: "Answering the question",
        note: "You can leave this page: the question keeps running, and its answer is added to the list below.",
      });
      if (final.state === "failed") {
        progress.replaceChildren();
        showError((final.error && final.error.message) || "The question could not be answered.",
          (final.error && final.error.hint) || "");
        return;
      }
      if (final.state !== "done") {
        progress.replaceChildren();
        if (final.state === "cancelled") toast("info", "Question cancelled.", "Nothing was saved.");
        return;
      }
      const out = await call("/ask/task/" + snapshot.id + "/result", undefined, "GET");
      if (out.url) { window.location.assign(out.url); return; }
      progress.replaceChildren();
      const article = document.createElement("article");
      article.className = "card note ask-answer";
      article.innerHTML = out.html; // rendered and sanitised by the server (S3)
      inline.replaceChildren(article);
    } catch (err) {
      showError(err.message, (err.data && err.data.hint) || "");
    } finally {
      submit.disabled = false;
    }
  }

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const data = new FormData(form);
    const question = String(data.get("question") || "").trim();
    if (!question) { showError("Type a question first."); $("#ask-q").focus(); return; }
    const consent = $("#ask-cloud-consent");
    if (consent && !consent.checked) {
      showError("Tick the box to send the excerpts to the cloud for this question,", "or choose a local model.");
      consent.focus();
      return;
    }
    const body = {
      question,
      backend: String(data.get("backend") || "") || null,
      model: String(data.get("model") || "").trim() || null,
      cloud_consent: Boolean(consent && consent.checked),
      date_from: String(data.get("date_from") || "") || null,
      date_to: String(data.get("date_to") || "") || null,
      person: String(data.get("person") || "").trim() || null,
      previous_id: String(data.get("previous_id") || "") || null,
    };
    submit.disabled = true;
    try {
      const out = await call("/ask/start", body);
      await follow(out.task);
    } catch (err) {
      submit.disabled = false;
      showError(err.message, (err.data && err.data.hint) || "");
    }
  });

  if (form.dataset.running) {
    call("/ask/task", undefined, "GET").then((out) => { if (out.task) follow(out.task); }).catch(() => {});
  }
})();
