/* MeetingMaster3 review workspace: the note editor and its actions.
   The note is edited as parts (properties, your own text between sections, each section's
   content); the marker lines are not editable. The server joins the parts back, so unchanged
   bytes stay exactly as they were. */
(function () {
  "use strict";

  const dataEl = document.getElementById("review-data");
  const editor = document.getElementById("editor");
  if (!dataEl || !editor) return;
  const data = JSON.parse(dataEl.textContent);
  const base = "/ui/review/" + data.mm3_id;
  const MARKER = /^[ \t]*<!--[ \t]*\/?[ \t]*mm3[ \t]*:[ \t]*section/im;
  const MARKER_LINES = /^[ \t]*<!--[ \t]*\/?[ \t]*mm3[ \t]*:[ \t]*section.*$/gim;

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const toast = (kind, msg, hint) => (window.mm3Toast ? window.mm3Toast(kind, msg, hint) : null);
  const csrf = () => { const m = $('meta[name="csrf-token"]'); return m ? m.content : ""; };
  const status = $("#save-status");

  async function call(path, body, method) {
    const res = await fetch(base + path, {
      method: method || "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let out = {};
    try { out = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      const err = new Error(out.message || "The request failed (" + res.status + ").");
      err.data = out;
      err.status = res.status;
      throw err;
    }
    return out;
  }
  const fail = (err) => toast("error", err.message, (err.data && err.data.hint) || "");

  async function busy(button, fn) {
    const label = button ? button.textContent : "";
    if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); }
    try { return await fn(); } catch (err) { fail(err); return undefined; }
    finally { if (button) { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = label; } }
  }

  // -- parts and dirty state ------------------------------------------------------------------
  const parts = () => $$("textarea.part", editor);
  function collect() {
    const texts = [];
    const sections = {};
    let frontmatter = null;
    for (const ta of parts()) {
      if (ta.dataset.kind === "text") texts[Number(ta.dataset.index)] = ta.value;
      else if (ta.dataset.kind === "section") sections[ta.dataset.id] = ta.value;
      else if (ta.dataset.kind === "frontmatter") frontmatter = ta.value;
    }
    return { texts, sections, frontmatter };
  }
  let saved = JSON.stringify(collect());
  const markerSnapshot = new Map(parts().map((ta) => [ta, (ta.value.match(MARKER_LINES) || []).join("\n")]));
  const isDirty = () => JSON.stringify(collect()) !== saved;

  function setStatus(text, kind) {
    if (!status) return;
    status.textContent = text;
    status.dataset.kind = kind || "";
  }

  function autosize(ta) {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + 2 + "px";
  }

  function checkMarkers(ta) {
    if (ta.dataset.kind === "section") {
      const warn = ta.parentElement.querySelector(".marker-warn");
      const bad = MARKER.test(ta.value);
      warn.hidden = !bad;
      warn.textContent = bad ? "This section now contains a section marker line. Remove it before saving." : "";
    } else {
      const changed = parts().some((t) => t.dataset.kind !== "section" &&
        (t.value.match(MARKER_LINES) || []).join("\n") !== markerSnapshot.get(t));
      const warn = $("#text-marker-warn");
      if (warn) warn.hidden = !changed;
    }
  }

  let draftTimer = null;
  function changed(ta) {
    if (ta) { autosize(ta); checkMarkers(ta); }
    if (!isDirty()) { setStatus("Saved", "saved"); return; }
    setStatus("Unsaved changes", "dirty");
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 1500);
  }

  async function saveDraft() {
    if (!isDirty()) return;
    try {
      await call("/draft", { path: data.path, base_sha: data.base_sha, edits: collect() });
      setStatus("Unsaved changes · draft kept", "dirty");
    } catch (err) {
      setStatus("Unsaved changes · draft not kept", "dirty");
    }
  }

  for (const ta of parts()) {
    autosize(ta);
    ta.addEventListener("input", () => changed(ta));
  }
  window.addEventListener("resize", () => parts().forEach(autosize));
  // A closed <details> has no layout: size its textarea when it opens.
  for (const d of $$("details.fm", editor)) d.addEventListener("toggle", () => parts().forEach(autosize));
  window.addEventListener("beforeunload", (evt) => { if (isDirty()) { saveDraft(); evt.preventDefault(); } });

  // -- save ----------------------------------------------------------------------------------
  async function save(extra) {
    clearTimeout(draftTimer);
    setStatus("Saving…", "busy");
    const edits = collect();
    try {
      const out = await call("/save", Object.assign({ path: data.path, base_sha: data.base_sha, edits }, extra || {}));
      data.base_sha = out.sha;
      saved = JSON.stringify(edits);
      for (const ta of parts()) markerSnapshot.set(ta, (ta.value.match(MARKER_LINES) || []).join("\n"));
      parts().forEach(checkMarkers);
      setStatus(isDirty() ? "Unsaved changes" : "Saved to vault " + out.saved_at, isDirty() ? "dirty" : "saved");
      return true;
    } catch (err) {
      setStatus("Not saved", "error");
      if (err.status === 409 && err.data.conflict) {
        $("#conflict-diff").innerHTML = err.data.conflict.html; // server-rendered, escaped
        $("#dlg-conflict").dataset.theirs = err.data.conflict.theirs_sha;
        $("#dlg-conflict").showModal();
      } else if (err.data && err.data.code === "E_MARKER_EDIT" && err.data.details && err.data.details.confirm) {
        $("#markers-message").textContent = err.message;
        $("#dlg-markers").dataset.extra = JSON.stringify(extra || {});
        $("#dlg-markers").showModal();
      } else {
        fail(err);
      }
      return false;
    }
  }
  $("#btn-save").addEventListener("click", (evt) => busy(evt.currentTarget, () => save()));
  document.addEventListener("keydown", (evt) => {
    if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "s") { evt.preventDefault(); save(); }
  });
  $("#conflict-mine").addEventListener("click", () => {
    const dlg = $("#dlg-conflict");
    dlg.close();
    save({ force_sha: dlg.dataset.theirs });
  });
  $("#conflict-theirs").addEventListener("click", async () => {
    try { await call("/draft", undefined, "DELETE"); } catch (e) { /* reload anyway */ }
    saved = JSON.stringify(collect()); // do not warn on unload
    window.location.reload();
  });
  $("#markers-save").addEventListener("click", () => {
    const dlg = $("#dlg-markers");
    dlg.close();
    save(Object.assign(JSON.parse(dlg.dataset.extra || "{}"), { allow_marker_changes: true }));
  });

  // -- rendered preview ----------------------------------------------------------------------
  const previewBtn = $("#btn-preview");
  const preview = $("#preview");
  previewBtn.addEventListener("click", () => busy(previewBtn, async () => {
    const showing = previewBtn.getAttribute("aria-pressed") === "true";
    if (showing) {
      preview.hidden = true; editor.hidden = false;
      previewBtn.setAttribute("aria-pressed", "false");
      return;
    }
    const out = await call("/render", { path: data.path, base_sha: data.base_sha, edits: collect() });
    preview.innerHTML = out.html; // sanitised by the server (raw HTML off, links filtered)
    preview.hidden = false; editor.hidden = true;
    previewBtn.setAttribute("aria-pressed", "true");
  }));

  // -- dialogs: close buttons, cloud-consent checkbox ---------------------------------------
  document.addEventListener("click", (evt) => {
    const close = evt.target.closest("[data-close]");
    if (close && close.closest("dialog")) close.closest("dialog").close();
    const mode = evt.target.closest("[data-diff-mode]");
    if (mode) {
      const diff = mode.closest(".diff");
      diff.dataset.mode = mode.dataset.diffMode;
      diff.querySelector(".diff-split").hidden = mode.dataset.diffMode !== "split";
      diff.querySelector(".diff-unified").hidden = mode.dataset.diffMode !== "unified";
      for (const b of diff.querySelectorAll("[data-diff-mode]")) b.setAttribute("aria-pressed", String(b === mode));
    }
  });
  function syncConsent(form) {
    const sel = form.querySelector(".backend-select");
    const label = form.querySelector(".consent");
    if (!sel || !label) return;
    const opt = sel.options[sel.selectedIndex];
    const cloud = opt && opt.dataset.consent === "yes";
    label.hidden = !cloud;
    label.querySelector(".consent-name").textContent = opt ? opt.value : "";
    if (!cloud) label.querySelector("input").checked = false;
  }
  for (const form of $$("#form-regen, #form-switch")) {
    syncConsent(form);
    form.querySelector(".backend-select").addEventListener("change", () => syncConsent(form));
  }
  const modelOptions = (form) => {
    const f = new FormData(form);
    return {
      backend: f.get("backend") || null,
      model: String(f.get("model") || "").trim() || null,
      cloud_consent: f.get("cloud_consent") === "on",
    };
  };
  const requireClean = (what) => {
    if (!isDirty()) return true;
    toast("error", "Save your edits first.", what + " works on the note as saved in the vault.");
    return false;
  };

  // -- per-section regeneration --------------------------------------------------------------
  const regenDialog = $("#dlg-regen");
  const regenForm = $("#form-regen");
  let regenTarget = null; // {sectionId, title, append}

  function openRegen(sectionId, title, append) {
    regenTarget = { sectionId, title, append };
    regenDialog.querySelector('[data-fill="title"]').textContent = title;
    regenDialog.showModal();
    $("#regen-instructions").focus();
  }
  for (const btn of $$(".regen-btn")) {
    btn.addEventListener("click", () => openRegen(btn.dataset.sectionId, btn.dataset.title, false));
  }
  for (const btn of $$(".append-btn")) {
    btn.addEventListener("click", () => {
      if (requireClean("Appending a section")) openRegen(btn.dataset.sectionId, btn.dataset.sectionId, true);
    });
  }

  regenForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const target = regenTarget;
    regenDialog.close();
    const ta = target.append ? null : $('textarea[data-kind="section"][data-id="' + CSS.escape(target.sectionId) + '"]', editor);
    const area = target.append ? $("#append-result") : $('.regen-result[data-section-id="' + CSS.escape(target.sectionId) + '"]', editor);
    area.innerHTML = "";
    const wait = document.createElement("p");
    wait.className = "alert info";
    wait.setAttribute("role", "status");
    wait.textContent = "Regenerating “" + target.title + "”…";
    area.append(wait);
    try {
      const out = await call("/regenerate", Object.assign({
        path: data.path,
        base_sha: data.base_sha,
        section_id: target.sectionId,
        inner: ta ? ta.value : null,
        instructions: $("#regen-instructions").value.trim() || null,
        append: target.append,
      }, modelOptions(regenForm)));
      area.innerHTML = out.html; // server-rendered diff, escaped
      area.mm3 = { newInner: out.new_inner, sectionId: target.sectionId, ta };
      const first = area.querySelector("[data-regen]");
      if (first) first.focus();
    } catch (err) {
      area.innerHTML = "";
      fail(err);
    }
  });

  document.addEventListener("click", async (evt) => {
    const btn = evt.target.closest("[data-regen]");
    if (!btn) return;
    const area = btn.closest(".regen-result, #append-result");
    const pending = area && area.mm3;
    if (!pending) return;
    const action = btn.dataset.regen;
    if (action === "discard") { area.innerHTML = ""; area.mm3 = null; return; }
    if (action === "append") {
      if (!requireClean("Appending a section")) return;
      await busy(btn, async () => {
        await call("/append-section", { path: data.path, base_sha: data.base_sha, section_id: pending.sectionId, inner: pending.newInner });
        saved = JSON.stringify(collect());
        window.location.reload();
      });
      return;
    }
    await busy(btn, async () => {
      let archived = "";
      if (action === "accept-archive") {
        const out = await call("/archive-section", { path: data.path, section_id: pending.sectionId, inner: pending.ta.value });
        archived = out.archive;
      }
      pending.ta.value = pending.newInner;
      area.innerHTML = "";
      area.mm3 = null;
      changed(pending.ta);
      pending.ta.focus();
      if (archived) toast("info", "New version accepted. Previous version archived.", archived + ". Save to vault to keep the new one.");
      else toast("info", "New version accepted.", "Save to vault to keep it.");
    });
  });

  // -- switch template -----------------------------------------------------------------------
  const switchDialog = $("#dlg-switch");
  const switchForm = $("#form-switch");
  let switchToken = null;
  $("#btn-switch").addEventListener("click", () => {
    if (!requireClean("Switching the template")) return;
    $("#switch-result").innerHTML = "";
    switchDialog.showModal();
  });
  switchForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const button = switchForm.querySelector('button[type="submit"]');
    const result = $("#switch-result");
    result.innerHTML = '<p class="alert info" role="status">Writing the whole note again. This can take a few minutes…</p>';
    const out = await busy(button, () => call("/switch/preview", Object.assign({
      path: data.path, base_sha: data.base_sha, template: new FormData(switchForm).get("template"),
    }, modelOptions(switchForm))));
    if (!out) { result.innerHTML = ""; return; }
    switchToken = out.token;
    result.innerHTML = out.html;
  });
  switchDialog.addEventListener("click", async (evt) => {
    const apply = evt.target.closest("#switch-apply");
    if (!apply) return;
    await busy(apply, async () => {
      const out = await call("/switch/apply", { path: data.path, token: switchToken });
      toast("info", "Template switched. The previous note was archived.", out.archive);
      saved = JSON.stringify(collect());
      window.location.reload();
    });
  });

  // -- rename speakers -----------------------------------------------------------------------
  const renameDialog = $("#dlg-rename");
  const renameForm = $("#form-rename");
  let companionSha = null;
  const names = () => {
    const out = {};
    for (const input of $$('input[name^="name__"]', renameForm)) out[input.name.slice(6)] = input.value;
    return out;
  };
  $("#btn-rename").addEventListener("click", () => {
    if (!requireClean("Renaming speakers")) return;
    $("#rename-result").innerHTML = "";
    renameDialog.showModal();
  });
  renameForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const out = await busy(renameForm.querySelector('button[type="submit"]'), () =>
      call("/speakers/preview", { path: data.path, base_sha: data.base_sha, names: names() }));
    if (!out) return;
    companionSha = out.companion_sha;
    $("#rename-result").innerHTML = out.html;
  });
  renameDialog.addEventListener("click", async (evt) => {
    const apply = evt.target.closest("#rename-apply");
    if (!apply) return;
    await busy(apply, async () => {
      await call("/speakers/apply", { path: data.path, base_sha: data.base_sha, names: names(), companion_sha: companionSha });
      saved = JSON.stringify(collect());
      window.location.reload();
    });
  });

  // -- unsaved draft -------------------------------------------------------------------------
  const restore = $("#draft-restore");
  if (restore && data.draft && data.draft.usable) {
    restore.addEventListener("click", () => {
      const d = data.draft;
      for (const ta of parts()) {
        if (ta.dataset.kind === "text" && d.texts[Number(ta.dataset.index)] !== undefined) ta.value = d.texts[Number(ta.dataset.index)];
        else if (ta.dataset.kind === "section" && d.sections[ta.dataset.id] !== undefined) ta.value = d.sections[ta.dataset.id];
        else if (ta.dataset.kind === "frontmatter" && d.frontmatter !== null) ta.value = d.frontmatter;
        autosize(ta);
        checkMarkers(ta);
      }
      $("#draft-banner").remove();
      changed(null);
      toast("info", "Your edits are back.", "Save to vault to keep them.");
    });
  }
  const discard = $("#draft-discard");
  if (discard) {
    discard.addEventListener("click", () => busy(discard, async () => {
      await call("/draft", undefined, "DELETE");
      $("#draft-banner").remove();
    }));
  }

  // -- note-only mode: link a found transcript, or transcribe the recording again ------------
  document.addEventListener("click", async (evt) => {
    const link = evt.target.closest(".link-transcript");
    if (link) {
      await busy(link, async () => {
        await call("/link-transcript", { path: data.path, base_sha: data.base_sha, transcript: link.dataset.transcript });
        window.location.reload();
      });
    }
    const again = evt.target.closest("#btn-reprocess");
    if (again) {
      await busy(again, async () => {
        const out = await call("/reprocess", { path: data.path });
        window.location.assign(out.url);
      });
    }
  });
})();
