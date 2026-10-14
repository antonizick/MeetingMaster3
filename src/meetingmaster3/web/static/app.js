/* MeetingMaster3 UI behaviour. No inline script is allowed by the CSP, so everything lives here.
   Alpine runs in its CSP build: templates may only reference properties and call methods. */
(function () {
  "use strict";

  const csrfToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  };

  function toast(kind, message, hint) {
    const region = document.getElementById("toasts");
    if (!region) return;
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    const strong = document.createElement("strong");
    strong.textContent = message;
    el.append(strong);
    if (hint) el.append(" ", hint);
    region.replaceChildren(el);
  }
  window.mm3Toast = toast; // used by the review workspace (static/js/review.js)

  // -- Copy-path buttons (Settings > About): <button data-copy="text"> -------------------------------
  document.body.addEventListener("click", (evt) => {
    const button = evt.target instanceof Element ? evt.target.closest("[data-copy]") : null;
    if (!button) return;
    const text = button.getAttribute("data-copy") || "";
    const done = () => toast("info", "Copied.", text);
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => toast("error", "Could not copy.", text));
    } else {
      toast("info", "Select and copy this path:", text);
    }
  });

  // -- HTMX: show failed requests as toasts instead of swapping them in -------------------------
  document.body.addEventListener("htmx:beforeSwap", (evt) => {
    const xhr = evt.detail.xhr;
    if (!xhr || xhr.status < 400) return;
    evt.detail.shouldSwap = false;
    evt.detail.isError = false;
    const type = xhr.getResponseHeader("Content-Type") || "";
    if (type.includes("json")) {
      try {
        const err = JSON.parse(xhr.responseText);
        toast("error", err.message || "The request failed.", err.hint || "");
        return;
      } catch (e) { /* fall through */ }
    } else if (type.includes("html") && xhr.responseText.includes('class="toast error"')) {
      document.getElementById("toasts").innerHTML = xhr.responseText; // our own escaped fragment
      return;
    }
    toast("error", "The request failed (" + xhr.status + ").", "Reload the page and try again.");
  });
  document.body.addEventListener("htmx:sendError", () => {
    toast("error", "Cannot reach MeetingMaster3.", "Is the server still running?");
  });

  // -- Paged sections (Meetings): after a page swap, put focus back on the section heading -------
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const elt = evt.detail && evt.detail.requestConfig ? evt.detail.requestConfig.elt : null;
    const id = elt && elt.dataset ? elt.dataset.focus : "";
    const heading = id ? document.getElementById(id) : null;
    if (heading) heading.focus({ preventScroll: false });
  });

  // -- Job page: the SSE stream says "something changed", the server renders the panel ---------
  function setupJobPanel() {
    const panel = document.getElementById("job-panel");
    if (!panel || !panel.dataset.eventsUrl) return;
    const live = document.getElementById("live-status");
    let source = null;
    let queued = false;
    let lastLive = "";

    const marker = () => panel.querySelector("[data-live]");
    const isFinal = () => {
      const m = marker();
      return m ? m.dataset.final === "true" : panel.dataset.final === "true";
    };
    const refresh = () => {
      if (queued) return;
      queued = true;
      setTimeout(() => { queued = false; htmx.trigger(panel, "mm3:refresh"); }, 250);
    };
    const close = () => { if (source) { source.close(); source = null; } };
    const open = () => {
      if (source || isFinal() || !window.EventSource) return;
      source = new EventSource(panel.dataset.eventsUrl);
      for (const name of ["snapshot", "stage", "job"]) source.addEventListener(name, refresh);
      source.onerror = () => { close(); setTimeout(open, 2000); }; // the server closes after the end
    };

    panel.addEventListener("htmx:afterSwap", () => {
      const m = marker();
      // The tab title follows the job, so a background tab shows its state (no announcement).
      if (m && m.dataset.title && document.title !== m.dataset.title) document.title = m.dataset.title;
      if (m && live && m.dataset.live !== lastLive) {
        lastLive = m.dataset.live;
        live.textContent = lastLive;
      }
      if (isFinal()) close(); else open();
    });
    // A job that is running but quiet (a long stage) still updates its clock and ETA.
    setInterval(() => {
      const m = marker();
      if (m && ["queued", "running"].includes(m.dataset.status)) refresh();
    }, 5000);
    open();
  }

  // -- Alpine components ----------------------------------------------------------------------
  document.addEventListener("alpine:init", () => {
    Alpine.data("uploader", () => ({
      file: null,
      dragging: false,
      uploading: false,
      progress: 0,
      error: "",
      errorHint: "",
      backendName: "",
      badge: "",
      needsConsent: false,
      consented: "",
      modelNote: "",
      modelProblem: "",
      models: {},
      suggestedModel: "",
      templateHint: "",

      dateEdited: false,
      dateFromName: false,

      today() { return new Date().toLocaleDateString("en-CA"); }, // in the browser's time zone

      init() {
        const date = this.field("meeting_date");
        date.value = this.today();
        date.addEventListener("input", () => { this.dateEdited = true; this.dateFromName = false; });
        this.backendChanged();
        this.templateChanged();
      },

      get hasError() { return this.error !== ""; },
      get hasFile() { return this.file !== null; },
      get cannotStart() { return this.file === null || this.uploading; },
      get startHint() { return this.file === null ? "Choose a file first." : ""; },
      get dropClass() { return this.dragging ? "dragging" : ""; },
      get badgeClass() { return this.badge === "local" ? "local" : "cloud"; },
      get consentValue() {
        return this.needsConsent && this.consented === this.backendName ? "true" : "false";
      },
      get fileLabel() {
        if (this.file === null) {
          return "No file chosen. Up to " + this.$root.dataset.maxMb + " MB.";
        }
        return this.file.name + " (" + (this.file.size / 1048576).toFixed(1) + " MB)";
      },

      field(name) { return this.$root.elements[name]; },

      dragOver() { this.dragging = true; },
      dragLeave() { this.dragging = false; },
      onDrop(evt) {
        this.dragging = false;
        const files = evt.dataTransfer && evt.dataTransfer.files;
        if (files && files.length) {
          this.field("file").files = files;
          this.setFile(files[0]);
        }
      },
      onPick(evt) {
        const files = evt.target.files;
        if (files && files.length) this.setFile(files[0]);
      },

      async setFile(file) {
        this.file = file;
        this.error = "";
        const max = Number(this.$root.dataset.maxMb) * 1048576;
        if (file.size > max) {
          this.error = "That file is larger than the " + this.$root.dataset.maxMb + " MB limit.";
          this.errorHint = "Trim or compress the recording first.";
        }
        this.prefill(file.name);
        this.loadHardware();
      },

      async prefill(name) {
        let guess = {};
        try {
          const res = await fetch("/ui/parse-filename?name=" + encodeURIComponent(name));
          guess = await res.json();
        } catch (e) { /* the form just stays empty */ }
        const title = this.field("title");
        const date = this.field("meeting_date");
        const time = this.field("meeting_time");
        if (!title.value) title.value = guess.title || name.replace(/\.[^.]+$/, "");
        // A date found in the file name beats the "today" default, but never an edit by the user.
        if (!this.dateEdited) {
          date.value = guess.date || this.today();
          this.dateFromName = Boolean(guess.date);
        }
        if (!time.value && guess.time) time.value = guess.time;
      },

      audioDuration() {
        return new Promise((resolve) => {
          const probe = document.createElement("audio");
          const url = URL.createObjectURL(this.file);
          const done = (value) => { URL.revokeObjectURL(url); resolve(value); };
          probe.preload = "metadata";
          probe.onloadedmetadata = () => done(Number.isFinite(probe.duration) ? probe.duration : null);
          probe.onerror = () => done(null);
          probe.src = url;
        });
      },

      async loadHardware() {
        if (this.file === null) return;
        const duration = await this.audioDuration();
        const diarize = this.field("diarize").checked;
        let url = "/ui/hardware?diarize=" + diarize;
        if (duration) url += "&duration=" + duration.toFixed(1);
        htmx.ajax("GET", url, { target: "#hardware-panel", swap: "innerHTML" });
      },
      diarizeChanged() { this.loadHardware(); },

      templateChanged() {
        const sel = this.field("template");
        const opt = sel.options[sel.selectedIndex];
        this.templateHint = opt ? opt.dataset.description || "" : "";
      },

      backendChanged() {
        const sel = this.field("backend");
        const opt = sel.options[sel.selectedIndex];
        if (!opt) return;
        this.backendName = opt.value;
        this.badge = opt.dataset.badge || "";
        this.needsConsent = opt.dataset.consent === "yes";
        this.field("model").value = opt.dataset.model || "";
        this.listModels(opt.value, this.badge === "local");
        if (this.needsConsent && this.consented !== opt.value) this.$refs.consent.showModal();
      },
      allowCloud() {
        this.consented = this.backendName;
        this.$refs.consent.close();
      },
      refuseCloud() {
        this.$refs.consent.close();
        const sel = this.field("backend");
        const local = Array.from(sel.options).find((o) => o.dataset.consent === "no");
        if (local) { sel.value = local.value; this.backendChanged(); }
      },

      async listModels(name, isLocal) {
        const list = document.getElementById("model-list");
        list.replaceChildren();
        this.models = {};
        this.suggestedModel = "";
        this.modelNote = "";
        this.modelProblem = "";
        if (!isLocal) {
          this.modelNote = "Type the model id this provider should use.";
          return;
        }
        try {
          const res = await fetch("/api/llm/backends/" + encodeURIComponent(name) + "/models");
          const body = await res.json();
          if (!res.ok) throw new Error(body.hint || body.message);
          for (const m of body.models) {
            this.models[m.id] = m;
            if (!m.usable) continue; // embedding models and tiny windows cannot write notes
            const o = document.createElement("option");
            o.value = m.id;
            if (m.context_window) o.label = m.context_window.toLocaleString() + "-token context";
            list.append(o);
          }
          this.suggestedModel = body.suggested || "";
          const input = this.field("model");
          const current = this.models[input.value];
          if ((!input.value || (current && !current.usable)) && this.suggestedModel) {
            input.value = this.suggestedModel;
          }
          if (!body.models.length) this.modelNote = "No models are installed for this backend yet.";
          else if (!this.suggestedModel) {
            this.modelNote = "None of the installed models can write notes. Install a chat " +
              "model, for example: ollama pull qwen3:8b";
          } else this.modelChanged();
        } catch (e) {
          this.modelNote = "Could not list models (" + e.message + "). You can type a model name.";
        }
      },

      modelChanged() {
        const id = this.field("model").value.trim();
        const m = this.models[id] || this.models[id + ":latest"];
        this.modelProblem = "";
        if (!m) { this.modelNote = ""; return; }
        const better = this.suggestedModel ? " Try " + this.suggestedModel + "." : "";
        if (m.can_generate === false) {
          this.modelProblem = id + " is an embedding model (used for search), so it cannot " +
            "write notes." + better;
        } else if (!m.usable) {
          this.modelProblem = id + " can only read " + m.context_window.toLocaleString() +
            " tokens at a time, too few to summarise a meeting." + better;
        }
        this.modelNote = this.modelProblem || (m.context_window
          ? "Reads up to " + m.context_window.toLocaleString() + " tokens at a time." : "");
      },

      options() {
        const form = this.$root;
        const v = (n) => form.elements[n].value.trim();
        const list = (n) => v(n).split(",").map((s) => s.trim()).filter(Boolean);
        const opts = {
          title: v("title"),
          template: v("template"),
          backend: v("backend"),
          cloud_consent: this.consentValue === "true",
          diarize: form.elements.diarize.checked,
          participants: list("participants"),
          tags: list("tags"),
        };
        const put = (key, value) => { if (value !== "") opts[key] = value; };
        put("meeting_date", v("meeting_date"));
        put("meeting_time", v("meeting_time"));
        put("location", v("location"));
        put("model", v("model"));
        put("instructions", v("instructions"));
        for (const key of ["min_speakers", "max_speakers", "batch_size"]) {
          const el = form.elements[key];
          if (el && el.value !== "") opts[key] = Number(el.value);
        }
        for (const key of ["transcription_model", "compute_type"]) {
          const el = form.elements[key];
          if (el && el.value.trim() !== "") opts[key] = el.value.trim();
        }
        return opts;
      },

      submit() {
        if (this.file === null || this.uploading) return;
        if (this.needsConsent && this.consented !== this.backendName) {
          this.$refs.consent.showModal();
          return;
        }
        if (this.modelProblem) {
          this.error = "Choose another model before starting.";
          this.errorHint = this.modelProblem;
          this.field("model").focus();
          return;
        }
        this.error = "";
        this.uploading = true;
        this.progress = 0;
        const body = new FormData();
        body.append("options", JSON.stringify(this.options()));
        body.append("file", this.file, this.file.name);
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/jobs");
        xhr.setRequestHeader("X-CSRF-Token", csrfToken());
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) this.progress = Math.round((e.loaded / e.total) * 100);
        };
        xhr.onload = () => {
          let data = {};
          try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
          if (xhr.status === 201 && data.id) {
            window.location.assign("/jobs/" + data.id);
            return;
          }
          this.fail(data.message || "The upload failed (" + xhr.status + ").", data.hint || "");
        };
        xhr.onerror = () => this.fail("Cannot reach MeetingMaster3.", "Is the server still running?");
        xhr.send(body);
      },
      fail(message, hint) {
        this.uploading = false;
        this.error = message;
        this.errorHint = hint;
      },
    }));

    Alpine.data("speakers", () => ({
      stopAt: null,

      init() {
        const audio = document.getElementById("speaker-audio");
        audio.addEventListener("timeupdate", () => {
          if (this.stopAt !== null && audio.currentTime >= this.stopAt) {
            audio.pause();
            this.stopAt = null;
          }
        });
        audio.addEventListener("error", () => {
          toast("error", "The audio cannot be played.", "It may have been removed by the retention policy.");
        });
      },

      play(evt) {
        const audio = document.getElementById("speaker-audio");
        const start = Number(evt.currentTarget.dataset.start);
        this.stopAt = Number(evt.currentTarget.dataset.end);
        const go = () => { audio.currentTime = start; audio.play(); };
        if (audio.readyState >= 1) go();
        else { audio.addEventListener("loadedmetadata", go, { once: true }); audio.load(); }
      },

      useSuggestion(evt) {
        const box = evt.currentTarget.closest("fieldset");
        box.querySelector('input[name^="name__"]').value = evt.currentTarget.dataset.name;
        box.querySelector('input[name^="person__"]').value = evt.currentTarget.dataset.person;
      },

      nameTyped(evt) {
        const box = evt.target.closest("fieldset");
        const hidden = box.querySelector('input[name^="person__"]');
        const known = Array.from(document.querySelectorAll("#people-list option"));
        const match = known.find((o) => o.value === evt.target.value);
        hidden.value = match ? match.dataset.person : "";
      },
    }));
  });

  document.addEventListener("DOMContentLoaded", setupJobPanel);
})();
