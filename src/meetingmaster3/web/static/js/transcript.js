/* MeetingMaster3 review workspace: audio player, synced transcript, search, splitter.
   Plain JavaScript (no inline script is allowed by the CSP). Exposes window.mm3Player.seek(). */
(function () {
  "use strict";

  const audio = document.getElementById("audio");
  const box = document.getElementById("transcript");
  const panes = document.getElementById("panes");
  if (!panes) return;

  const STEP = 5;
  const segs = box ? Array.from(box.querySelectorAll(".seg")) : [];
  const starts = segs.map((s) => Number(s.dataset.t));
  let current = -1;
  let lastAutoScroll = 0;
  const follow = document.getElementById("tr-follow");

  const clock = (sec) => {
    if (!Number.isFinite(sec) || sec < 0) sec = 0;
    const s = Math.floor(sec % 60), m = Math.floor(sec / 60) % 60, h = Math.floor(sec / 3600);
    const ss = String(s).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + ss : m + ":" + ss;
  };

  /** Index of the segment playing at time t: the last segment starting at or before t. */
  function indexAt(t) {
    let lo = 0, hi = starts.length - 1, found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (starts[mid] <= t) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    return found;
  }

  function highlight(i, scroll) {
    if (i === current) return;
    if (current >= 0 && segs[current]) segs[current].classList.remove("current");
    current = i;
    if (i < 0 || !segs[i]) return;
    segs[i].classList.add("current");
    if (scroll && (!follow || follow.checked)) {
      lastAutoScroll = performance.now();
      segs[i].scrollIntoView({ block: "center", behavior: "auto" });
    }
  }

  function seek(t, play) {
    highlight(indexAt(t + 0.01), false);
    if (follow) follow.checked = true;
    if (!audio) return;
    const go = () => {
      audio.currentTime = Math.max(0, t);
      if (play) audio.play().catch(() => {});
    };
    if (audio.readyState >= 1) go();
    else { audio.addEventListener("loadedmetadata", go, { once: true }); audio.load(); }
  }
  window.mm3Player = { seek };

  // Opened from a search result at a moment (/meetings/<id>#t=<seconds>): show that segment.
  const fromHash = /^#t=(\d+(?:\.\d+)?)$/.exec(window.location.hash);
  if (fromHash && segs.length) {
    const t = Number(fromHash[1]);
    seek(t, false);
    const i = indexAt(t + 0.01);
    if (i >= 0 && segs[i]) segs[i].scrollIntoView({ block: "center" });
  }

  // A manual scroll pauses "follow"; the checkbox turns it back on.
  if (box) {
    box.addEventListener("scroll", () => {
      if (performance.now() - lastAutoScroll > 400 && audio && !audio.paused && follow) {
        follow.checked = false;
      }
    }, { passive: true });
  }
  if (follow) follow.addEventListener("change", () => {
    if (follow.checked && current >= 0) {
      lastAutoScroll = performance.now();
      segs[current].scrollIntoView({ block: "center" });
    }
  });

  // Clicking a word, a segment or a timestamp (in the transcript or the rendered note) seeks.
  document.addEventListener("click", (evt) => {
    const target = evt.target.closest(".transcript [data-t], .ts-link[data-t]");
    if (!target) return;
    evt.preventDefault();
    seek(Number(target.dataset.t), true);
  });

  // -- player controls ------------------------------------------------------------------------
  if (audio) {
    const play = document.getElementById("pl-play");
    const range = document.getElementById("pl-seek");
    const time = document.getElementById("pl-time");
    const speed = document.getElementById("pl-speed");
    const toggle = () => { if (audio.paused) audio.play().catch(() => {}); else audio.pause(); };
    const nudge = (d) => seek(Math.min(Math.max(audio.currentTime + d, 0), audio.duration || 0), !audio.paused);
    const show = () => {
      time.textContent = clock(audio.currentTime) + " / " + clock(audio.duration);
      if (document.activeElement !== range) range.value = String(audio.currentTime);
    };
    play.addEventListener("click", toggle);
    document.getElementById("pl-back").addEventListener("click", () => nudge(-STEP));
    document.getElementById("pl-fwd").addEventListener("click", () => nudge(STEP));
    speed.addEventListener("change", () => { audio.playbackRate = Number(speed.value); });
    range.addEventListener("input", () => { audio.currentTime = Number(range.value); });
    audio.addEventListener("loadedmetadata", () => { range.max = String(audio.duration || 0); show(); });
    audio.addEventListener("play", () => { play.textContent = "❚❚"; play.setAttribute("aria-label", "Pause"); });
    audio.addEventListener("pause", () => { play.textContent = "▶"; play.setAttribute("aria-label", "Play"); });
    audio.addEventListener("timeupdate", () => { show(); highlight(indexAt(audio.currentTime), true); });
    audio.addEventListener("error", () => {
      const player = document.getElementById("player");
      const note = document.createElement("p");
      note.className = "alert info";
      note.textContent = "The recording cannot be played (it may have been removed by the retention policy). The transcript still works.";
      player.replaceChildren(note);
    });

    // Keyboard: Space/K play-pause, J back, L forward; never while typing or in a dialog.
    document.addEventListener("keydown", (evt) => {
      if (evt.ctrlKey || evt.metaKey || evt.altKey || evt.defaultPrevented) return;
      const t = evt.target;
      if (t.closest("input, textarea, select, [contenteditable], dialog")) return;
      const key = evt.key.toLowerCase();
      if (key === " " && t.closest("button, a, summary")) return; // let Space press the control
      if (key === " " || key === "k") { evt.preventDefault(); toggle(); }
      else if (key === "j") { evt.preventDefault(); nudge(-STEP); }
      else if (key === "l") { evt.preventDefault(); nudge(STEP); }
    });
  }

  // -- search ---------------------------------------------------------------------------------
  const search = document.getElementById("tr-search");
  if (search && box) {
    const count = document.getElementById("tr-count");
    let hits = [];
    let pos = -1;
    let timer = null;
    const clear = () => { for (const s of hits) s.classList.remove("hit", "hit-current"); hits = []; pos = -1; };
    const run = () => {
      clear();
      const q = search.value.trim().toLowerCase();
      if (!q) { count.textContent = ""; return; }
      hits = segs.filter((s) => s.textContent.toLowerCase().includes(q));
      for (const s of hits) s.classList.add("hit");
      count.textContent = hits.length === 1 ? "1 match" : hits.length + " matches";
      if (hits.length) go(0);
    };
    const go = (i) => {
      if (!hits.length) return;
      if (pos >= 0) hits[pos].classList.remove("hit-current");
      pos = (i + hits.length) % hits.length;
      hits[pos].classList.add("hit-current");
      if (follow) follow.checked = false;
      hits[pos].scrollIntoView({ block: "center" });
      count.textContent = (pos + 1) + " of " + hits.length;
    };
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 150); });
    search.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter") { evt.preventDefault(); go(evt.shiftKey ? pos - 1 : pos + 1); }
      else if (evt.key === "Escape") { search.value = ""; run(); }
    });
    document.getElementById("tr-next").addEventListener("click", () => go(pos + 1));
    document.getElementById("tr-prev").addEventListener("click", () => go(pos - 1));
  }

  // -- resizable splitter (pointer and keyboard), remembered per browser ----------------------
  const splitter = document.getElementById("splitter");
  if (splitter) {
    const KEY = "mm3.review.split";
    const set = (pct) => {
      pct = Math.min(80, Math.max(20, pct));
      panes.style.setProperty("--left", pct + "%");
      splitter.setAttribute("aria-valuenow", String(Math.round(pct)));
      return pct;
    };
    try { const saved = Number(localStorage.getItem(KEY)); if (saved) set(saved); } catch (e) { /* private mode */ }
    const remember = (pct) => { try { localStorage.setItem(KEY, String(pct)); } catch (e) { /* ignore */ } };
    splitter.addEventListener("pointerdown", (evt) => {
      splitter.setPointerCapture(evt.pointerId);
      const rect = panes.getBoundingClientRect();
      const move = (e) => set(((e.clientX - rect.left) / rect.width) * 100);
      const up = (e) => {
        splitter.removeEventListener("pointermove", move);
        remember(set(((e.clientX - rect.left) / rect.width) * 100));
      };
      splitter.addEventListener("pointermove", move);
      splitter.addEventListener("pointerup", up, { once: true });
    });
    splitter.addEventListener("keydown", (evt) => {
      const now = Number(splitter.getAttribute("aria-valuenow"));
      if (evt.key === "ArrowLeft") { evt.preventDefault(); remember(set(now - 5)); }
      else if (evt.key === "ArrowRight") { evt.preventDefault(); remember(set(now + 5)); }
    });
  }

  // Ctrl/Cmd+click on a [mm:ss] reference inside the editor seeks too.
  document.addEventListener("click", (evt) => {
    const ta = evt.target;
    if (!(evt.ctrlKey || evt.metaKey) || !ta.matches || !ta.matches("textarea.part")) return;
    const at = ta.selectionStart;
    const re = /\[(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)\]/g;
    let m;
    while ((m = re.exec(ta.value)) !== null) {
      if (m.index <= at && at <= m.index + m[0].length) {
        seek(Number(m[1] || 0) * 3600 + Number(m[2]) * 60 + Number(m[3]), true);
        return;
      }
    }
  });
})();
