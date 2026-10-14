/* MeetingMaster3 progress widget for long review actions (Phase 15c, R27).
   window.mm3Progress.run(container, {taskUrl, cancelUrl, snapshot, title, csrf, ...}) draws a
   determinate bar with the current step, a ticking elapsed clock and a time-left estimate, moves
   (striped bar, or a sweep before the first figure) so a long run never looks frozen, and polls
   the server for the task. It resolves with the final snapshot ({state: done|failed|cancelled}).
   The server owns the numbers (fraction, remaining); the clock only ticks between polls.
   With prefers-reduced-motion the animation is dropped by CSS; the clock still ticks. */
(function () {
  "use strict";
  const POLL_MS = 1000;
  const TICK_MS = 250;

  function clock(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + sec : m + ":" + sec;
  }

  function timeLeft(seconds) {
    if (seconds < 45) return "less than a minute";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return "about " + minutes + (minutes === 1 ? " minute" : " minutes");
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return "about " + hours + " h" + (rest ? " " + rest + " min" : "");
  }

  function el(tag, props, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children || []) node.append(c);
    return node;
  }

  function stepText(snap) {
    if (snap.step && snap.steps && snap.step_title) {
      return "Section " + snap.step + " of " + snap.steps + ": " + snap.step_title;
    }
    return snap.message || "Starting";
  }

  /* The text for the time-left line, from the last snapshot plus the time since it arrived. */
  function etaText(snap, sinceMs) {
    if (snap.eta === "none" || snap.remaining_s === null) {
      return snap.eta === "overrun" ? "Taking longer than expected, still working" : "Estimating the time left…";
    }
    const left = snap.remaining_s - sinceMs / 1000;
    if (left <= 1) return "Taking longer than expected, still working";
    return (snap.eta === "estimate" ? "Roughly " : "") + timeLeft(left) + " left";
  }

  function run(container, opts) {
    const csrf = opts.csrf || (() => "");
    let snap = opts.snapshot;
    let snapAt = performance.now();
    let stopped = false;
    let timer = null;
    let ticker = null;
    let lastAnnounced = "";
    let milestone = 0;

    const stepLine = el("p", { class: "pw-step", text: stepText(snap) });
    const fill = el("div", { class: "pw-fill" });
    const bar = el("div", {
      class: "pw-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
      "aria-valuenow": "0", "aria-label": opts.title || "Progress",
    }, [fill]);
    const elapsed = el("span", { class: "pw-elapsed" });
    const left = el("span", { class: "pw-left" });
    const times = el("p", { class: "pw-times" }, [elapsed, document.createTextNode(" · "), left]);
    const live = el("p", { class: "sr-only", role: "status", "aria-live": "polite" });
    const note = el("p", { class: "hint", text: opts.note || "You can keep reading the note while this runs." });
    const cancel = el("button", { type: "button", class: "danger", text: opts.cancelLabel || "Cancel" });
    const hide = opts.onHide ? el("button", { type: "button", text: "Hide and keep running" }) : null;
    const row = el("div", { class: "row" }, [cancel].concat(hide ? [hide] : []));
    const root = el("div", { class: "progress-widget", "data-state": "running" },
      [stepLine, bar, times, live, note, row]);
    container.replaceChildren(root);

    function paint() {
      const since = performance.now() - snapAt;
      const pct = Math.round(snap.fraction * 100);
      fill.style.width = (snap.fraction > 0 ? Math.max(pct, 3) : 0) + "%";
      root.classList.toggle("indeterminate", snap.fraction <= 0);
      bar.setAttribute("aria-valuenow", String(pct));
      bar.setAttribute("aria-valuetext", pct + " percent. " + stepText(snap));
      stepLine.textContent = stepText(snap);
      elapsed.textContent = "Elapsed " + clock(snap.elapsed_s + since / 1000);
      left.textContent = etaText(snap, since);
    }

    function announce() {
      const text = stepText(snap);
      const quarter = Math.floor(snap.fraction * 4);
      if (text !== lastAnnounced && quarter > milestone) { // a few times per run, not every tick
        milestone = quarter;
        lastAnnounced = text;
        live.textContent = Math.round(snap.fraction * 100) + " percent. " + text;
      }
    }

    function finish(final) {
      stopped = true;
      clearTimeout(timer);
      clearInterval(ticker);
      root.dataset.state = final.state;
      return final;
    }

    return new Promise((resolve) => {
      async function poll() {
        if (stopped) return;
        try {
          const res = await fetch(opts.taskUrl, { headers: { Accept: "application/json" } });
          if (res.status === 404) {
            resolve(finish(Object.assign({}, snap, { state: "lost" })));
            return;
          }
          if (res.ok) {
            snap = (await res.json()).task;
            snapAt = performance.now();
            paint();
            announce();
            if (snap.state !== "running") { resolve(finish(snap)); return; }
          }
        } catch (err) {
          left.textContent = "Lost contact with MeetingMaster3, retrying…";
        }
        timer = setTimeout(poll, POLL_MS);
      }
      cancel.addEventListener("click", async () => {
        cancel.disabled = true;
        try {
          await fetch(opts.cancelUrl, { method: "POST", headers: { "X-CSRF-Token": csrf() } });
        } catch (err) { /* the next poll reports what happened */ }
        clearTimeout(timer);
        poll();
      });
      if (hide) hide.addEventListener("click", () => opts.onHide());
      paint();
      ticker = setInterval(paint, TICK_MS);
      timer = setTimeout(poll, snap.state === "running" ? POLL_MS : 0);
      root.mm3 = { snapshot: () => snap };
      if (opts.signal) opts.signal.addEventListener("abort", () => resolve(finish(snap)));
    });
  }

  window.mm3Progress = { run, clock, timeLeft, etaText };
})();
