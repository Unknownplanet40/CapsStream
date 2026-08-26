/* ============================================================
   CapsStream — Vue 3 SPA (No Build Step)
   All components defined inline using Vue.defineComponent
   ============================================================ */

const { createApp, ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } = Vue;
const { createRouter, createWebHashHistory } = VueRouter;

// ─── API Helper ──────────────────────────────────────────────

const _API_CACHE = new Map();

const API = {
  clearCache(pattern) {
    if (!pattern) {
      _API_CACHE.clear();
      return;
    }
    for (const key of _API_CACHE.keys()) {
      if (key.includes(pattern)) _API_CACHE.delete(key);
    }
  },
  async get(url, options = {}) {
    const isCacheable = url.startsWith("/api/media") || url.startsWith("/api/genres") || url.startsWith("/api/favorites") || url.startsWith("/api/collections");
    const useCache = options.cache !== false && (isCacheable || options.cache === true);
    const maxAge = options.maxAge || 60000;
    const now = Date.now();
    const entry = _API_CACHE.get(url);

    if (useCache && entry) {
      // SWR: return cached entry immediately and revalidate in background if older than maxAge / 2
      if (now - entry.timestamp > maxAge / 2) {
        fetch(url)
          .then((r) => (r.ok ? r.json() : null))
          .then((fresh) => {
            if (fresh) _API_CACHE.set(url, { data: fresh, timestamp: Date.now() });
          })
          .catch(() => {});
      }
      return entry.data;
    }

    const r = await fetch(url);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `API error: ${r.status}`);
    }
    const data = await r.json();
    if (useCache) {
      _API_CACHE.set(url, { data, timestamp: now });
    }
    return data;
  },
  async post(url, data) {
    API.clearCache();
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `API error: ${r.status}`);
    }
    return r.json();
  },
  async put(url, data) {
    API.clearCache();
    const r = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `API error: ${r.status}`);
    }
    return r.json();
  },
  async patch(url, data) {
    API.clearCache();
    const r = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `API error: ${r.status}`);
    }
    return r.json();
  },
  async del(url) {
    API.clearCache();
    const r = await fetch(url, { method: "DELETE" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `API error: ${r.status}`);
    }
    return r.json();
  },
};

// ─── Global State ─────────────────────────────────────────────

const store = reactive({
  profile: null,
  toasts: [],
  achievementQueue: [],
  scanRunning: false,
  scanPhase: "",        // "scanning" | "matching" | "complete"
  scanProgress: "",
  scanCount: 0,
  scanTotal: 0,
  scanPercent: 0,
  scanItem: null,       // rich info about the file currently being processed
  scanMatched: 0,
  scanElapsed: 0,
  serverOnline: true,
  updateInfo: null,      // set when an update is available
  pendingScanAfterCacheCleared: false, // triggers auto-scan when returning home after cache clear
  pendingUpdateCheck: false,           // triggers auto-check for updates when Settings opens from the banner
  sleepTimerMinutes: 0,
  sleepTimerEndsAt: null,
  bedtimeActive: false,
  bedtimeReason: 'curfew',
  todayWatchSeconds: 0,
  bedtimeWarned: false,
  dailyLimitWarned: false,
  bedtimeDismissedForToday: false,
  dailyLimitExtended: false,
});

let sleepTimerInterval = null;

function setSleepTimer(minutes) {
  if (sleepTimerInterval) {
    clearInterval(sleepTimerInterval);
    sleepTimerInterval = null;
  }
  if (!minutes || minutes <= 0) {
    store.sleepTimerMinutes = 0;
    store.sleepTimerEndsAt = null;
    addToast("Bedtime timer turned off", "info");
    return;
  }
  store.sleepTimerMinutes = minutes;
  store.sleepTimerEndsAt = Date.now() + minutes * 60 * 1000;
  addToast(`Bedtime timer set for ${minutes} minutes 🌙`, "success");

  sleepTimerInterval = setInterval(() => {
    if (!store.sleepTimerEndsAt) {
      clearInterval(sleepTimerInterval);
      return;
    }
    const remaining = Math.max(0, Math.ceil((store.sleepTimerEndsAt - Date.now()) / 60000));
    store.sleepTimerMinutes = remaining;
    if (Date.now() >= store.sleepTimerEndsAt) {
      clearInterval(sleepTimerInterval);
      sleepTimerInterval = null;
      store.sleepTimerMinutes = 0;
      store.sleepTimerEndsAt = null;
      store.bedtimeActive = true;
      const v = document.querySelector("video");
      if (v) v.pause();
    }
  }, 1000);
}

let isServerOfflineToastActive = false;

async function checkServerHealth() {
  try {
    const res = await fetch("/api/system/info", { method: "GET" });
    if (res.ok) {
      if (store.serverOnline === false) {
        store.serverOnline = true;
        isServerOfflineToastActive = false;
        // Only auto-rescan on reconnect when a profile is logged in
        if (store.profile) {
          startLibraryScan(true);
        }
      } else {
        store.serverOnline = true;
      }
      const info = await res.json().catch(() => null);
      checkRamUsage(info);
    } else {
      handleServerOffline();
    }
  } catch (err) {
    handleServerOffline();
  }
}

// ─── High RAM Usage Alerts ─────────────────────────────────────
// Thresholds on the server's memory-load percentage:
//   ≥85% → warning   ≥95% → critical
// Alerts fire on level escalation and re-remind at most every 10 minutes
// while the condition persists; a recovery notice fires once when it clears.
let ramAlertLevel = "ok";
let ramLastNotifyTs = 0;
const RAM_REMIND_COOLDOWN = 10 * 60 * 1000;

function checkRamUsage(info) {
  const ram = info && info.ram_info;
  const pct = Number(ram && ram.load_pct) || 0;

  let level = "ok";
  if (pct >= 95) level = "critical";
  else if (pct >= 85) level = "warn";

  if (level === "ok") {
    if (ramAlertLevel !== "ok") {
      ramAlertLevel = "ok";
      addToast(`🟢 System memory back to normal (${pct}% in use).`, "success", 5000);
    }
    return;
  }

  const escalated = level !== ramAlertLevel;
  const dueForRemind = Date.now() - ramLastNotifyTs > RAM_REMIND_COOLDOWN;
  if (!escalated && !dueForRemind) return;

  ramAlertLevel = level;
  ramLastNotifyTs = Date.now();

  const usedGb = Number(ram && ram.used_gb) || 0;
  const totalGb = Number(ram && ram.total_gb) || 0;
  const usage = `${usedGb.toFixed(1)} GB / ${totalGb.toFixed(1)} GB used`;

  if (level === "critical") {
    addToast(
      `🔴 System memory almost full — ${pct}% (${usage}). Close other applications to avoid playback stutters or crashes.`,
      "error",
      10000
    );
  } else {
    addToast(
      `🟡 High RAM usage — ${pct}% (${usage}). Playback quality may degrade if it rises further.`,
      "warning",
      7000
    );
  }
}

function handleServerOffline() {
  if (store.serverOnline !== false) {
    store.serverOnline = false;
    if (!isServerOfflineToastActive) {
      isServerOfflineToastActive = true;
      addToast("⚠️ Server Disconnected — CapsStream backend is unreachable or offline.", "error", 6000);
    }
  }
}

setInterval(checkServerHealth, 6000);

function addToast(message, type = "info", duration = 3000) {
  const id = Date.now() + Math.random();
  store.toasts.push({ id, message, type });
  setTimeout(() => {
    store.toasts = store.toasts.filter((t) => t.id !== id);
  }, duration);
}

function playAchievementSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    osc1.type = "sine";
    osc2.type = "triangle";

    osc1.frequency.setValueAtTime(587.33, now);
    osc1.frequency.setValueAtTime(880.00, now + 0.12);

    osc2.frequency.setValueAtTime(1174.66, now + 0.12);

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.18, now + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.65);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.65);
    osc2.stop(now + 0.65);
  } catch (e) {}
}

// ─── Custom Global Confirm Modal System ───────────────────────

const confirmState = reactive({
  show: false,
  title: "Confirmation Required",
  message: "",
  icon: "ph ph-question",
  okText: "Confirm",
  cancelText: "Cancel",
  danger: false,
  resolve: null
});

function customConfirm({ title = "Confirmation Required", message, icon = "ph ph-question", okText = "Confirm", cancelText = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    confirmState.title = title;
    confirmState.message = message;
    confirmState.icon = icon;
    confirmState.okText = okText;
    confirmState.cancelText = cancelText;
    confirmState.danger = danger;
    confirmState.resolve = resolve;
    confirmState.show = true;
  });
}

function handleConfirmOk() {
  confirmState.show = false;
  if (confirmState.resolve) {
    confirmState.resolve(true);
    confirmState.resolve = null;
  }
}

function handleConfirmCancel() {
  confirmState.show = false;
  if (confirmState.resolve) {
    confirmState.resolve(false);
    confirmState.resolve = null;
  }
}

function formatFileSize(bytes) {
  if (!bytes || isNaN(bytes) || bytes <= 0) return '0 MB';
  const tb = bytes / (1024 * 1024 * 1024 * 1024);
  if (tb >= 1.0) return `${tb < 10 ? tb.toFixed(2) : tb.toFixed(1)} TB`;
  const gb = bytes / (1024 * 1024 * 1024);
  if (gb >= 1.0) return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
}

// ─── Custom Global Fix Match Modal System ─────────────────────

const fixMatchState = reactive({
  show: false,
  target: null,
  onMatched: null
});

function openGlobalFixMatch(target, onMatched) {
  fixMatchState.target = target;
  fixMatchState.onMatched = onMatched || null;
  fixMatchState.show = true;
}

// ─── Multi-Theme Preset System ─────────────────────────────────

const THEME_PRESETS = [
  {
    id: "crimson",
    name: "Crimson Cinema",
    desc: "Obsidian dark mode with bold Netflix-crimson red accents and warm golden highlights.",
    accent: "#e50914",
    secondary: "#f5c518",
    bg: "#050508",
    border: "rgba(229, 9, 20, 0.35)",
    icon: "ph-film-slate",
  },
  {
    id: "oled",
    name: "OLED Pure Black",
    desc: "100% true pitch black canvas with sharp silver luminescence for maximum contrast and OLED displays.",
    accent: "#ffffff",
    secondary: "#94a3b8",
    bg: "#000000",
    border: "rgba(255, 255, 255, 0.25)",
    icon: "ph-moon",
  },
  {
    id: "sapphire",
    name: "Royal Sapphire",
    desc: "Deep Disney+ cosmic space navy paired with rich royal sapphire blue and icy cyan highlights.",
    accent: "#2563eb",
    secondary: "#38bdf8",
    bg: "#060a17",
    border: "rgba(37, 99, 235, 0.35)",
    icon: "ph-planet",
  },
  {
    id: "amethyst",
    name: "Velvet Amethyst",
    desc: "Deep HBO royal obsidian violet with luminous amethyst purple accents and radiant lavender glow.",
    accent: "#8b5cf6",
    secondary: "#c084fc",
    bg: "#090514",
    border: "rgba(139, 92, 246, 0.35)",
    icon: "ph-sparkle",
  },
  {
    id: "azure",
    name: "Azure Prime",
    desc: "Midnight cerulean canvas with crisp electric streaming cyan-blue accents and icy highlights.",
    accent: "#0284c7",
    secondary: "#38bdf8",
    bg: "#050d14",
    border: "rgba(2, 132, 199, 0.35)",
    icon: "ph-television-simple",
  },
  {
    id: "coral",
    name: "Sunset Coral",
    desc: "Smoky cinematic dusk obsidian with warm radiant coral rose accents and golden peach highlights.",
    accent: "#f43f5e",
    secondary: "#fda4af",
    bg: "#0e080b",
    border: "rgba(244, 63, 94, 0.35)",
    icon: "ph-sun-horizon",
  },
];

function applyTheme(themeKey, persist = false) {
  const validTheme = THEME_PRESETS.some((t) => t.id === themeKey) ? themeKey : "crimson";
  document.documentElement.setAttribute("data-theme", validTheme);
  document.body.setAttribute("data-theme", validTheme);
  try {
    localStorage.setItem("capsstream_theme", validTheme);
  } catch (e) {}

  if (persist && store.profile?.id) {
    store.profile.theme = validTheme;
    API.put(`/api/profiles/${store.profile.id}`, {
      name: store.profile.name,
      avatar: store.profile.avatar,
      color: store.profile.color,
      is_kids: store.profile.is_kids,
      theme: validTheme,
      daily_limit_minutes: store.profile.daily_limit_minutes,
      bedtime_curfew: store.profile.bedtime_curfew,
    }).catch((err) => console.warn("[Theme] Failed to persist profile theme:", err));
  }
}

// ─── Custom Global Context Menu System ────────────────────────

const contextMenuState = reactive({
  show: false,
  x: 0,
  y: 0,
  item: null,
  isFavorite: false,
});

function openGlobalContextMenu(e, item) {
  if (!item) return;
  if (e && typeof e.preventDefault === "function") e.preventDefault();
  if (e && typeof e.stopPropagation === "function") e.stopPropagation();

  const menuWidth = 270;
  const menuHeight = 360;
  let clickX = (e && e.clientX) || 100;
  let clickY = (e && e.clientY) || 100;

  // Anchor to the 3-dot button if triggered from a card or the button itself
  let anchorEl = null;
  if (e && e.currentTarget && typeof e.currentTarget.querySelector === "function") {
    if (e.currentTarget.classList?.contains("card-menu-btn")) {
      anchorEl = e.currentTarget;
    } else {
      anchorEl = e.currentTarget.querySelector(".card-menu-btn") || e.currentTarget;
    }
  } else if (e && e.target && typeof e.target.closest === "function") {
    const card = e.target.closest(".media-card");
    if (card) {
      anchorEl = card.querySelector(".card-menu-btn") || card;
    }
  }

  if (anchorEl && typeof anchorEl.getBoundingClientRect === "function") {
    const rect = anchorEl.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      clickX = rect.left;
      clickY = rect.bottom + 4;
    }
  }

  const maxX = window.innerWidth - menuWidth - 16;
  const maxY = window.innerHeight - menuHeight - 16;

  contextMenuState.x = Math.max(16, Math.min(clickX, maxX));
  contextMenuState.y = Math.max(16, Math.min(clickY, maxY));
  contextMenuState.item = item;
  contextMenuState.isFavorite = !!item.is_favorite;
  contextMenuState.show = true;
}

function closeGlobalContextMenu() {
  contextMenuState.show = false;
  contextMenuState.item = null;
}

// ─── Global Collection Picker System ──────────────────────────

const collectionPickerState = reactive({
  show: false,
  item: null,
  collections: [],
  inlineName: "",
});

function openGlobalCollectionPicker(item) {
  if (!item) return;
  collectionPickerState.item = item;
  collectionPickerState.show = true;
  API.get("/api/collections").then((res) => {
    collectionPickerState.collections = res || [];
  }).catch(() => {});
}

// ─── Global Trailer Modal System ──────────────────────────────

const globalTrailerState = reactive({
  show: false,
  url: null,
  title: ""
});

async function openGlobalTrailer(item) {
  if (!item) return;
  const mediaId = item.id || item.tmdb_id;
  if (!mediaId) return;
  try {
    const res = await API.get(`/api/media/${mediaId}/trailer`);
    if (res && res.embed_url) {
      unlockAchievement("trailer_buff");
      globalTrailerState.url = res.embed_url;
      globalTrailerState.title = `${item.title} — ${res.title || 'Official Trailer'}`;
      globalTrailerState.show = true;
    } else {
      addToast("No trailer found for this title", "info");
    }
  } catch (e) {
    addToast("No trailer available for this title", "info");
  }
}

function triggerAchievementUnlock(ach) {
  if (!ach) return;
  playAchievementSound();
  const item = {
    id: Date.now() + Math.random(),
    icon: ach.icon || "🏆",
    title: ach.title || "Achievement Unlocked!",
    description: ach.description || "You earned a new trophy in your Trophy Case!",
    rarity: ach.rarity || "Gold",
    category: ach.category || "General"
  };
  store.achievementQueue.push(item);
  setTimeout(() => {
    store.achievementQueue = store.achievementQueue.filter((a) => a.id !== item.id);
  }, 4800);
}

// ─── Kids Mode Content Filter ─────────────────────────────────
// Secondary safety layer — the backend (backend/kids_filter.py) is the
// primary enforcement point and filters every media endpoint server-side.

const KIDS_SAFE_GENRES = [
  "animation", "family", "kids", "children"
];

const KIDS_BLOCKED_GENRES = [
  "horror", "thriller", "crime", "war", "romance", "mystery"
];

// Action/Drama only tolerated alongside a core safe genre
const KIDS_SOFT_GENRES = ["action", "drama"];
const KIDS_NEUTRAL_GENRES = [
  "adventure", "comedy", "fantasy", "music", "musical", "science fiction",
  "sci-fi", "sport", "sports", "history", "western"
];

const KID_SAFE_RATINGS = ["g", "pg", "tv-y", "tv-y7", "tv-g", "tv-pg"];
const KID_BLOCKED_RATINGS = ["pg-13", "tv-14", "r", "nc-17", "tv-ma", "nr", "unrated"];

const KID_KEYWORD_BLOCKLIST = [
  /\bsex\b/i, /\bsexual\w*/i, /\bsexuality\b/i, /\bsexy\b/i,
  /\bporn\w*/i, /\berotic\w*/i, /\bnude\b/i, /\bnudity\b/i, /\bnaked\b/i,
  /\bintercourse\b/i, /\bfornicat\w*/i, /\bprostitut\w*/i,
  /\bpuberty\b/i, /\bcontracept\w*/i, /\babortion\w*/i,
  /\bmasturbat\w*/i, /\borgasm\w*/i, /\bfetish\w*/i, /\bbdsm\b/i,
  /\bkink\w*/i, /\bsensual\w*/i, /\bkamasutra\b/i,
  /\bqueer sex\b/i, /\bsex\s*ed(?:ucation)?\b/i, /\bbirds\s+and\s+bees\b/i,
  /\bhuman\s+reproduction\b/i, /\breproductive\s+(?:system|organs|health)\b/i,
  /\bhentai\b/i, /\becchi\b/i, /\byaoi\b/i, /\byuri\b/i,
  /\bstriptease\b/i, /\bstripper\b/i, /\bthreesome\b/i, /\borgy\b/i
];

const KID_DOC_SAFE_RE = /\b(animal\w*|wildlife|nature|ocean\w*|sea |underwater|shark|whale|dolphin|dinosaur\w*|space|planet\w*|solar system|universe|weather|volcano\w*|jungle|rainforest|penguin\w*|polar bear\w*|lion\w*|elephant\w*|insect\w*|bug\b|bugs\b|reptile\w*|bird\w*|forest\w*|farm\b|science|experiment\w*|robot\w*)\b/i;

function _kidsGenreSet(item) {
  const set = new Set(
    (item.genres || "").split(",").map(g => g.trim().toLowerCase()).filter(Boolean)
  );
  if (item.type === "anime") set.add("animation");
  return set;
}

function isKidSafeItem(item) {
  if (!item) return false;
  const genres = _kidsGenreSet(item);
  const hasCoreSafe = KIDS_SAFE_GENRES.some((g) => genres.has(g));
  const hardBlocked = [...genres].filter((g) => KIDS_BLOCKED_GENRES.includes(g));
  const softBlocked = [...genres].filter((g) => KIDS_SOFT_GENRES.includes(g));
  const known = new Set([...KIDS_SAFE_GENRES, ...KIDS_BLOCKED_GENRES, ...KIDS_SOFT_GENRES, ...KIDS_NEUTRAL_GENRES]);
  const unknown = [...genres].filter((g) => !known.has(g));

  if (hardBlocked.length) return false;
  if (softBlocked.length && !hasCoreSafe) return false;
  if (!hasCoreSafe) return false;

  // Documentary-only titles must be clearly child-friendly nature/science
  if (genres.size === 1 && genres.has("documentary")) {
    const text = `${item.title || ""} ${item.overview || ""} ${item.tagline || ""}`;
    if (!KID_DOC_SAFE_RE.test(text)) return false;
  }

  // Keyword denylist over title/tagline/overview
  const text = `${item.title || ""} ${item.original_title || ""} ${item.ep_title || ""} ${item.tagline || ""} ${item.overview || ""}`;
  if (KID_KEYWORD_BLOCKLIST.some((rx) => rx.test(text))) return false;

  // Rating gate when certification data exists
  const cert = (item.certification || "").trim().toLowerCase();
  if (cert) {
    if (!KID_SAFE_RATINGS.includes(cert)) return false;
  } else if (softBlocked.length || unknown.length) {
    // Missing rating: require pure kid-core genres
    return false;
  }

  return true;
}

function kidsFilter(items) {
  if (!items || !Array.isArray(items)) return [];
  if (!store.profile?.is_kids) return items;
  return items.filter(item => isKidSafeItem(item));
}

let scanPollTimer = null;
let sessionScanStarted = false;

function applyScanStatus(status) {
  store.scanRunning = !!status.running;
  store.scanPhase = status.phase || "";
  store.scanProgress = status.progress || "";
  store.scanCount = status.count || 0;
  store.scanTotal = status.total || 0;
  store.scanPercent = status.percent || 0;
  store.scanItem = status.current_item || null;
  store.scanMatched = status.matched || 0;
  store.scanElapsed = status.elapsed || 0;
}

// Starts the library scan at most once per session (unless forced).
// Used after profile login — never before. Respects the user's
// "Scan Library on Startup" setting unless forced (manual scan buttons).
async function startLibraryScan(force = false) {
  if (!store.profile && !force) return false;
  if (!force && (sessionScanStarted || store.scanRunning)) return false;
  if (!force) {
    try {
      const cfg = await API.get("/api/settings");
      if (cfg && cfg.library && cfg.library.scan_on_startup === false) {
        sessionScanStarted = true; // don't retry later in the session
        return false;
      }
    } catch (e) {}
  }
  sessionScanStarted = true;
  try {
    await API.post("/api/scan", {});
    store.scanRunning = true;
    pollScanStatus();
    return true;
  } catch (e) {
    if (e.message && e.message.includes("409")) {
      // Scan already running elsewhere — just follow its status
      store.scanRunning = true;
      pollScanStatus();
      return true;
    }
    sessionScanStarted = false;
    return false;
  }
}

async function pollScanStatus() {
  clearInterval(scanPollTimer);
  scanPollTimer = setInterval(async () => {
    try {
      const status = await API.get("/api/scan/status");
      applyScanStatus(status);
      if (!status.running) {
        clearInterval(scanPollTimer);
        // New-episode notifications — surface shows that gained episodes
        const ne = status.new_episodes || [];
        for (let i = 0; i < Math.min(ne.length, 3); i++) {
          const n = ne[i];
          addToast(`📺 ${n.added} new episode${n.added > 1 ? "s" : ""} of ${n.title} added`, "info", 6000);
        }
        if (ne.length > 3) {
          addToast(`📺 …and ${ne.reduce((s, n) => s + n.added, 0) - ne.slice(0, 3).reduce((s, n) => s + n.added, 0)} more new episodes across other shows`, "info", 6000);
        }
      }
    } catch (e) {
      clearInterval(scanPollTimer);
      store.scanRunning = false;
    }
  }, 1500);
}

// Module-level achievement unlock — toasts on unlock. Used by UI actions
// outside the player (search, filters, scans, IMDb links, trailers).
function unlockAchievement(achievementId) {
  API.post("/api/achievements/unlock", { achievement_id: achievementId })
    .then((res) => {
      if (res && res.unlocked) {
        if (store.profile?.is_kids) {
          addToast(`🌟 Kids Badge Unlocked: ${res.unlocked.icon} ${res.unlocked.title}! 🎉`, "success");
        } else {
          addToast(`🏆 Achievement Unlocked: ${res.unlocked.icon} ${res.unlocked.title}!`, "success");
        }
      }
    })
    .catch(() => {});
}

// Player-feature tracking for the "Player Grandmaster" achievement —
// unlocks once subtitles, audio, speed, AND quality have all been used.
function trackPlayerFeature(feature) {
  try {
    const used = new Set(JSON.parse(localStorage.getItem("cs_player_features") || "[]"));
    used.add(feature);
    localStorage.setItem("cs_player_features", JSON.stringify([...used]));
    if (["subs", "audio", "speed", "quality"].every((f) => used.has(f))) {
      unlockAchievement("player_god");
    }
  } catch (e) {}
}

function imgUrl(path, size = "original") {
  if (!path) return null;
  if (path.startsWith("http")) {
    if (path.includes("image.tmdb.org/t/p/")) {
      return path.replace(/\/t\/p\/w(185|300)/, `/t/p/${size === "poster" ? "w500" : "original"}`);
    }
    return path;
  }
  if (path.startsWith("/")) {
    const tmdbSize = size === "poster" ? "w500" : "original";
    return `https://image.tmdb.org/t/p/${tmdbSize}${path}`;
  }
  if (path.startsWith("images/")) return `/metadata/${path}`;
  if (!path.startsWith("metadata/")) return `/metadata/images/${path}`;
  return `/${path}`;
}

// Fallback: if a full-res TMDB image fails to load, retry once at w500.
// (capture phase required — image error events do not bubble)
document.addEventListener(
  "error",
  (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || img.dataset.sizeFallback) return;
    const src = img.currentSrc || img.src || "";
    if (!src.includes("/t/p/original")) return;
    img.dataset.sizeFallback = "1";
    img.src = src.replace("/t/p/original", "/t/p/w500");
  },
  true
);

function formatRating(r) {
  return r ? r.toFixed(1) : "—";
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatGenres(genresStr, max = 3) {
  if (!genresStr) return "";
  const list = genresStr.split(",").map(s => s.trim()).filter(Boolean);
  return list.slice(0, max).join(" • ");
}

function getCodecInfo(path) {
  if (!path) return { hasWarning: false, tags: [], note: "" };
  const p = path.toLowerCase();
  const tags = [];

  if (p.includes("x265") || p.includes("hevc") || p.includes("h265") || p.includes("h.265")) {
    tags.push("HEVC / x265");
  }
  if (p.includes("10bit") || p.includes("10-bit") || p.includes("10 bit")) {
    tags.push("10-Bit Color");
  }
  if (p.includes("dts") || p.includes("atmos") || p.includes("truehd")) {
    tags.push("DTS / Atmos Audio");
  }
  if (p.includes("av1")) {
    tags.push("AV1 Codec");
  }

  const hasWarning = tags.length > 0;
  const note = hasWarning
    ? "This media file uses advanced video/audio encoding. Direct browser HTML5 playback requires hardware decoding support (recommended browser: Microsoft Edge or Safari)."
    : "";

  return { hasWarning, tags, note };
}

function getPosDur(item) {
  if (!item) return { pos: 0, dur: 0 };
  const pos = Number(item.position !== undefined && item.position !== null ? item.position : item.progress?.position || 0);
  let dur = Number(item.duration !== undefined && item.duration !== null ? item.duration : item.progress?.duration || 0);
  // If duration is 0/missing but position exists, estimate duration (45m for TV, 2h for movies) so progress bar & badge display
  if (!dur && pos > 0) {
    dur = item.type === "movie" ? 7200 : 2700;
  }
  return { pos, dur };
}

function calcProgressPercent(item) {
  const { pos, dur } = getPosDur(item);
  if (!dur || !pos) return 0;
  return Math.min(100, Math.round((pos / dur) * 100));
}

function calcTimeLeft(item) {
  const { pos, dur } = getPosDur(item);
  if (!dur || !pos || pos >= dur) return "";
  const remaining = dur - pos;
  const m = Math.ceil(remaining / 60);
  if (m < 60) return `${m}m left`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return remM > 0 ? `${h}h ${remM}m left` : `${h}h left`;
}

// ─── Media Card Component ─────────────────────────────────────

const MediaCard = {
  props: ["item", "media", "showBadge", "isContinue"],
  emits: ["click", "remove-continue"],
  template: `
    <div class="media-card"
         :class="{ 'continue-card': isContinue, 'is-unmounted': cardItem.is_mounted === false }"
         @mouseenter="showTooltip = true"
         @mouseleave="showTooltip = false"
         @click="$emit('click', cardItem)"
         @contextmenu.prevent="openCardMenu($event)"
         :id="'card-' + (cardItem.id || 'card')">

      <div v-if="cardItem.is_mounted === false && showTooltip" class="unmounted-tooltip">
        <i class="ph ph-warning" style="margin-right:4px;color:#ffb703"></i> Source drive not mounted. Please connect drive to watch this title.
      </div>

      <div class="card-inner">
        <img
          v-if="posterSrc"
          :src="posterSrc"
          :alt="cardItem.title"
          class="card-poster"
          loading="lazy"
          decoding="async"
          @error="handleImgError"
        >
        <div v-else class="card-poster-placeholder">
          <span class="placeholder-icon">🎬</span>
          <span class="placeholder-title">{{ cardItem.title }}</span>
        </div>

        <div v-if="cardItem.is_mounted === false" class="unmounted-badge">
          <i class="ph ph-hard-drive"></i> Unmounted
        </div>

        <span v-if="showBadge !== false && cardItem.is_mounted !== false && cardItem.type !== 'anime'" class="card-badge" :class="cardItem.type">
          {{ cardItem.type === 'series' ? '📺 Series' : '🎬 Movie' }}
        </span>

        <span v-if="isContinue && calcTimeLeft(cardItem)" class="card-badge" style="right:var(--space-sm);left:auto;background:rgba(10,10,15,0.85);border:1px solid var(--border-strong)">
          {{ calcTimeLeft(cardItem) }}
        </span>

        <!-- 3-Dots Context Menu Button -->
        <button
          class="card-menu-btn"
          @click.stop="openCardMenu($event)"
          title="More options"
          :id="'menu-btn-' + (cardItem.id || 'card')"
        >
          <i class="ph-bold ph-dots-three-vertical"></i>
        </button>

        <button v-if="isContinue"
                class="card-remove-btn"
                @click.stop="$emit('remove-continue', cardItem)"
                title="Remove from Continue Watching"
                :id="'remove-btn-' + (cardItem.id || '')">
          <i class="ph ph-x"></i>
        </button>

        <div v-if="calcProgressPercent(cardItem) > 0" class="card-progress">
          <div class="card-progress-fill" :style="{ width: calcProgressPercent(cardItem) + '%' }"></div>
        </div>

        <div class="card-overlay">
          <div class="card-play-btn">
            <i class="ph-fill ph-play" style="color:white;font-size:1rem;margin-left:2px"></i>
          </div>
          <div class="card-title">{{ cardItem.title }}</div>
          <div v-if="isContinue && (cardItem.season || cardItem.ep_title)" class="card-meta" style="color:var(--text-secondary);font-weight:600">
            <span v-if="cardItem.season">S{{ cardItem.season.toString().padStart(2,'0') }}E{{ (cardItem.episode||'').toString().padStart(2,'0') }}</span>
            <span v-if="cardItem.ep_title"> — {{ cardItem.ep_title }}</span>
          </div>
          <div v-else class="card-meta">
            <span v-if="cardItem.year">{{ cardItem.year }}</span>
            <span v-if="cardItem.rating" class="card-rating">
              ⭐ {{ formatRating(cardItem.rating) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  `,
  setup(props) {
    const showTooltip = ref(false);
    const imgError = ref(false);
    const cardItem = computed(() => props.item || props.media || {});

    const posterSrc = computed(() => {
      if (imgError.value) return null;
      const item = cardItem.value;
      if (props.isContinue && item.backdrop_path) return imgUrl(item.backdrop_path);
      if (item.poster_path) return imgUrl(item.poster_path);
      if (item.backdrop_path) return imgUrl(item.backdrop_path);
      if (item.still_path) return imgUrl(item.still_path);
      return null;
    });

    function handleImgError() {
      imgError.value = true;
    }

    function openCardMenu(e) {
      openGlobalContextMenu(e, cardItem.value);
    }

    return { cardItem, posterSrc, handleImgError, openCardMenu, imgUrl, formatRating, calcProgressPercent, calcTimeLeft, showTooltip };
  },
};

// ─── Content Row Component ────────────────────────────────────

const ContentRow = {
  props: ["row"],
  emits: ["card-click", "remove-continue"],
  components: { MediaCard },
  template: `
    <div class="content-row">
      <div class="row-header">
        <div class="row-title">
          {{ row.title }}
          <span class="row-arrow">›</span>
        </div>
        <div class="row-header-controls">
          <button class="row-control-btn" :disabled="!canScrollLeft" @click="scrollLeft" title="Scroll Left" id="row-prev-btn">
            <i class="ph ph-caret-left"></i>
          </button>
          <button class="row-control-btn" :disabled="!canScrollRight" @click="scrollRight" title="Scroll Right" id="row-next-btn">
            <i class="ph ph-caret-right"></i>
          </button>
        </div>
      </div>

      <div class="row-scroller-wrapper">
        <div class="cards-scroller" ref="scrollerRef" @scroll="checkScroll">
          <media-card
            v-for="item in (row?.items || [])"
            :key="item.id || item.tmdb_id"
            :item="item"
            :is-continue="row?.type === 'continue'"
            @click="$emit('card-click', item, row)"
            @remove-continue="$emit('remove-continue', item)"
          />
        </div>
      </div>
    </div>
  `,
  setup() {
    const scrollerRef = ref(null);
    const canScrollLeft = ref(false);
    const canScrollRight = ref(true);

    function checkScroll() {
      if (!scrollerRef.value) return;
      const el = scrollerRef.value;
      canScrollLeft.value = el.scrollLeft > 10;
      canScrollRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 10;
    }

    function scrollLeft() {
      if (!scrollerRef.value) return;
      scrollerRef.value.scrollBy({ left: -600, behavior: "smooth" });
      setTimeout(checkScroll, 350);
    }

    function scrollRight() {
      if (!scrollerRef.value) return;
      scrollerRef.value.scrollBy({ left: 600, behavior: "smooth" });
      setTimeout(checkScroll, 350);
    }

    onMounted(() => {
      nextTick(() => {
        checkScroll();
      });
    });

    return { scrollerRef, canScrollLeft, canScrollRight, checkScroll, scrollLeft, scrollRight };
  },
};

const TrailerModal = {
  props: ["url", "title"],
  emits: ["close"],
  setup() {
    onMounted(async () => {
      try {
        const res = await API.post("/api/achievements/unlock", { achievement_id: "trailer_buff" });
        if (res && res.unlocked) {
          addToast(`🏆 Achievement Unlocked: ${res.unlocked.icon} ${res.unlocked.title}!`, "success");
        }
      } catch (e) {}
    });
  },
  template: `
    <div class="modal-backdrop" @click.self="$emit('close')" style="z-index:9999">
      <div class="modal-card" style="max-width:880px;width:92%;padding:0;overflow:hidden;background:#0d0e15;border:1px solid rgba(255,255,255,0.15);box-shadow:0 20px 60px rgba(0,0,0,0.8)">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:rgba(255,255,255,0.06);border-bottom:1px solid rgba(255,255,255,0.1)">
          <div style="font-weight:700;font-size:1.05rem;display:flex;align-items:center;gap:8px;color:#fff">
            <i class="ph ph-film-strip" style="color:var(--accent);font-size:1.2rem"></i>
            <span>{{ title || 'Official Trailer' }}</span>
          </div>
          <button class="btn btn-ghost btn-sm" @click="$emit('close')" style="padding:4px 8px;font-size:1.2rem;color:var(--text-secondary)">
            ✕
          </button>
        </div>
        <div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;background:#000">
          <iframe
            v-if="url"
            :src="url"
            style="position:absolute;top:0;left:0;width:100%;height:100%;border:0"
            allow="autoplay; encrypted-media; picture-in-picture"
            allowfullscreen
          ></iframe>
        </div>
      </div>
    </div>
  `
};

// ─── Hero Banner Component ────────────────────────────────────

const HeroBanner = {
  props: ["items"],
  emits: ["play", "detail", "trailer"],
  template: `
    <div class="hero" v-if="current">
      <div class="hero-backdrop-container">
        <transition name="banner-slide">
          <div :key="currentIdx" class="hero-backdrop">
            <img
              v-if="current.backdrop_path"
              :src="imgUrl(current.backdrop_path)"
              class="hero-backdrop-img"
              :alt="current.title"
              decoding="async"
              @error="e => e.target.style.display='none'"
            >
          </div>
        </transition>
      </div>

      <div class="hero-gradient"></div>

      <div class="hero-content">
        <div class="hero-badge">
          {{ current.type === 'anime' ? '🎌 Anime' : current.type === 'series' ? '📺 Series' : '🎬 Movie' }}
        </div>
        <div class="hero-title-container">
          <img v-if="current.logo_path" :src="imgUrl(current.logo_path)" :alt="current.title" class="hero-logo-img" />
          <h1 v-else class="hero-title">{{ current.title }}</h1>
        </div>
        <div class="hero-meta">
          <span v-if="current.year">{{ current.year }}</span>
          <span v-if="current.rating" class="hero-rating">⭐ {{ formatRating(current.rating) }}</span>
          <span v-if="current.genres">{{ current.genres.split(',').slice(0,3).join(' · ') }}</span>
        </div>
        <p class="hero-overview">{{ current.overview }}</p>
        <div class="hero-actions">
          <button class="btn btn-primary btn-lg" @click="$emit('play', current)" id="hero-play-btn">
            <span>Play Now</span>
            <div class="btn-icon-wrapper">
              <i class="ph-fill ph-play" style="font-size:0.9rem"></i>
            </div>
          </button>
          <button v-if="!store.profile?.is_kids" class="btn btn-secondary btn-lg" @click="$emit('trailer', current)" id="hero-trailer-btn" title="Trailer">
            <i class="ph ph-film-strip" style="font-size:1.15rem"></i>
          </button>
          <button class="btn btn-secondary btn-lg" @click="$emit('detail', current)" id="hero-info-btn" title="More Info">
            <i class="ph ph-info" style="font-size:1.15rem"></i>
          </button>
        </div>
      </div>
      <div class="hero-indicators" v-if="items && items.length > 1">
        <div
          v-for="(item, i) in (items || []).slice(0, 6)"
          :key="i"
          class="hero-indicator"
          :class="{ active: i === currentIdx }"
          @click="currentIdx = i"
        ></div>
      </div>
    </div>
  `,
  setup(props) {
    const currentIdx = ref(0);
    const current = computed(() => (props.items && props.items.length) ? props.items[currentIdx.value] : null);
    let timer = null;

    onMounted(() => {
      timer = setInterval(() => {
        if (props.items && props.items.length > 1) {
          currentIdx.value = (currentIdx.value + 1) % Math.min(props.items.length, 6);
        }
      }, 7000);
    });

    onUnmounted(() => clearInterval(timer));

    return { currentIdx, current, imgUrl, formatRating, store };
  },
};

// ─── Home Page ────────────────────────────────────────────────

const HomePage = {
  components: { HeroBanner, ContentRow, MediaCard, TrailerModal },
  template: `
    <div>
      <trailer-modal
        v-if="trailerModalUrl"
        :url="trailerModalUrl"
        :title="trailerModalTitle"
        @close="trailerModalUrl = null"
      />

      <hero-banner
        v-if="heroItems && heroItems.length"
        :items="heroItems"
        @play="handlePlay"
        @detail="handleDetail"
        @trailer="handleTrailer"
      />

      <!-- Kids Mode active indicator -->
      <div v-if="store.profile?.is_kids" class="kids-mode-banner" id="kids-mode-banner">
        <i class="ph ph-shield-check"></i>
        <span>🧒 Kids Mode is on — only kid-friendly titles are shown</span>
      </div>

      <!-- Kids Category Bubbles Tray -->
      <div v-if="store.profile?.is_kids && !loading && kidsItemCount > 0" class="kids-category-bubbles">
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'all' }" @click="selectCategory('all')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #ff7675, #d63031)">🌟</div>
          <span class="kids-bubble-label">All Fun</span>
        </div>
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'cartoons' }" @click="selectCategory('cartoons')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #74b9ff, #0984e3)">🎨</div>
          <span class="kids-bubble-label">Cartoons & Anime</span>
        </div>
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'adventures' }" @click="selectCategory('adventures')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #55efc4, #00b894)">🚀</div>
          <span class="kids-bubble-label">Adventures</span>
        </div>
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'magic' }" @click="selectCategory('magic')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #a29bfe, #6c5ce7)">🪄</div>
          <span class="kids-bubble-label">Magic & Fantasy</span>
        </div>
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'comedy' }" @click="selectCategory('comedy')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #ffeaa7, #fdcb6e)">😄</div>
          <span class="kids-bubble-label">Funny Laughs</span>
        </div>
        <div class="kids-bubble-item" :class="{ active: selectedCategory === 'family' }" @click="selectCategory('family')">
          <div class="kids-bubble-icon" style="background: linear-gradient(135deg, #fd79a8, #e84393)">🦁</div>
          <span class="kids-bubble-label">Animals & Family</span>
        </div>
      </div>

      <div class="home-content">
        <!-- Structured loading skeleton — mirrors the real page layout -->
        <div v-if="loading" class="home-skeleton" aria-hidden="true">
          <!-- Hero skeleton -->
          <div class="sk-hero">
            <div class="sk-hero-backdrop skeleton"></div>
            <div class="sk-hero-content">
              <div class="sk-line skeleton" style="width:70px;height:20px;border-radius:6px"></div>
              <div class="sk-line skeleton" style="width:42%;height:34px"></div>
              <div class="sk-line skeleton" style="width:56%;height:13px"></div>
              <div class="sk-line skeleton" style="width:47%;height:13px"></div>
              <div class="sk-hero-actions">
                <div class="sk-line skeleton" style="width:118px;height:42px;border-radius:8px"></div>
                <div class="sk-line skeleton" style="width:118px;height:42px;border-radius:8px"></div>
              </div>
            </div>
          </div>

          <!-- Content-row skeletons -->
          <div v-for="r in 3" :key="r" class="sk-row">
            <div class="sk-line skeleton sk-row-title"></div>
            <div class="cards-scroller">
              <div
                v-for="i in 8"
                :key="i"
                class="sk-card"
                :style="{ '--sk-delay': (0.12 + i * 0.09) + 's' }"
              >
                <div class="sk-poster skeleton"></div>
                <div class="sk-line skeleton" style="width:86%;height:11px"></div>
                <div class="sk-line skeleton" style="width:54%;height:11px"></div>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="!loading && (!rows || rows.length === 0)" class="empty-state" style="padding-top: calc(var(--nav-height) + 2rem); text-align: center; max-width: 600px; margin: 0 auto;">
          <div class="empty-icon" style="font-size: 3.5rem; margin-bottom: 1rem;">🎬</div>
          <div class="empty-title" style="font-size: 1.5rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.5rem;">
            No Media Found in Library
          </div>
          <div class="empty-subtitle" style="color: var(--text-secondary); line-height: 1.6; margin-bottom: 1.75rem;">
            Welcome to CapsStream! No media sources configured yet — open <strong>Settings → Media Scanner Paths</strong> and add the folders where your movies, series, or anime live.
          </div>
          <div style="display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
            <button class="btn btn-primary" @click="triggerScanFromHome" :disabled="store.scanRunning" id="home-empty-scan-btn">
              <i class="ph ph-arrows-clockwise" :style="{ animation: store.scanRunning ? 'spin 1s linear infinite' : 'none' }" style="margin-right:6px"></i>
              {{ store.scanRunning ? 'Scanning Library...' : 'Scan Library' }}
            </button>
            <button v-if="!store.profile?.is_kids" class="btn btn-secondary" @click="router.push('/settings')" id="home-empty-settings-btn">
              <i class="ph ph-gear" style="margin-right:6px"></i> Settings & Media Paths
            </button>
          </div>
        </div>

        <template v-else>
          <content-row
            v-for="row in (rows || [])"
            :key="row.title || row.id"
            :row="row"
            @card-click="handleCardClick"
            @remove-continue="handleRemoveContinue"
          />
        </template>
      </div>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const rows = ref([]);
    const loading = ref(true);
    const selectedCategory = ref("all");
    const kidsAllRows = ref([]);
    const kidsItemCount = ref(0);

    const heroItems = computed(() => {
      if (!rows.value || !Array.isArray(rows.value)) return [];
      const topRatedRow = rows.value.find((r) => r && r.title === "Top Rated");
      const recentRow = rows.value.find((r) => r && r.title === "Recently Added");
      const source = topRatedRow || recentRow || rows.value[1] || rows.value[0];
      return (source?.items || []).filter((i) => i && i.backdrop_path).slice(0, 6);
    });

    function selectCategory(cat) {
      selectedCategory.value = cat;
      if (store.profile?.is_kids) {
        unlockAchievement("kids_bubble_explorer");
      }
      applyKidsCategoryFilter();
    }

    function applyKidsCategoryFilter() {
      if (!store.profile?.is_kids || !kidsAllRows.value.length) return;
      if (selectedCategory.value === "all") {
        rows.value = kidsAllRows.value;
      } else if (selectedCategory.value === "cartoons") {
        rows.value = kidsAllRows.value.filter(r => r.categoryKey === "cartoons");
      } else if (selectedCategory.value === "adventures") {
        rows.value = kidsAllRows.value.filter(r => r.categoryKey === "adventures");
      } else if (selectedCategory.value === "magic") {
        rows.value = kidsAllRows.value.filter(r => r.categoryKey === "magic");
      } else if (selectedCategory.value === "comedy") {
        rows.value = kidsAllRows.value.filter(r => r.categoryKey === "comedy");
      } else if (selectedCategory.value === "family") {
        rows.value = kidsAllRows.value.filter(r => r.categoryKey === "family");
      }
      if (rows.value.length === 0) {
        rows.value = kidsAllRows.value;
      }
    }

    async function loadHome() {
      try {
        loading.value = true;
        const data = await API.get("/api/home");
        if (store.profile?.is_kids) {
          const allRaw = [];
          (data || []).forEach(r => (r.items || []).forEach(item => allRaw.push(item)));
          const uniqueItems = Array.from(new Map(allRaw.map(i => [i.id || i.tmdb_id, i])).values());
          const filtered = kidsFilter(uniqueItems);
          kidsItemCount.value = filtered.length;

          const animationItems = filtered.filter(i => (i.genres || '').toLowerCase().includes('animation') || i.type === 'anime');
          const adventureItems = filtered.filter(i => (i.genres || '').toLowerCase().includes('adventure') || (i.genres || '').toLowerCase().includes('action') || (i.genres || '').toLowerCase().includes('sci-fi'));
          const magicItems = filtered.filter(i => (i.genres || '').toLowerCase().includes('fantasy') || (i.genres || '').toLowerCase().includes('magic'));
          const familyItems = filtered.filter(i => (i.genres || '').toLowerCase().includes('family') || (i.genres || '').toLowerCase().includes('documentary'));
          const comedyItems = filtered.filter(i => (i.genres || '').toLowerCase().includes('comedy'));

          const kidsRows = [];
          if (animationItems.length) kidsRows.push({ title: "🎨 Animation & Cartoons", items: animationItems, categoryKey: "cartoons" });
          if (adventureItems.length) kidsRows.push({ title: "🚀 Fun Adventures", items: adventureItems, categoryKey: "adventures" });
          if (magicItems.length) kidsRows.push({ title: "🪄 Magic & Fantasy", items: magicItems, categoryKey: "magic" });
          if (familyItems.length) kidsRows.push({ title: "🦁 Animals & Family", items: familyItems, categoryKey: "family" });
          if (comedyItems.length) kidsRows.push({ title: "😄 Funny Laughs", items: comedyItems, categoryKey: "comedy" });
          if (filtered.length && kidsRows.length === 0) kidsRows.push({ title: "✨ Kids Movies & Shows", items: filtered, categoryKey: "all" });

          kidsAllRows.value = kidsRows;
          applyKidsCategoryFilter();
        } else {
          rows.value = (data || []).map(row => ({
            ...row,
            items: kidsFilter(row.items),
          })).filter(row => row.items && row.items.length > 0);
        }
      } catch (e) {
        addToast("Failed to load home page", "error");
      } finally {
        loading.value = false;
      }
    }

    onMounted(loadHome);

    const route = VueRouter.useRoute();
    watch(
      () => route.path,
      (newPath) => {
        if (newPath === "/") {
          loadHome();
          // If the user just cleared the cache, kick off a fresh scan automatically
          if (store.pendingScanAfterCacheCleared) {
            store.pendingScanAfterCacheCleared = false;
            startLibraryScan(true);
          }
        }
      },
    );

    watch(
      () => store.profile,
      (newProfile) => {
        if (newProfile) {
          loadHome();
        }
      },
    );

    watch(
      () => store.scanRunning,
      (running, prev) => {
        if (!running && prev === true) {
          loadHome();
        }
      },
    );

    function handleCardClick(item, row) {
      if (item.is_mounted === false && (row?.type === "continue" || item.position > 0 || item.type === "movie")) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      if (row?.type === "continue" || item.position > 0) {
        if (item.id) {
          router.push(`/watch/${item.id}`);
          return;
        }
      }
      if (item.type === "movie" && item.id) {
        router.push(`/title/movie/${item.id}`);
      } else if (item.tmdb_id) {
        router.push(`/title/${item.type || "series"}/${item.tmdb_id}`);
      } else if (item.id) {
        router.push(`/title/${item.type || "series"}/${item.id}`);
      }
    }

    async function handleRemoveContinue(item) {
      if (!item.id) return;
      try {
        await API.del(`/api/progress/${item.id}`);
        const cwRow = rows.value.find((r) => r.type === "continue");
        if (cwRow) {
          cwRow.items = cwRow.items.filter((i) => i.id !== item.id);
          if (cwRow.items.length === 0) {
            rows.value = rows.value.filter((r) => r.type !== "continue");
          }
        }
        addToast("Removed from Continue Watching", "success");
      } catch (e) {
        addToast("Failed to remove item", "error");
      }
    }

    function handlePlay(item) {
      if (item.is_mounted === false) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      if (item.type === "movie" && item.id) {
        router.push(`/watch/${item.id}`);
      } else {
        handleCardClick(item);
      }
    }

    function handleDetail(item) {
      handleCardClick(item);
    }

    async function triggerScanFromHome() {
      try {
        await API.post("/api/scan", {});
        store.scanRunning = true;
      } catch (e) {
        if (e.message && e.message.includes("409")) {
          addToast("Scan already in progress", "info");
        } else {
          addToast("Failed to start scan", "error");
        }
      }
    }

    const trailerModalUrl = ref(null);
    const trailerModalTitle = ref("");

    async function handleTrailer(item) {
      if (!item) return;
      if (store.profile?.is_kids) {
        addToast("Trailers are disabled in Kids Mode", "info");
        return;
      }
      try {
        const id = item.id || item.tmdb_id;
        const res = await API.get(`/api/media/${id}/trailer`);
        if (res && res.embed_url) {
          unlockAchievement("trailer_buff");
          trailerModalUrl.value = res.embed_url;
          trailerModalTitle.value = `${item.title} — ${res.title || 'Official Trailer'}`;
        } else {
          addToast("No trailer found for this title", "info");
        }
      } catch (e) {
        addToast("No trailer available for this title", "info");
      }
    }

    return {
      store,
      router,
      rows,
      loading,
      heroItems,
      trailerModalUrl,
      trailerModalTitle,
      handleCardClick,
      handleRemoveContinue,
      handlePlay,
      handleDetail,
      handleTrailer,
      triggerScanFromHome,
    };
  },
};

// ─── Title Detail Page ────────────────────────────────────────

const DetailPage = {
  components: { MediaCard, TrailerModal },
  template: `
    <div class="detail-page" v-if="media" @mousemove="onMouseMove">
      <trailer-modal
        v-if="trailerModalUrl"
        :url="trailerModalUrl"
        :title="trailerModalTitle"
        @close="trailerModalUrl = null"
      />

      <!-- Backdrop -->
      <div class="detail-backdrop">
        <div class="detail-backdrop-parallax" :style="backdropStyle">
          <transition name="kenburns-fade">
            <img
              v-if="activeBackdrop && !backdropFailed"
              :key="activeBackdrop"
              :src="imgUrl(activeBackdrop)"
              class="detail-backdrop-img"
              :alt="media.title"
              decoding="async"
              @error="backdropFailed = true"
            >
          </transition>
        </div>
        <!-- Fallback when the backdrop can't load (server down / file missing) -->
        <div v-if="!activeBackdrop || backdropFailed" class="detail-backdrop-fallback">
          <i class="ph ph-film-strip"></i>
        </div>
        <div class="detail-backdrop-overlay"></div>

        <!-- Backdrop Indicators (Manual Switcher) -->
        <div v-if="backdrops.length > 1" class="detail-backdrop-indicators">
          <div
            v-for="(b, idx) in backdrops"
            :key="idx"
            class="backdrop-dot"
            :class="{ active: idx === activeBackdropIdx }"
            @click.stop="activeBackdropIdx = idx"
            :title="'Backdrop ' + (idx + 1)"
          ></div>
        </div>
      </div>

      <!-- Body -->
      <div class="detail-body">
        <!-- Poster -->
        <div>
          <img
            v-if="media.poster_path"
            :src="imgUrl(media.poster_path)"
            class="detail-poster"
            :alt="media.title"
          >
          <div v-else class="detail-poster" style="background:var(--bg-card);display:flex;align-items:center;justify-content:center;font-size:3rem;">🎬</div>
        </div>

        <!-- Info -->
        <div class="detail-info">
          <div class="detail-type-badge">
            {{ media.type === 'anime' ? '🎌 Anime' : media.type === 'series' ? '📺 Series' : '🎬 Movie' }}
          </div>

          <div class="detail-title-container">
            <img v-if="media.logo_path" :src="imgUrl(media.logo_path)" :alt="media.title" class="detail-logo-img" />
            <h1 v-else class="detail-title">{{ media.title }}</h1>
          </div>

          <div class="detail-meta">
            <span v-if="media.year">{{ media.year }}</span>
            <span v-if="media.rating" class="detail-rating">⭐ {{ formatRating(media.rating) }}</span>
            <span v-if="media.vote_count" style="font-size:0.8rem;color:var(--text-muted)">{{ media.vote_count.toLocaleString() }} votes</span>
            <span v-if="media.runtime">{{ formatDuration(media.runtime * 60) }}</span>
            <a v-if="media.imdb_id" :href="'https://www.imdb.com/title/' + media.imdb_id" target="_blank" class="imdb-link-badge" title="Open IMDb Page" @click="unlockAchievement('imdb_surfer')">
              <span class="imdb-badge-logo">IMDb</span>
              <span class="imdb-id-text">{{ media.imdb_id }}</span>
            </a>
            <span v-if="media.has_multi_audio" class="multi-audio-badge" :title="media.audio_tracks ? media.audio_tracks.map(t => t.title).join(', ') : 'Multiple audio tracks available'">
              🎙️ Multi-Audio
            </span>
          </div>

          <div v-if="media.genres" class="detail-genres">
            <span
              v-for="genre in media.genres.split(',')"
              :key="genre.trim()"
              class="genre-tag"
              @click="browseGenre(genre.trim())"
            >{{ genre.trim() }}</span>
          </div>

          <p v-if="media.tagline" style="font-style:italic;color:var(--text-muted);margin-bottom:0.75rem;font-size:0.9rem">"{{ media.tagline }}"</p>

          <p class="detail-overview">{{ media.overview }}</p>

          <!-- Actions -->
          <div class="detail-actions" style="display:flex;align-items:center;gap:1.25rem;flex-wrap:wrap;margin-top:1.75rem;margin-bottom:2rem">
            <button class="btn btn-primary btn-lg" @click="playMedia" id="detail-play-btn">
              <span>{{ resumeLabel }}</span>
              <div class="btn-icon-wrapper">
                <i class="ph-fill ph-play" style="font-size:0.9rem"></i>
              </div>
            </button>
            <button v-if="!store.profile?.is_kids" class="btn btn-secondary btn-lg" @click="watchTrailer" id="detail-trailer-btn" title="Trailer">
              <i class="ph ph-film-strip" style="font-size:1.15rem"></i>
            </button>
            <button class="btn btn-secondary btn-lg" @click="toggleFav" id="detail-fav-btn" :title="media.is_favorite ? 'Remove from Watchlist' : 'Add to Watchlist'">
              <i :class="media.is_favorite ? 'ph-fill ph-heart' : 'ph ph-heart'" style="font-size:1.15rem" :style="{ color: media.is_favorite ? 'var(--accent)' : 'inherit' }"></i>
            </button>
            <button v-if="!store.profile?.is_kids" class="btn btn-ghost btn-lg" @click="showCollectionModal = true" id="detail-collection-btn" title="Add to List">
              <i class="ph ph-plus-circle" style="font-size:1.15rem"></i>
            </button>
            <button v-if="!store.profile?.is_kids" class="btn btn-ghost btn-lg" @click="openFixMatchModal" id="detail-fix-match-btn" title="Fix Match">
              <i class="ph ph-wrench" style="font-size:1.15rem"></i>
            </button>
            <button v-if="!store.profile?.is_kids" class="btn btn-ghost btn-lg" @click="recacheInfo" :disabled="recaching" id="detail-recache-btn" :title="recaching ? 'Re-caching...' : 'Re-cache'">
              <i :class="recaching ? 'ph ph-circle-notch' : 'ph ph-database'" :style="{ animation: recaching ? 'spin 1s linear infinite' : 'none', fontSize: '1.15rem' }"></i>
            </button>
          </div>

          <!-- Codec Compatibility Warning Card -->
          <div class="codec-warning-card" v-if="codecInfo.hasWarning && !store.profile?.is_kids">
            <div class="codec-warning-icon">⚠️</div>
            <div class="codec-warning-content">
              <div class="codec-warning-title">
                Codec Compatibility Notice
                <span v-for="tag in codecInfo.tags" :key="tag" class="codec-badge">{{ tag }}</span>
              </div>
              <div class="codec-warning-note">
                {{ codecInfo.note }}
              </div>
            </div>
          </div>

          <!-- Cast Section -->
          <div class="detail-section" v-if="media.cast && media.cast.length">
            <div class="detail-section-header">
              <div class="detail-section-title">
                <i class="ph ph-users"></i> Cast & Crew
              </div>
              <div class="row-header-controls" v-if="media.cast.length > 5">
                <button class="row-control-btn" @click="scrollCast(-400)" title="Scroll Left">
                  <i class="ph ph-caret-left"></i>
                </button>
                <button class="row-control-btn" @click="scrollCast(400)" title="Scroll Right">
                  <i class="ph ph-caret-right"></i>
                </button>
              </div>
            </div>
            <div class="cast-scroll-container" ref="castScrollerRef">
              <div
                v-for="member in media.cast.slice(0, 20)"
                :key="member.name"
                class="cast-card cast-card-clickable"
                :title="'Find more titles with ' + member.name"
                @click="searchCast(member.name)"
              >
                <div class="card-inner">
                  <div class="cast-portrait-wrap">
                    <img
                      v-if="member && member.profile"
                      :src="'https://image.tmdb.org/t/p/w185' + member.profile"
                      :alt="member.name"
                      class="cast-portrait-img"
                      loading="lazy"
                      @error="e => e.target.style.display='none'"
                    >
                    <div v-else class="cast-portrait-placeholder">🎭</div>
                  </div>
                  <div class="cast-info-wrap">
                    <div class="cast-name" :title="member.name">{{ member.name }}</div>
                    <div class="cast-character" :title="member.character">{{ member.character || 'Role' }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- File Details Bento Container -->
          <div class="detail-section" v-if="media.file_path">
            <div class="detail-section-title">
              <i class="ph ph-file-video" style="color:var(--accent)"></i> Media File Details
            </div>
            <div class="file-details-card">
              <div class="card-inner file-details-inner">
                <!-- File Path Header -->
                <div class="file-path-header">
                  <div class="file-path-info">
                    <span class="file-path-label">STORAGE LOCATION</span>
                    <div class="file-path-text" :title="media.file_path">{{ media.file_path }}</div>
                  </div>
                  <button class="btn btn-secondary btn-sm" @click="copyFilePath" title="Copy file path to clipboard" id="btn-copy-filepath">
                    <i class="ph ph-copy" style="font-size:0.95rem"></i> Copy Path
                  </button>
                </div>

                <!-- Badges Row -->
                <div class="file-details-pills">
                  <a v-if="media.imdb_id" :href="'https://www.imdb.com/title/' + media.imdb_id" target="_blank" class="file-pill imdb-pill" title="View on IMDb" @click="unlockAchievement('imdb_surfer')">
                    <i class="ph ph-arrow-square-out"></i>
                    <span>IMDb: {{ media.imdb_id }}</span>
                  </a>
                  <div class="file-pill" v-if="media.file_size">
                    <i class="ph ph-hard-drive"></i>
                    <span>{{ formatFileSize(media.file_size) }}</span>
                  </div>
                  <div class="file-pill" v-if="getFileExtension(media.file_path)">
                    <i class="ph ph-film-strip"></i>
                    <span>{{ getFileExtension(media.file_path) }}</span>
                  </div>
                  <div class="file-pill" :class="media.is_mounted !== false ? 'mounted' : 'unmounted'">
                    <i :class="media.is_mounted !== false ? 'ph ph-check-circle' : 'ph ph-plugs-connected'"></i>
                    <span>{{ media.is_mounted !== false ? 'Drive Mounted' : 'Drive Unmounted' }}</span>
                  </div>
                  <div class="file-pill" v-if="media.has_multi_audio">
                    <i class="ph ph-speaker-high"></i>
                    <span>Multi-Audio Track</span>
                  </div>
                </div>

                <!-- Audio Tracks Detail List -->
                <div class="file-audio-tracks" v-if="media.audio_tracks && media.audio_tracks.length">
                  <div class="file-audio-label">AUDIO TRACKS DETECTED</div>
                  <div class="audio-track-list">
                    <div v-for="(track, idx) in media.audio_tracks" :key="idx" class="audio-track-pill">
                      <span class="audio-track-index">#{{ idx + 1 }}</span>
                      <span class="audio-track-title">{{ track.title }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Seasons / Episodes -->
          <div class="seasons-section" v-if="media.seasons && Object.keys(media.seasons).length">
            <div class="season-tabs-header">
              <h3>Episodes</h3>
              <div v-if="sortedSeasons.length > 3" class="season-select-container">
                <select v-model="activeSeason" class="season-dropdown-select" id="season-dropdown-select">
                  <option v-for="season in sortedSeasons" :key="season" :value="season">
                    Season {{ season }} ({{ getSeasonMeta(season).localCount }}/{{ getSeasonMeta(season).totalCount }})
                  </option>
                </select>
              </div>
            </div>

            <div class="season-tabs-container">
              <button class="season-scroll-btn left" @click="scrollSeasonTabs(-250)" title="Scroll seasons left">
                <i class="ph ph-caret-left"></i>
              </button>
              <div class="season-tabs" ref="seasonTabsRef" @wheel="onSeasonTabsWheel">
                <button
                  v-for="season in sortedSeasons"
                  :key="season"
                  class="season-tab"
                  :class="{ active: activeSeason === season, 'season-missing': getSeasonMeta(season).isMissing }"
                  @click="activeSeason = season"
                  :id="'season-tab-' + season"
                >
                  Season {{ season }}
                  <span class="season-tab-count">
                    ({{ getSeasonMeta(season).localCount }}/{{ getSeasonMeta(season).totalCount }})
                  </span>
                </button>
              </div>
              <button class="season-scroll-btn right" @click="scrollSeasonTabs(250)" title="Scroll seasons right">
                <i class="ph ph-caret-right"></i>
              </button>
            </div>

            <div class="episodes-list">
              <div
                v-for="ep in media.seasons[activeSeason]"
                :key="ep.id || ('missing-' + ep.season + '-' + ep.episode)"
                class="episode-card"
                :class="{ 'missing-episode': ep.is_local === false || ep.is_mounted === false }"
                @click="playEpisode(ep)"
                :id="'ep-' + (ep.id || ('missing-' + ep.episode))"
              >
                <!-- 16:9 Thumbnail -->
                <div class="episode-thumb-container">
                  <img
                    v-if="ep.still_path"
                    :src="imgUrl(ep.still_path)"
                    class="episode-thumb-img"
                    @error="e => e.target.style.display = 'none'"
                  />
                  <img
                    v-else-if="media.backdrop_path"
                    :src="imgUrl(media.backdrop_path)"
                    class="episode-thumb-img"
                  />
                  <div class="episode-thumb-overlay" v-if="ep.is_local !== false && ep.is_mounted !== false">
                    <i class="ph-fill ph-play episode-play-icon"></i>
                  </div>
                  <!-- Missing / Unmounted Overlay Badge -->
                  <div class="episode-thumb-overlay" v-else style="opacity:1;background:rgba(10,10,15,0.65)">
                    <span class="missing-badge">{{ ep.is_mounted === false ? '🔌 Unmounted' : '⚠️ Not Downloaded' }}</span>
                  </div>
                  <!-- Red watch progress bar -->
                  <div v-if="calcProgressPercent(ep) > 0" class="episode-thumb-progress">
                    <div class="episode-thumb-progress-fill" :style="{ width: calcProgressPercent(ep) + '%' }"></div>
                  </div>
                  <!-- Per-episode skip marker editor -->
                  <button
                    v-if="ep.id && !store.profile?.is_kids"
                    class="episode-skip-btn"
                    :class="{ 'has-markers': episodeHasMarkers(ep) }"
                    @click.stop="openEpisodeSkipModal(ep)"
                    :title="'Edit skip markers for S' + activeSeason.toString().padStart(2,'0') + 'E' + (ep.episode || '?').toString().padStart(2,'0')"
                  >
                    <i class="ph ph-timer"></i>
                  </button>
                </div>

                <!-- Episode Info & Summary -->
                <div class="episode-card-body">
                  <div class="episode-card-header">
                    <div class="episode-card-number">
                      S{{ activeSeason.toString().padStart(2,'0') }}E{{ (ep.episode || '?').toString().padStart(2,'0') }}
                      <span class="episode-card-title">• {{ ep.ep_title || ep.title }}</span>
                      <span v-if="ep.is_local === false" class="missing-badge" style="margin-left:8px">Missing</span>
                    </div>
                    <div class="episode-card-runtime" v-if="ep.duration">
                      {{ formatDuration(ep.duration) }}
                    </div>
                  </div>
                  <div class="episode-card-overview">
                    {{ ep.overview || 'No description available for this episode.' }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Add to Collection Modal -->
      <div class="modal-backdrop" v-if="showCollectionModal" @click.self="showCollectionModal = false">
        <div class="modal-card" style="max-width:460px">
          <div class="modal-title">Add to Collection</div>

          <!-- Inline Create Collection Row -->
          <div style="margin-top:1rem;margin-bottom:0.75rem;padding:0.75rem;background:var(--bg-secondary);border-radius:8px">
            <div v-if="!showInlineCreate" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer" @click="showInlineCreate = true" id="btn-inline-create-col">
              <span style="font-weight:600;font-size:0.9rem;color:var(--accent)">
                <i class="ph ph-plus-circle" style="margin-right:4px"></i> Create New Collection
              </span>
            </div>
            <div v-else style="display:flex;gap:6px">
              <input type="text" v-model="inlineColName" class="form-input" placeholder="Collection name..." @keyup.enter="createAndAddInlineCollection" autofocus id="input-inline-col-name" />
              <button class="btn btn-primary btn-sm" @click="createAndAddInlineCollection" id="btn-save-inline-col">Create & Add</button>
            </div>
          </div>

          <div style="max-height:260px;overflow-y:auto">
            <div v-if="collections.length === 0" style="color:var(--text-muted);text-align:center;padding:1rem">
              No collections created yet. Type a name above to create one!
            </div>
            <div v-for="col in collections" :key="col.id"
              style="padding:0.75rem;cursor:pointer;border-radius:8px;transition:background 0.15s;margin-bottom:4px;display:flex;align-items:center;justify-content:space-between"
              :style="{ background: inCollection(col) ? 'var(--accent-dim)' : 'var(--bg-secondary)' }"
              @click="toggleCollection(col)"
            >
              <div>
                <div style="font-weight:600;font-size:0.9rem">{{ col.name }}</div>
                <div style="font-size:0.75rem;color:var(--text-muted)">{{ col.items.length }} items</div>
              </div>
              <i :class="inCollection(col) ? 'ph-fill ph-check-circle' : 'ph ph-circle'" :style="{ color: inCollection(col) ? 'var(--accent)' : 'var(--text-muted)', fontSize: '1.2rem' }"></i>
            </div>
          </div>
          <button class="btn btn-ghost btn-full" style="margin-top:1rem" @click="showCollectionModal = false">Close</button>
        </div>
      </div>

      <!-- Fix Match Modal -->
      <fix-match-modal
        v-if="showFixMatchModal"
        :target="fixMatchTarget"
        @close="showFixMatchModal = false"
        @matched="handleFixMatchDone"
      />

      <!-- Skip Timestamps Editor Modal (per-episode) -->
      <skip-timestamps-modal
        v-if="showSkipModal"
        :media="skipEditTarget || media"
        :inPlayer="false"
        @close="showSkipModal = false"
        @saved="handleSkipSaved"
      />
    </div>

    <div v-else-if="loading" class="detail-page" style="display:flex;align-items:center;justify-content:center;min-height:100vh">
      <div class="loading-spinner"></div>
    </div>

    <div v-else class="empty-state" style="padding-top:calc(var(--nav-height) + 4rem);min-height:80vh">
      <div class="empty-icon">⚠️</div>
      <div class="empty-title">Title Not Found</div>
      <div class="empty-subtitle" style="margin-bottom:1.5rem">Could not load details for this media item.</div>
      <button class="btn btn-primary" @click="router.back()">Go Back</button>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const media = ref(null);
    const loading = ref(true);
    const activeSeason = ref("1");
    const seasonTabsRef = ref(null);
    const showCollectionModal = ref(false);
    const collections = ref([]);

    const showFixMatchModal = ref(false);
    const fixQuery = ref("");
    const fixResults = ref([]);
    const searchingFix = ref(false);
    const fixSearched = ref(false);

    const sortedSeasons = computed(() => {
      if (!media.value?.seasons) return [];
      return Object.keys(media.value.seasons).sort((a, b) => Number(a) - Number(b));
    });

    const resumeLabel = computed(() => {
      const p = media.value?.progress;
      if (p && p.position > 30) return "▶ Resume";
      return "▶ Play";
    });

    const codecInfo = computed(() => {
      const path = media.value?.file_path || media.value?.seasons?.[sortedSeasons.value[0]]?.[0]?.file_path;
      return getCodecInfo(path);
    });

    const backdropFailed = ref(false);
    const activeBackdropIdx = ref(0);
    const parallaxX = ref(0);
    const parallaxY = ref(0);
    const scrollOffsetY = ref(0);
    let backdropCycleTimer = null;

    const backdrops = computed(() => {
      const list = [];
      if (media.value?.backdrops && Array.isArray(media.value.backdrops)) {
        for (const b of media.value.backdrops) {
          if (b && !list.includes(b)) list.push(b);
        }
      }
      if (media.value?.backdrop_path && !list.includes(media.value.backdrop_path)) {
        list.unshift(media.value.backdrop_path);
      }
      return list;
    });

    const activeBackdrop = computed(() => backdrops.value[activeBackdropIdx.value] || media.value?.backdrop_path || null);

    const backdropStyle = computed(() => ({
      transform: `translate3d(${parallaxX.value}px, ${parallaxY.value + scrollOffsetY.value}px, 0) scale(1.06)`,
      transition: "transform 0.15s cubic-bezier(0.2, 0, 0.2, 1)"
    }));

    function onMouseMove(e) {
      const w = window.innerWidth;
      const h = window.innerHeight;
      parallaxX.value = ((e.clientX / w) - 0.5) * -22;
      parallaxY.value = ((e.clientY / h) - 0.5) * -16;
    }

    function onScroll() {
      scrollOffsetY.value = window.scrollY * -0.28;
    }

    function startBackdropCycle() {
      if (backdropCycleTimer) clearInterval(backdropCycleTimer);
      backdropCycleTimer = setInterval(() => {
        if (backdrops.value.length > 1) {
          activeBackdropIdx.value = (activeBackdropIdx.value + 1) % backdrops.value.length;
        }
      }, 8000);
    }

    async function load() {
      loading.value = true;
      backdropFailed.value = false;   // reset fallback when loading a title
      try {
        const { type, id } = route.params;
        let url;
        if (type === "movie") {
          url = `/api/media/${id}`;
        } else {
          url = `/api/show/${id}?type=${type}`;
        }
        const loadedMedia = await API.get(url);
        if (store.profile?.is_kids && loadedMedia && !isKidSafeItem(loadedMedia)) {
          addToast("🧒 Kids Safe Mode: This title is restricted.", "warning");
          media.value = null;
          router.replace("/");
          return;
        }
        media.value = loadedMedia;
        activeBackdropIdx.value = 0;
        startBackdropCycle();
        if (sortedSeasons.value.length) {
          activeSeason.value = sortedSeasons.value[0];
        }
        if (store.profile) {
          collections.value = await API.get("/api/collections");
        }
      } catch (e) {
        media.value = null;
      } finally {
        loading.value = false;
      }
    }

    onMounted(() => {
      load();
      window.addEventListener("scroll", onScroll, { passive: true });
    });
    onUnmounted(() => {
      if (backdropCycleTimer) clearInterval(backdropCycleTimer);
      window.removeEventListener("scroll", onScroll);
    });
    watch(() => route.params.id, () => {
      activeBackdropIdx.value = 0;
      load();
    });

    function copyFilePath() {
      if (!media.value?.file_path) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(media.value.file_path);
        addToast('File path copied to clipboard!', 'success');
      } else {
        const input = document.createElement('input');
        input.value = media.value.file_path;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        addToast('File path copied to clipboard!', 'success');
      }
    }

    function formatFileSize(bytes) {
      if (!bytes || isNaN(bytes) || bytes <= 0) return '0 MB';
      const tb = bytes / (1024 * 1024 * 1024 * 1024);
      if (tb >= 1.0) return `${tb < 10 ? tb.toFixed(2) : tb.toFixed(1)} TB`;
      const gb = bytes / (1024 * 1024 * 1024);
      if (gb >= 1.0) return `${gb < 10 ? gb.toFixed(2) : gb.toFixed(1)} GB`;
      const mb = bytes / (1024 * 1024);
      return `${mb.toFixed(1)} MB`;
    }

    function getFileExtension(path) {
      if (!path) return '';
      const parts = path.split('.');
      if (parts.length < 2) return '';
      return parts[parts.length - 1].toUpperCase();
    }

    function playMedia() {
      if (!media.value) return;
      if (media.value.is_mounted === false) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      if (media.value.type === "movie") {
        router.push(`/watch/${media.value.id}`);
      } else {
        const seasonEps = media.value.seasons?.[activeSeason.value] || [];
        const playableEp = seasonEps.find((e) => e.is_local !== false && e.is_mounted !== false);
        if (playableEp) {
          router.push(`/watch/${playableEp.id}`);
        } else {
          addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        }
      }
    }

    function playEpisode(ep) {
      if (ep.is_local === false) {
        addToast("Episode not downloaded in library", "info");
        return;
      }
      if (ep.is_mounted === false) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      router.push(`/watch/${ep.id}`);
    }

    async function toggleFav() {
      if (!media.value || !store.profile) return;
      const idToFav = media.value.id || media.value.seasons?.[sortedSeasons.value[0]]?.[0]?.id;
      if (!idToFav) return;
      const res = await API.post("/api/favorites/toggle", { media_id: idToFav });
      media.value.is_favorite = res.is_favorite;
      addToast(res.is_favorite ? "Added to Favorites" : "Removed from Favorites", "info");
    }

    function browseGenre(genre) {
      router.push(`/browse?genre=${encodeURIComponent(genre)}`);
    }

    function inCollection(col) {
      if (!media.value) return false;
      const mediaId = media.value.id || media.value.seasons?.[sortedSeasons.value[0]]?.[0]?.id;
      return col.items.some((i) => i.id === mediaId);
    }

    const inlineColName = ref("");
    const showInlineCreate = ref(false);

    async function createAndAddInlineCollection() {
      const name = inlineColName.value.trim();
      if (!name) return;
      try {
        const col = await API.post("/api/collections", { name });
        col.items = [];
        collections.value.unshift(col);
        inlineColName.value = "";
        showInlineCreate.value = false;
        await toggleCollection(col);
        addToast(`Created "${name}" & added title!`, "success");
      } catch (e) {
        addToast("Failed to create collection", "error");
      }
    }

    async function toggleCollection(col) {
      const mediaId = media.value.id || media.value.seasons?.[sortedSeasons.value[0]]?.[0]?.id;
      if (!mediaId) return;
      if (inCollection(col)) {
        await API.del(`/api/collections/${col.id}/items/${mediaId}`);
        col.items = col.items.filter((i) => i.id !== mediaId);
      } else {
        await API.post(`/api/collections/${col.id}/items`, { media_id: mediaId });
        col.items.push({ id: mediaId });
      }
    }

    const fixMatchTarget = computed(() => {
      if (!media.value) return null;
      const mediaId = media.value.id || media.value.seasons?.[sortedSeasons.value[0]]?.[0]?.id;
      return {
        id: mediaId,
        tmdb_id: media.value.tmdb_id,
        title: media.value.title,
        year: media.value.year,
        type: media.value.type || route.params.type || "movie",
        file_path: media.value.file_path
      };
    });

    function openFixMatchModal() {
      showFixMatchModal.value = true;
    }

    async function handleFixMatchDone(result) {
      showFixMatchModal.value = false;
      await load();
    }

    function getSeasonMeta(seasonNum) {
      const eps = media.value?.seasons?.[seasonNum] || [];
      const localCount = eps.filter(e => e.is_local !== false && e.is_mounted !== false).length;
      const totalCount = eps.length;
      return { localCount, totalCount, isMissing: localCount === 0 };
    }

    const trailerModalUrl = ref(null);
    const trailerModalTitle = ref("");
    const showSkipModal = ref(false);
    // Which episode's markers are being edited (per-episode skip markers)
    const skipEditTarget = ref(null);

    function openEpisodeSkipModal(ep) {
      if (!ep || !ep.id) {
        addToast("Skip markers need a local media file", "info");
        return;
      }
      skipEditTarget.value = ep;
      showSkipModal.value = true;
    }

    function episodeHasMarkers(ep) {
      if (!ep) return false;
      return !!(
        (ep.recap_end || 0) > (ep.recap_start || 0) ||
        (ep.intro_end || 0) > (ep.intro_start || 0) ||
        (ep.outro_end || 0) > (ep.outro_start || 0)
      );
    }

    function handleSkipSaved(updatedData) {
      // Write the new markers onto the exact episode object being edited so
      // reopening the editor (and the has-markers badge) reflects them live.
      if (skipEditTarget.value) {
        Object.assign(skipEditTarget.value, updatedData);
      } else if (media.value) {
        Object.assign(media.value, updatedData);
      }
    }

    // ─── Re-cache: wipe this title's metadata/artwork, re-download ──
    const recaching = ref(false);
    async function recacheInfo() {
      if (!media.value || recaching.value) return;
      const tmdbId = media.value.tmdb_id;
      if (!tmdbId) {
        addToast("This title has no TMDb match — use 'Fix Match' first", "warning");
        return;
      }
      const ok = await customConfirm({
        title: "Re-cache this title?",
        message: "Deletes the current metadata, artwork, and episode info for this title and re-downloads everything from TMDb. Skip markers you set manually are kept.",
        icon: "ph ph-database",
        okText: "Delete & Re-download",
        danger: true,
      });
      if (!ok) return;

      recaching.value = true;
      try {
        const res = await API.post("/api/recache", {
          tmdb_id: tmdbId,
          type: media.value.type,
        });
        addToast(
          `Re-cached "${res.title}" — ${res.removed_files} old files replaced across ${res.updated_rows} entries`,
          "success",
          5000
        );
        await load();
      } catch (e) {
        addToast(e.message || "Re-cache failed", "error");
      } finally {
        recaching.value = false;
      }
    }

    async function watchTrailer() {
      if (!media.value) return;
      const mediaId = media.value.id || media.value.seasons?.[sortedSeasons.value[0]]?.[0]?.id;
      if (!mediaId) return;
      try {
        const res = await API.get(`/api/media/${mediaId}/trailer`);
        if (res && res.embed_url) {
          unlockAchievement("trailer_buff");
          trailerModalUrl.value = res.embed_url;
          trailerModalTitle.value = `${media.value.title} — ${res.title || 'Official Trailer'}`;
        } else {
          addToast("No trailer found for this title", "info");
        }
      } catch (e) {
        addToast("No trailer available for this title", "info");
      }
    }

    const castScrollerRef = ref(null);
    function scrollCast(offset) {
      if (castScrollerRef.value) {
        castScrollerRef.value.scrollBy({ left: offset, behavior: "smooth" });
      }
    }

    // Click a cast member → jump to Search pre-filled with their name.
    // The backend deep-search matches cast_json, so results are titles
    // featuring that actor across the whole library.
    function searchCast(name) {
      if (!name) return;
      router.push({ path: "/search", query: { q: name } });
    }

    function copyFilePath() {
      if (!media.value?.file_path) return;
      navigator.clipboard.writeText(media.value.file_path).then(() => {
        addToast("Storage location copied to clipboard!", "success");
      }).catch(() => {
        addToast("Failed to copy path", "error");
      });
    }

    function scrollSeasonTabs(offset) {
      if (seasonTabsRef.value) {
        seasonTabsRef.value.scrollBy({ left: offset, behavior: "smooth" });
      }
    }

    function onSeasonTabsWheel(e) {
      if (seasonTabsRef.value && e.deltaY) {
        seasonTabsRef.value.scrollLeft += e.deltaY;
      }
    }

    return {
      store,
      media,
      loading,
      activeSeason,
      sortedSeasons,
      getSeasonMeta,
      seasonTabsRef,
      scrollSeasonTabs,
      onSeasonTabsWheel,
      castScrollerRef,
      scrollCast,
      searchCast,
      backdropFailed,
      activeBackdropIdx,
      backdrops,
      activeBackdrop,
      backdropStyle,
      onMouseMove,
      skipEditTarget,
      openEpisodeSkipModal,
      episodeHasMarkers,
      recaching,
      recacheInfo,
      copyFilePath,
      resumeLabel,
      codecInfo,
      showCollectionModal,
      collections,
      inlineColName,
      showInlineCreate,
      createAndAddInlineCollection,
      showFixMatchModal,
      fixMatchTarget,
      openFixMatchModal,
      handleFixMatchDone,
      router,
      imgUrl,
      formatRating,
      formatDuration,
      calcProgressPercent,
      playMedia,
      playEpisode,
      toggleFav,
      browseGenre,
      inCollection,
      toggleCollection,
      copyFilePath,
      formatFileSize,
      getFileExtension,
      watchTrailer,
      trailerModalUrl,
      trailerModalTitle,
      showSkipModal,
      handleSkipSaved,
    };
  },
};

// ─── Settings Page ────────────────────────────────────────────

const SettingsPage = {
  template: `
    <div class="settings-page">
      <div class="settings-header">
        <div class="settings-title">
          <i class="ph ph-gear" style="color:var(--accent)"></i>
          <span>Application Settings</span>
        </div>
      </div>

      <div v-if="loading" style="display:flex;justify-content:center;padding:4rem">
        <div class="loading-spinner"></div>
      </div>

      <template v-else>
        <!-- Appearance & Themes -->
        <div class="settings-section" id="settings-theme-section">
          <div class="settings-section-title">
            <i class="ph ph-palette" style="color:var(--accent)"></i>
            <span>Appearance & Theme Presets</span>
          </div>
          <div class="settings-group">
            <div class="settings-label-container" style="margin-bottom:12px">
              <div class="settings-label">Active Theme Preset</div>
              <div class="settings-desc">Choose a curated visual theme for your profile. Changes apply instantly across the entire interface.</div>
            </div>

            <div class="theme-preset-grid">
              <div
                v-for="t in THEME_PRESETS"
                :key="t.id"
                class="theme-preset-card"
                :class="{ active: currentTheme === t.id }"
                @click="selectTheme(t.id)"
              >
                <div class="theme-card-preview" :style="{ background: t.bg, borderColor: t.border }">
                  <div class="theme-card-accent-bar" :style="{ background: t.accent }"></div>
                  <div class="theme-card-dots">
                    <span class="theme-card-dot" :style="{ background: t.accent }"></span>
                    <span class="theme-card-dot" :style="{ background: t.secondary || t.accent }"></span>
                  </div>
                </div>
                <div class="theme-card-body">
                  <div class="theme-card-name">
                    <span>{{ t.name }}</span>
                    <span v-if="currentTheme === t.id" class="theme-active-tag">Active</span>
                  </div>
                  <div class="theme-card-desc">{{ t.desc }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 0. Updates -->
        <div class="settings-section" id="settings-updates-section">
          <div class="settings-section-title">
            <i class="ph ph-arrow-circle-up" style="color:var(--accent)"></i>
            <span>Updates</span>
          </div>
          <div class="settings-group" style="display:flex;flex-direction:column;gap:12px">
            <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
              <div class="settings-label-container">
                <div class="settings-label">Current version</div>
                <div class="settings-desc">CapsStream v{{ sysInfo?.version || '…' }}</div>
              </div>
              <div class="settings-label-container" v-if="updateState.last_checked">
                <div class="settings-label">Last checked</div>
                <div class="settings-desc">{{ updateState.last_checked }}</div>
              </div>
              <div class="settings-label-container" v-if="updateState.latest && updateState.status !== 'up_to_date'">
                <div class="settings-label">Latest available</div>
                <div class="settings-desc" style="color:var(--accent)">v{{ updateState.latest }}</div>
              </div>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Automatic Update Checks</div>
                <div class="settings-desc">Periodically check for new CapsStream releases and show a banner when one is available.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.updates.auto_check" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div
              class="update-status-line"
              :style="{ color: updateState.status === 'available' ? 'var(--accent)' : updateState.status === 'error' ? '#ef4444' : 'var(--text-secondary)' }"
            >
              {{ updateState.message || 'Check for updates to see if a new version is available.' }}
            </div>

            <!-- Live update progress -->
            <div v-if="updateInstalling && updateProgress && updateProgress.stage === 'downloading' && updateProgress.total" style="margin-top:10px">
              <div style="height:6px;border-radius:3px;background:var(--bg-secondary);overflow:hidden">
                <div style="height:100%;background:var(--accent);transition:width .4s" :style="{ width: Math.round(100 * (updateProgress.bytes_done || 0) / (updateProgress.total || 1)) + '%' }"></div>
              </div>
              <div style="font-size:.8rem;color:var(--text-secondary);margin-top:4px">
                Downloading… {{ Math.round((updateProgress.bytes_done || 0) / 1048576 * 10) / 10 }} / {{ Math.round((updateProgress.total || 0) / 1048576 * 10) / 10 }} MB
              </div>
            </div>
            <div v-else-if="updateInstalling && updateProgress && ['verifying','extracting','validating','installing'].includes(updateProgress.stage)" style="font-size:.85rem;color:var(--text-secondary);margin-top:8px">
              <i class="ph ph-circle-notch" style="animation:spin 1s linear infinite;margin-right:6px"></i>{{ updateProgress.message || (updateProgress.stage[0].toUpperCase() + updateProgress.stage.slice(1)) + '…' }}
            </div>

            <!-- One-click restart for backend updates -->
            <div v-if="restartPending" style="margin-top:10px;padding:10px 14px;border-radius:12px;background:rgba(253,203,110,.12);border:1px solid rgba(253,203,110,.35);color:#fdcb6e;font-size:.87rem">
              <i class="ph ph-circle-notch" style="animation:spin 1s linear infinite;margin-right:6px"></i>Restarting — the server will come back online in a few seconds…
            </div>

            <div
              v-if="updateState.changelog"
              class="changelog-box"
              v-html="changelogHtml"
            ></div>

            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button class="btn btn-secondary" @click="checkUpdates" :disabled="updateChecking">
                <i :class="updateChecking ? 'ph ph-circle-notch' : 'ph ph-magnifying-glass'" :style="updateChecking ? 'animation:spin 1s linear infinite' : ''" style="margin-right:6px"></i>
                {{ updateChecking ? 'Checking...' : 'Check for Updates' }}
              </button>
              <button
                v-if="updateState.status === 'available'"
                class="btn btn-primary"
                @click="installUpdate"
                :disabled="updateInstalling"
                id="btn-install-update"
              >
                <i :class="updateInstalling ? 'ph ph-circle-notch' : 'ph ph-download-simple'" :style="updateInstalling ? 'animation:spin 1s linear infinite' : ''" style="margin-right:6px"></i>
                {{ updateInstalling ? 'Installing...' : 'Install Update' }}
              </button>
              <button
                v-if="updateState.status === 'up_to_date' && !restartPending && !updateInstalling && /restart CapsStream/i.test(updateState.message)"
                class="btn btn-primary"
                @click="restartAfterUpdate"
                id="btn-restart-update"
              >
                <i class="ph ph-arrow-clockwise" style="margin-right:6px"></i>
                Restart &amp; Finish Update
              </button>
            </div>
          </div>
        </div>

        <!-- 1. Metadata Providers -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-database" style="color:var(--accent)"></i>
            <span>Metadata Providers & API Keys</span>
          </div>
          <div class="settings-group">
            <div class="settings-row" style="flex-direction:column;align-items:flex-start">
              <div class="settings-label-container">
                <div class="settings-label">TMDb API Key (Main Metadata Provider)</div>
                <div class="settings-desc">Used for fetching movie/series posters, backdrops, ratings, overviews, and cast info.</div>
              </div>
              <div style="display:flex;gap:8px;width:100%;margin-top:8px">
                <input type="password" v-model="form.tmdb_api_key" class="form-input" placeholder="Enter TMDb API key..." style="flex:1" />
                <button class="btn btn-secondary" @click="testApi('tmdb', form.tmdb_api_key)" :disabled="testingApi === 'tmdb'">
                  {{ testingApi === 'tmdb' ? 'Testing...' : 'Test API' }}
                </button>
              </div>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Enable Jikan API (Anime Metadata Fallback)</div>
                <div class="settings-desc">Use MyAnimeList/Jikan API for fallback anime metadata matching.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.metadata_sources.enable_jikan" />
                <span class="toggle-slider"></span>
              </label>
            </div>
          </div>
        </div>

        <!-- 1b. Server -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-hard-drives" style="color:var(--accent)"></i>
            <span>Server</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Host Address</div>
                <div class="settings-desc">Network interface the server binds to. Use 127.0.0.1 for this PC only, or 0.0.0.0 to allow other devices on your network.</div>
              </div>
              <input type="text" v-model="form.host" class="form-input" style="width:180px" placeholder="127.0.0.1" />
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Port</div>
                <div class="settings-desc">TCP port the server listens on (1–65535).</div>
              </div>
              <input type="number" v-model.number="form.port" min="1" max="65535" class="form-input" style="width:120px" />
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Open Browser on Launch</div>
                <div class="settings-desc">Automatically open CapsStream in your browser when start.bat runs.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.launch_browser_on_start" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-desc" style="color:#f59e0b">
              <i class="ph ph-warning" style="margin-right:4px"></i>
              Host and Port changes take effect after restarting CapsStream (close the server and run start.bat again).
            </div>

            <div>
              <button class="btn btn-secondary btn-sm" @click="$router.push('/logs')" title="View live server log">
                <i class="ph ph-scroll" style="margin-right:4px"></i> View Live Logs
              </button>
            </div>
          </div>
        </div>

        <!-- 2. System Files, Web Browser & Media Paths -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-globe-hemisphere-west" style="color:var(--accent)"></i>
            <span>Web Browser & System Configuration</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Default Web Browser</div>
                <div class="settings-desc">Choose preferred browser for launching media streaming. Microsoft Edge is recommended for native 4K HEVC and Dolby AC-3 decoding.</div>
              </div>
              <select v-model="form.browser" class="form-input" style="width:280px" id="setting-browser-select">
                <option value="edge">🌐 Microsoft Edge (Recommended)</option>
                <option value="chrome">🌐 Google Chrome</option>
                <option value="system">💻 System Default Browser</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Hide System Files & Folders</div>
                <div class="settings-desc">When enabled, hides all files and folders in the root project except media folders and start.bat.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.hide_system_files" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Hide Unmounted Media Items</div>
                <div class="settings-desc">When enabled, automatically hides media files located on disconnected external drives or unmounted storage paths.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.hide_unmounted_items" id="setting-hide-unmounted-toggle" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div style="margin-top:1rem">
              <div class="settings-label">Media Scanner Paths</div>
              <div class="settings-desc">Local directories scanned for video files, grouped by category. Order sets scan priority.</div>

              <div class="paths-grid">
                <div v-for="cat in ['movies', 'series', 'anime']" :key="cat" class="path-cat-card" :id="'paths-card-' + cat">
                  <!-- Category header -->
                  <div class="path-cat-header">
                    <div
                      class="path-cat-icon"
                      :class="'cat-' + cat"
                    >
                      <i :class="cat === 'movies' ? 'ph ph-film-strip' : cat === 'series' ? 'ph ph-television' : 'ph ph-sparkle'"></i>
                    </div>
                    <div class="path-cat-title">
                      <span class="path-cat-name">{{ cat === 'anime' ? 'Anime' : cat.charAt(0).toUpperCase() + cat.slice(1) }}</span>
                      <span class="path-cat-count">
                        {{ (form.media_paths[cat] || []).length }} {{ (form.media_paths[cat] || []).length === 1 ? 'path' : 'paths' }}
                          <span v-if="(form.disabled_paths[cat] || []).length" style="color:var(--text-muted,#888);font-size:0.78em;margin-left:4px">({{ (form.disabled_paths[cat] || []).length }} disabled)</span>
                      </span>
                    </div>
                  </div>

                  <!-- Path list -->
                  <div class="path-list">
                    <div
                      v-for="(p, idx) in (form.media_paths[cat] || [])"
                      :key="idx"
                      class="path-list-item"
                      :class="{ 'path-disabled': (form.disabled_paths[cat] || []).includes(p) }"
                    >
                      <span
                        class="path-status-dot"
                        :class="pathStatuses[p] ? (pathStatuses[p].accessible ? 'ok' : 'bad') : 'unknown'"
                        :title="pathStatuses[p] ? (pathStatuses[p].accessible ? 'Connected — ' + pathStatuses[p].video_count + ' videos found' : 'Unmounted / Not Found') : 'Checking...'"
                      ></span>
                      <span class="path-text" :title="p">{{ p }}</span>
                      <span
                        v-if="pathStatuses[p]"
                        class="path-videos"
                        :class="pathStatuses[p].accessible ? 'ok' : 'bad'"
                      >
                        {{ pathStatuses[p].accessible ? pathStatuses[p].video_count + ' vids' : 'n/a' }}
                      </span>
                      <div class="path-actions">
                        <button class="path-act-btn" @click.stop="movePath(cat, idx, -1)" :disabled="idx === 0" title="Move Up">
                          <i class="ph ph-caret-up"></i>
                        </button>
                        <button class="path-act-btn" @click.stop="movePath(cat, idx, 1)" :disabled="idx === (form.media_paths[cat]?.length || 0) - 1" title="Move Down">
                          <i class="ph ph-caret-down"></i>
                        </button>
                        <button
                          class="path-act-btn toggle-btn"
                          @click.stop="togglePath(cat, idx)"
                          :title="(form.disabled_paths[cat] || []).includes(p) ? 'Enable this path' : 'Disable this path'"
                        >
                          <i :class="(form.disabled_paths[cat] || []).includes(p) ? 'ph ph-eye-slash' : 'ph ph-eye'"></i>
                        </button>
                        <button class="path-act-btn danger" @click.stop="removePath(cat, idx)" title="Remove Path">
                          <i class="ph ph-trash"></i>
                        </button>
                      </div>
                    </div>

                    <!-- Empty state -->
                    <div v-if="!(form.media_paths[cat] || []).length" class="path-empty">
                      <i class="ph ph-folder-plus"></i> No paths yet — add your first folder below
                    </div>
                  </div>

                  <!-- Add path row -->
                  <div class="path-add-row">
                    <input
                      type="text"
                      v-model="newPaths[cat]"
                      class="form-input path-add-input"
                      :placeholder="'D:/Entertainment/' + cat + '...'"
                      @keyup.enter="addPath(cat)"
                    />
                    <button class="path-add-btn" @click="handleBrowseFolder(cat)" :disabled="browsingFolder === cat" :id="'btn-browse-' + cat" title="Browse folders">
                      <i :class="browsingFolder === cat ? 'ph ph-circle-notch' : 'ph ph-folder-open'" :style="browsingFolder === cat ? 'animation:spin 1s linear infinite' : ''"></i>
                    </button>
                    <button class="path-add-btn primary" @click="addPath(cat)" title="Add Path">
                      <i class="ph ph-plus"></i>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 2b. Library & Scanning -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-file-video" style="color:var(--accent)"></i>
            <span>Library & Scanning</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Scan Library on Startup</div>
                <div class="settings-desc">Automatically scan your media folders for new files when you log in.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.library.scan_on_startup" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Auto-Scan Interval</div>
                <div class="settings-desc">Automatically scan the library on a schedule while the server is running. New episodes are announced with a toast.</div>
              </div>
              <select v-model.number="form.library.scan_interval_hours" class="form-input" style="width:160px">
                <option :value="0">Off</option>
                <option :value="1">Every hour</option>
                <option :value="6">Every 6 hours</option>
                <option :value="12">Every 12 hours</option>
                <option :value="24">Every 24 hours</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Manual Library Scan</div>
                <div class="settings-desc">Run a full disk scan now to pick up new files, refresh metadata, and apply any library changes.</div>
                <div v-if="store.scanRunning" style="font-size:0.8rem;color:var(--accent);font-weight:700;margin-top:4px">
                  Scan in progress…
                </div>
              </div>
              <button class="btn btn-primary btn-sm" @click="manualScan" :disabled="store.scanRunning" id="btn-settings-scan">
                <i :class="store.scanRunning ? 'ph ph-circle-notch' : 'ph ph-arrows-clockwise'" :style="store.scanRunning ? 'animation:spin 1s linear infinite' : ''" style="margin-right:6px"></i>
                {{ store.scanRunning ? 'Scanning…' : 'Scan Library Now' }}
              </button>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Skip Patterns</div>
                <div class="settings-desc">Comma-separated keywords — files or folders whose name contains any of these are ignored during scans (e.g. samples, trailers, extras).</div>
              </div>
              <input type="text" v-model="form.library.skip_patterns" class="form-input" style="width:280px" placeholder="sample,trailer,extras" />
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Detect Anime in Series</div>
                <div class="settings-desc">Scans your Series library against TMDb and moves Japanese animation shows (Animation genre + Japanese origin) to the Anime page — including every episode. Safe to re-run.</div>
                <div v-if="animeDetect.running" style="font-size:0.8rem;color:var(--accent);font-weight:700;margin-top:4px">
                  Scanning {{ animeDetect.processed }}/{{ animeDetect.total }} shows…
                </div>
                <div v-else-if="animeDetect.done && !animeDetect.error" style="font-size:0.8rem;color:var(--text-muted);margin-top:4px">
                  Last run: {{ animeDetect.reclassified }} show(s) moved to Anime.
                </div>
                <div v-else-if="animeDetect.error" style="font-size:0.8rem;color:#ef4444;margin-top:4px">
                  Error: {{ animeDetect.error }}
                </div>
              </div>
              <button class="btn btn-primary btn-sm" @click="startAnimeDetect" :disabled="animeDetect.running" id="btn-detect-anime">
                <i :class="animeDetect.running ? 'ph ph-circle-notch' : 'ph ph-magic-wand'" :style="animeDetect.running ? 'animation:spin 1s linear infinite' : ''" style="margin-right:6px"></i>
                {{ animeDetect.running ? 'Detecting…' : 'Detect Anime' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 2c. Unmatched Media & Fix Match Inspector -->
        <div class="settings-section" id="settings-unmatched-section">
          <div class="settings-section-title" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <div style="display:flex;align-items:center;gap:8px">
              <i class="ph ph-warning-circle" style="color:var(--accent)"></i>
              <span>Unmatched Media & Fix Match</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <span class="unmatched-count-badge" v-if="unmatchedList.length > 0">
                <i class="ph ph-warning"></i> {{ unmatchedList.length }} Unmatched
              </span>
              <button class="btn btn-secondary btn-sm" @click="loadUnmatched" :disabled="loadingUnmatched" id="btn-refresh-unmatched">
                <i :class="loadingUnmatched ? 'ph ph-circle-notch' : 'ph ph-arrows-clockwise'" :style="loadingUnmatched ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
                {{ loadingUnmatched ? 'Refreshing...' : 'Refresh List' }}
              </button>
            </div>
          </div>

          <div class="settings-group">
            <div class="settings-desc" style="margin-bottom:1rem">
              Files in your scanned media directories that could not be automatically matched to TMDb. Click <strong>Fix Match</strong> to search and link them to the correct movie or TV show.
            </div>

            <div v-if="loadingUnmatched" style="display:flex;justify-content:center;padding:2rem">
              <div class="loading-spinner"></div>
            </div>

            <div v-else-if="unmatchedList.length === 0" style="padding:1.5rem;text-align:center;background:rgba(255,255,255,0.02);border-radius:12px;border:1px dashed rgba(255,255,255,0.1)">
              <div style="font-size:1.5rem;margin-bottom:4px">🎉</div>
              <div style="font-weight:700;color:var(--text-primary)">All Library Media Matched!</div>
              <div style="font-size:0.8rem;color:var(--text-muted)">There are currently no unmatched items in your library.</div>
            </div>

            <div v-else class="unmatched-container">
              <table class="unmatched-table">
                <thead>
                  <tr>
                    <th>Title / Guess</th>
                    <th>Type</th>
                    <th>File Path</th>
                    <th>Size</th>
                    <th style="text-align:right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in unmatchedList" :key="item.id">
                    <td class="unmatched-title-cell" :title="item.title">
                      {{ item.title }}
                      <span v-if="item.year" style="color:var(--text-muted);font-weight:normal"> ({{ item.year }})</span>
                    </td>
                    <td>
                      <span class="badge" style="text-transform:capitalize;font-size:0.75rem">{{ item.type }}</span>
                    </td>
                    <td class="unmatched-path-cell" :title="item.file_path">
                      {{ item.file_path }}
                    </td>
                    <td style="color:var(--text-muted);font-size:0.8rem">
                      {{ formatFileSize(item.file_size) }}
                    </td>
                    <td style="text-align:right">
                      <button class="btn btn-primary btn-sm" @click="openFixMatchForItem(item)">
                        <i class="ph ph-magic-wand" style="margin-right:4px"></i> Fix Match
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- 2d. Outgoing Network Activity & Request Inspector -->
        <div class="settings-section" id="settings-network-section">
          <div class="settings-section-title" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <div style="display:flex;align-items:center;gap:8px">
              <i class="ph ph-broadcast" style="color:var(--accent)"></i>
              <span>Outgoing Network Activity & Request Inspector</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <button class="btn btn-secondary btn-sm" @click="loadNetworkRequests" :disabled="loadingNetwork" id="btn-refresh-network">
                <i :class="loadingNetwork ? 'ph ph-circle-notch' : 'ph ph-arrows-clockwise'" :style="loadingNetwork ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
                {{ loadingNetwork ? 'Refreshing...' : 'Refresh Log' }}
              </button>
              <button class="btn btn-ghost btn-sm" @click="clearNetworkRequests" :disabled="!networkList.length" id="btn-clear-network" title="Clear recorded requests">
                <i class="ph ph-trash" style="margin-right:4px"></i> Clear Log
              </button>
            </div>
          </div>

          <div class="settings-group">
            <div class="network-inspector-container">
              <!-- Summary bar -->
              <div class="network-summary-bar">
                <div class="network-metric-chip">
                  <span class="metric-label">Total Outgoing:</span>
                  <span class="metric-val">{{ networkSummary.total || 0 }}</span>
                </div>
                <div class="network-metric-chip">
                  <span class="metric-label">Success Rate:</span>
                  <span class="metric-val" :style="{ color: networkSummary.failed > 0 ? '#fbbf24' : '#10b981' }">
                    {{ networkSummary.success_rate || 100 }}% ({{ networkSummary.success || 0 }}/{{ networkSummary.total || 0 }})
                  </span>
                </div>
                <div class="network-metric-chip">
                  <span class="metric-label">Avg Latency:</span>
                  <span class="metric-val" style="color:#38bdf8">{{ networkSummary.avg_latency_ms || 0 }} ms</span>
                </div>
                <div class="network-metric-chip" style="margin-left:auto">
                  <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.78rem;color:var(--text-secondary)">
                    <input type="checkbox" v-model="networkAutoRefresh" style="cursor:pointer" />
                    <span>Auto-Refresh (3s)</span>
                  </label>
                </div>
              </div>

              <!-- Filter Toolbar -->
              <div class="network-toolbar">
                <div class="network-filters">
                  <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">Service:</span>
                  <select v-model="networkServiceFilter" class="form-input" style="font-size:0.8rem;padding:4px 8px;width:150px">
                    <option value="all">All Services</option>
                    <option value="TMDb API">TMDb API</option>
                    <option value="TMDb CDN">TMDb CDN (Images)</option>
                    <option value="OpenSubtitles">OpenSubtitles</option>
                    <option value="AniSkip">AniSkip</option>
                    <option value="Jikan / MAL">Jikan / MAL</option>
                    <option value="GitHub">GitHub</option>
                    <option value="YTS Subs">YTS Subs</option>
                  </select>

                  <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600;margin-left:6px">Status:</span>
                  <select v-model="networkStatusFilter" class="form-input" style="font-size:0.8rem;padding:4px 8px;width:120px">
                    <option value="all">All Status</option>
                    <option value="success">Success (2xx/3xx)</option>
                    <option value="error">Errors / Failed</option>
                  </select>
                </div>
                <div style="font-size:0.76rem;color:var(--text-muted)">
                  Showing {{ filteredNetworkList.length }} recorded requests
                </div>
              </div>

              <!-- Request Table -->
              <div class="network-table-wrap">
                <div v-if="loadingNetwork && !networkList.length" style="padding:2.5rem;text-align:center">
                  <div class="loading-spinner"></div>
                </div>

                <div v-else-if="!filteredNetworkList.length" style="padding:2rem;text-align:center;color:var(--text-muted)">
                  <i class="ph ph-broadcast" style="font-size:1.8rem;opacity:0.4;margin-bottom:6px;display:block"></i>
                  <span>No outgoing HTTP requests recorded yet. Trigger a library scan, metadata refresh, or search to record activity.</span>
                </div>

                <table v-else class="network-table">
                  <thead>
                    <tr>
                      <th style="width:75px">Time</th>
                      <th style="width:130px">Service</th>
                      <th style="width:65px">Method</th>
                      <th>Target URL</th>
                      <th style="width:90px">Status</th>
                      <th style="width:85px;text-align:right">Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="req in filteredNetworkList" :key="req.id">
                      <td style="color:var(--text-muted);font-family:monospace;font-size:0.75rem">{{ req.timestamp }}</td>
                      <td>
                        <span class="network-service-badge" :class="getServiceBadgeClass(req.service)">
                          {{ req.service }}
                        </span>
                      </td>
                      <td>
                        <span class="network-method-tag">{{ req.method }}</span>
                      </td>
                      <td>
                        <div class="network-url-text" :title="req.url">
                          {{ req.url }}
                        </div>
                      </td>
                      <td>
                        <span class="network-status-tag" :class="req.ok ? 'ok' : 'err'" :title="req.error || ''">
                          {{ req.status_code || 'ERR' }}
                        </span>
                      </td>
                      <td style="text-align:right">
                        <span class="network-latency-text">{{ req.duration_ms }} ms</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <!-- 3. Subtitles & Player Defaults -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-subtitles" style="color:var(--accent)"></i>
            <span>Player & Subtitle Defaults</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Subtitles — Auto Load</div>
                <div class="settings-desc">Automatically enable and show subtitles on video start if available.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.subtitles.auto_load" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Subtitles — Preferred Language</div>
                <div class="settings-desc">Default language track selected when loading video subtitles.</div>
              </div>
              <select v-model="form.subtitles.preferred_language" class="form-input" style="width:160px">
                <option value="Auto">Auto (Default)</option>
                <option value="en">English</option>
                <option value="es">Spanish</option>
                <option value="fr">French</option>
                <option value="ja">Japanese</option>
                <option value="de">German</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Auto Play Next Episode</div>
                <div class="settings-desc">Automatically play the next episode when the current one finishes.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.playback.auto_play_next" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Auto-Skip Intro & Recap</div>
                <div class="settings-desc">Automatically skip intro, recap, and outro ranges when video playback enters their timestamp window.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.playback.auto_skip_intro" id="setting-auto-skip-toggle" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Resume Behavior</div>
                <div class="settings-desc">What to do when a video has saved watch progress.</div>
              </div>
              <select v-model="form.playback.resume_behavior" class="form-input" style="width:220px">
                <option value="ask">Ask Every Time</option>
                <option value="always">Always Resume</option>
                <option value="never">Always Start Over</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Default Speed</div>
                <div class="settings-desc">Playback speed applied when a video starts.</div>
              </div>
              <select v-model.number="form.playback.default_speed" class="form-input" style="width:140px">
                <option :value="0.5">0.5x</option>
                <option :value="0.75">0.75x</option>
                <option :value="1">1x (Normal)</option>
                <option :value="1.25">1.25x</option>
                <option :value="1.5">1.5x</option>
                <option :value="2">2x</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Auto-Fullscreen</div>
                <div class="settings-desc">Automatically enter fullscreen mode when video playback starts.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.playback.auto_fullscreen" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Start Muted</div>
                <div class="settings-desc">Launch videos muted regardless of the default volume level.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.playback.start_muted" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Subtitles — Font Size</div>
                <div class="settings-desc">Default font size scaling for subtitle text in the player.</div>
              </div>
              <select v-model="form.subtitles.font_size" class="form-input" style="width:160px">
                <option value="small">Small (75%)</option>
                <option value="normal">Normal (100%)</option>
                <option value="large">Large (125%)</option>
                <option value="extra-large">Extra Large (150%)</option>
              </select>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">OpenSubtitles API Key</div>
                <div class="settings-desc">Enables automatic subtitle downloads matched to your exact files. Free key at opensubtitles.com/api — free accounts allow 5 downloads per day.</div>
              </div>
              <input type="password" v-model="form.subtitles.opensubtitles_api_key" class="form-input" placeholder="Paste your OpenSubtitles API key..." style="width:280px" />
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Subtitles — Auto-Download</div>
                <div class="settings-desc">When opening a title with no subtitles available, automatically search OpenSubtitles and download one in your preferred language.</div>
              </div>
              <label class="toggle-switch">
                <input type="checkbox" v-model="form.subtitles.auto_download" />
                <span class="toggle-slider"></span>
              </label>
            </div>

            <div class="settings-row" style="flex-direction:column;align-items:flex-start">
              <div class="settings-label-container">
                <div class="settings-label">Subtitles — Appearance</div>
                <div class="settings-desc">Default subtitle text color, size, and background box opacity in the player.</div>
              </div>
              <div style="display:flex;flex-direction:column;gap:12px;margin-top:10px;width:100%">
                <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                  <span style="font-size:0.78rem;font-weight:700;color:var(--text-secondary);min-width:110px">Text Color</span>
                  <button
                    v-for="c in ['#ffffff', '#ffd700', '#4cc2ff', '#4ade80']"
                    :key="c"
                    @click="form.subtitles.appearance.textColor = c"
                    :style="{
                      width: '26px', height: '26px', borderRadius: '50%', cursor: 'pointer',
                      background: c, border: form.subtitles.appearance.textColor === c ? '2px solid var(--accent)' : '2px solid var(--border-subtle)'
                    }"
                    :title="c"
                  ></button>
                </div>
                <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                  <span style="font-size:0.78rem;font-weight:700;color:var(--text-secondary);min-width:110px">Text Size</span>
                  <button
                    v-for="s in [
                      { label: 'S', v: '0.85rem' },
                      { label: 'M', v: '1.1rem' },
                      { label: 'L', v: '1.4rem' },
                      { label: 'XL', v: '1.8rem' },
                    ]"
                    :key="s.v"
                    class="btn btn-sm"
                    :class="form.subtitles.appearance.fontSize === s.v ? 'btn-primary' : 'btn-secondary'"
                    @click="form.subtitles.appearance.fontSize = s.v"
                    style="min-width:38px"
                  >{{ s.label }}</button>
                </div>
                <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
                  <span style="font-size:0.78rem;font-weight:700;color:var(--text-secondary);min-width:110px">Box Opacity</span>
                  <button
                    v-for="o in [
                      { label: 'Off', v: 0 },
                      { label: '50%', v: 0.5 },
                      { label: 'Solid', v: 0.85 },
                    ]"
                    :key="o.v"
                    class="btn btn-sm"
                    :class="form.subtitles.appearance.bgOpacity === o.v ? 'btn-primary' : 'btn-secondary'"
                    @click="form.subtitles.appearance.bgOpacity = o.v"
                    style="min-width:56px"
                  >{{ o.label }}</button>
                </div>
              </div>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Seek Step (Seconds)</div>
                <div class="settings-desc">Time in seconds skipped when pressing Arrow Left/Right or skip buttons.</div>
              </div>
              <input type="number" v-model.number="form.playback.seek_step" min="1" max="60" class="form-input" style="width:120px" />
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Playback — Default Volume</div>
                <div class="settings-desc">Initial volume level when launching the video player.</div>
              </div>
              <div style="display:flex;align-items:center;gap:12px;width:240px">
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  :value="volumePercent"
                  @input="setVolumePercent($event.target.value)"
                  class="form-range-slider"
                  id="setting-default-volume-slider"
                  :style="{ flex: 1, '--range-progress': volumePercent + '%' }"
                />
                <span style="min-width:48px;font-weight:700;font-size:0.85rem;color:var(--accent);text-align:right">
                  {{ volumePercent }}%
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 4. Cache & Storage Management -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-hard-drive" style="color:var(--accent)"></i>
            <span>Cache & Storage Management</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Cached Metadata & Images</div>
                <div class="settings-desc">Cached posters, backdrops, and JSON metadata stored on disk.</div>
                <div style="font-size:0.85rem;color:var(--text-primary);font-weight:700;margin-top:4px">
                  Current Cache Usage: <span style="color:var(--accent)">{{ cacheInfo.size_formatted || '0 KB' }}</span> ({{ cacheInfo.file_count || 0 }} files)
                </div>
              </div>
              <button class="btn btn-secondary" @click="handleClearCache" :disabled="clearingCache" id="btn-clear-cache">
                <i class="ph ph-trash-simple" style="margin-right:6px"></i>
                {{ clearingCache ? 'Clearing...' : 'Clear Cache' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 5. Backup & Restore -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-archive-box" style="color:var(--accent)"></i>
            <span>Backup & Restore</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Download Backup</div>
                <div class="settings-desc">Exports your settings and library database (watch history, skip markers, profiles, collections, achievements) as a zip file.</div>
                <label style="display:flex;align-items:center;gap:7px;margin:6px 0 0;font-size:0.75rem;color:var(--text-muted);cursor:pointer">
                  <input type="checkbox" v-model="backupIncludeMetadata" />
                  Include metadata cache (posters & artwork — can be large)
                </label>
              </div>
              <a class="btn btn-primary btn-sm" :href="'/api/system/backup?include_metadata=' + (backupIncludeMetadata ? 1 : 0)" id="btn-download-backup">
                <i class="ph ph-download-simple" style="margin-right:6px"></i> Download Backup
              </a>
            </div>

            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label">Restore From Backup</div>
                <div class="settings-desc">Upload a backup zip to restore settings and/or the library database. The current config is kept in <code>data/pre_restore/</code>. Database restores apply on the next server start.</div>
                <div v-if="restoreResult" style="font-size:0.8rem;margin-top:4px" :style="{ color: restoreResult.ok ? '#10b981' : '#ef4444' }">
                  {{ restoreResult.message }}
                </div>
              </div>
              <label class="btn btn-secondary btn-sm" style="cursor:pointer" :id="'btn-restore-upload'">
                <i class="ph ph-upload-simple" style="margin-right:6px"></i> Upload Backup
                <input type="file" accept=".zip" style="display:none" @change="restoreFromBackup" />
              </label>
            </div>
          </div>
        </div>

        <!-- 6. Parental Controls & Kids Screen Time -->
        <div class="settings-section">
          <div class="settings-section-title">
            <i class="ph ph-shield-check" style="color:#fdcb6e"></i>
            <span>Parental Controls & Kids Screen Time</span>
          </div>
          <div class="settings-group">
            <div v-if="!kidsProfiles.length" style="padding:1.25rem;color:var(--text-muted);font-size:0.9rem">
              No Kids profiles created yet. Create or edit a profile in <router-link to="/profiles?manage=true" style="color:var(--accent);font-weight:700">Manage Profiles</router-link> to set daily cartoon time limits and bedtime curfews.
            </div>
            <div v-else>
              <div v-for="kp in kidsProfiles" :key="kp.id" class="settings-row" style="align-items:flex-start">
                <div class="settings-label-container">
                  <div class="settings-label" style="display:flex;align-items:center;gap:8px">
                    <span>{{ kp.avatar }} {{ kp.name }}</span>
                    <span style="font-size:0.75rem;background:rgba(253,203,110,0.15);color:#fdcb6e;padding:2px 8px;border-radius:12px;font-weight:700">🧒 Kids Profile</span>
                  </div>
                  <div class="settings-desc">Set daily watch limits and evening bedtime curfew for {{ kp.name }}. Changes save automatically when you select a value.</div>
                </div>
                <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
                  <div>
                    <label style="display:block;font-size:0.75rem;color:var(--text-muted);margin-bottom:4px;font-weight:600">Daily Limit</label>
                    <select v-model.number="kp.daily_limit_minutes" class="form-input" style="min-width:140px;font-size:0.85rem">
                      <option :value="0">No Limit</option>
                      <option :value="30">30 Mins / day</option>
                      <option :value="45">45 Mins / day</option>
                      <option :value="60">1 Hour / day</option>
                      <option :value="90">1.5 Hours / day</option>
                      <option :value="120">2 Hours / day</option>
                      <option :value="180">3 Hours / day</option>
                    </select>
                  </div>
                  <div>
                    <label style="display:block;font-size:0.75rem;color:var(--text-muted);margin-bottom:4px;font-weight:600">Bedtime Curfew</label>
                    <select v-model="kp.bedtime_curfew" class="form-input" style="min-width:140px;font-size:0.85rem">
                      <option value="">Off (None)</option>
                      <option value="19:00">7:00 PM</option>
                      <option value="19:30">7:30 PM</option>
                      <option value="20:00">8:00 PM</option>
                      <option value="20:30">8:30 PM</option>
                      <option value="21:00">9:00 PM</option>
                      <option value="21:30">9:30 PM</option>
                      <option value="22:00">10:00 PM</option>
                    </select>
                  </div>
                  <div style="display:flex;align-items:flex-end">
                    <button
                      class="btn btn-primary"
                      style="font-size:0.82rem;padding:7px 14px;height:auto"
                      @click="saveKidsProfileLimits(kp)"
                      :id="'btn-save-kids-' + kp.id"
                    >
                      <i class="ph ph-floppy-disk" style="margin-right:5px"></i> Save
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 7. Fresh Start (Full System Reset) -->
        <div class="settings-section" style="border:1px solid rgba(229,9,20,0.3);background:rgba(229,9,20,0.04)">
          <div class="settings-section-title">
            <i class="ph ph-warning-circle" style="color:var(--accent)"></i>
            <span style="color:var(--accent)">Fresh Start & System Reset</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label" style="color:var(--accent)">Full Application Reset</div>
                <div class="settings-desc">Unlinks external drive locations (e.g. E:/MOVIES, D:/Entertainment), resets media paths to local defaults, clears metadata cache, and wipes database.</div>
              </div>
              <button class="btn btn-primary danger" @click="showResetModal = true" :disabled="resetting" id="btn-fresh-start">
                <i class="ph ph-arrows-counter-clockwise" style="margin-right:6px"></i>
                Fresh Start Reset
              </button>
            </div>
          </div>
        </div>

        <!-- 8. Server Control & Shutdown -->
        <div class="settings-section" id="settings-shutdown-section" style="border:1px solid rgba(239,68,68,0.35);background:rgba(239,68,68,0.04)">
          <div class="settings-section-title">
            <i class="ph ph-power" style="color:#ef4444"></i>
            <span style="color:#ef4444">Server Control & Shutdown</span>
          </div>
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-label-container">
                <div class="settings-label" style="color:var(--text-primary);display:flex;align-items:center;gap:8px">
                  <span>Shutdown CapsStream Server</span>
                  <span class="server-status-pill online" style="font-size:0.7rem;padding:2px 8px">
                    <span class="status-dot"></span> Active
                  </span>
                </div>
                <div class="settings-desc">Gracefully stops the backend server process, flushes SQLite databases, and closes the browser window cleanly.</div>
              </div>
              <button class="btn btn-primary danger" @click="showShutdownModal = true" id="btn-open-shutdown">
                <i class="ph ph-power" style="margin-right:6px"></i>
                Shutdown Server
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Shutdown Confirmation Modal -->
      <div v-if="showShutdownModal" class="modal-backdrop" style="z-index:500;background:rgba(0,0,0,0.85);backdrop-filter:blur(16px);" @click.self="showShutdownModal = false">
        <div class="shortcuts-modal-card" style="max-width:480px" @click.stop>
          <div class="shortcuts-modal-inner" style="text-align:left">
            <div class="shortcuts-modal-header" style="margin-bottom:1rem;border-bottom-color:rgba(239,68,68,0.3)">
              <div class="shortcuts-header-title" style="color:#ef4444">
                <i class="ph ph-power" style="font-size:1.6rem"></i>
                <span>Shutdown Server?</span>
              </div>
              <button class="shortcuts-close-btn" @click="showShutdownModal = false">
                <i class="ph ph-x"></i>
              </button>
            </div>

            <div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.5;margin-bottom:1rem">
              Are you sure you want to stop the CapsStream server? This will stop all active streams and background tasks.
            </div>

            <div class="shortcuts-modal-footer" style="margin-top:1.5rem;display:flex;justify-content:flex-end;gap:10px">
              <button class="btn btn-secondary" @click="showShutdownModal = false">Cancel</button>
              <button class="btn btn-primary danger" @click="executeShutdown" id="btn-confirm-shutdown">
                <i class="ph ph-power" style="margin-right:6px"></i> Yes, Shutdown Server
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Fullscreen Shutdown Overlay -->
      <div v-if="isShuttingDown" class="shutdown-overlay">
        <div class="shutdown-modal-box">
          <div class="shutdown-icon-wrap" :class="{ offline: shutdownCompleted }">
            <i :class="shutdownCompleted ? 'ph ph-check-circle' : 'ph ph-power'"></i>
          </div>

          <h2 class="shutdown-title">
            {{ shutdownCompleted ? 'Server Offline' : 'Shutting Down Server...' }}
          </h2>

          <p class="shutdown-desc">
            {{ shutdownCompleted 
                ? 'The CapsStream server has stopped cleanly. You may now safely close this browser tab or window.' 
                : 'Saving database state and closing active background workers.' }}
          </p>

          <div v-if="!shutdownCompleted" class="shutdown-countdown-pill">
            <i class="ph ph-hourglass-medium"></i>
            <span>Closing window in {{ shutdownCountdown }}s</span>
          </div>

          <div class="shutdown-hint-box" v-if="shutdownCompleted">
            <span>To start CapsStream again, launch <strong>start.bat</strong> or <strong>Start CapsStream Silent.vbs</strong> in your project folder.</span>
          </div>

          <div v-if="shutdownCompleted" style="margin-top:0.5rem">
            <button class="btn btn-secondary btn-lg" @click="closeCurrentWindow">
              <i class="ph ph-x-circle" style="margin-right:6px"></i> Close Window
            </button>
          </div>
        </div>
      </div>

      <!-- Fresh Start Warning & Confirmation Modal -->
      <div v-if="showResetModal" class="modal-backdrop" style="z-index:500;background:rgba(0,0,0,0.85);backdrop-filter:blur(16px);" @click.self="showResetModal = false">
        <div class="shortcuts-modal-card" style="max-width:520px" @click.stop>
          <div class="shortcuts-modal-inner" style="text-align:left">
            <div class="shortcuts-modal-header" style="margin-bottom:1rem;border-bottom-color:rgba(229,9,20,0.3)">
              <div class="shortcuts-header-title" style="color:var(--accent)">
                <i class="ph ph-warning-octagon" style="font-size:1.6rem"></i>
                <span>⚠️ Fresh Start Warning</span>
              </div>
              <button class="shortcuts-close-btn" @click="showResetModal = false">
                <i class="ph ph-x"></i>
              </button>
            </div>

            <div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.5;margin-bottom:1rem">
              This action will perform a complete system reset of CapsStream. Please review the changes below:
            </div>

            <div class="settings-group" style="background:rgba(0,0,0,0.3);padding:1rem;border-radius:8px;margin-bottom:1.25rem">
              <div style="font-size:0.85rem;color:var(--text-primary);margin-bottom:6px"><strong>What will be done:</strong></div>
              <ul style="font-size:0.82rem;color:var(--text-secondary);line-height:1.6;list-style:disc;padding-left:1.25rem">
                <li><strong>Clears media paths</strong> — you'll re-add your own media sources afterwards.</li>
                <li><strong>Wipes database</strong>, deleting profiles, watch progress, watchlists, and custom collections.</li>
                <li><strong>Clears metadata cache</strong> (cached poster images and JSON files).</li>
              </ul>

              <div style="margin-top:1rem;padding-top:0.75rem;border-top:1px dashed rgba(255,255,255,0.1)">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.85rem;color:var(--accent);font-weight:700">
                  <input type="checkbox" v-model="clearMediaFiles" style="width:18px;height:18px;cursor:pointer">
                  <span>Also delete leftover files inside the local <code>media</code> folder</span>
                </label>
              </div>
            </div>

            <div class="form-group" style="margin-bottom:1.25rem">
              <label class="form-label" style="font-size:0.85rem">To confirm, type <strong style="color:var(--accent)">RESET</strong> below:</label>
              <input type="text" v-model="resetConfirmText" class="form-input" placeholder="Type RESET to confirm" style="text-transform:uppercase" id="reset-confirm-input" />
            </div>

            <div style="display:flex;gap:0.75rem;justify-content:flex-end">
              <button class="btn btn-ghost" @click="showResetModal = false">Cancel</button>
              <button class="btn btn-primary danger" :disabled="resetConfirmText.trim().toUpperCase() !== 'RESET' || resetting" @click="confirmFreshStart" id="btn-confirm-reset">
                {{ resetting ? 'Wiping & Resetting...' : 'Confirm Fresh Start & Reset' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Floating Bottom-Right Save Action Bar (only when changes are pending) -->
      <transition name="fade">
        <div class="settings-floating-bar" id="settings-floating-bar" v-if="isDirty || saving">
          <div class="settings-floating-status">
            <span :class="isDirty ? 'settings-pulse-dot warning' : 'settings-pulse-dot success'"></span>
            <span style="font-size:0.85rem;font-weight:700;color:var(--text-primary)">
              {{ saving ? 'Saving configuration...' : 'Unsaved Settings Changes' }}
            </span>
          </div>
          <button class="btn btn-primary" @click="saveSettings" :disabled="saving" id="floating-save-settings-btn">
            <i class="ph ph-floppy-disk" style="margin-right:6px"></i>
            {{ saving ? 'Saving...' : 'Save Settings' }}
          </button>
        </div>
      </transition>
    </div>
  `,
  setup() {
    const loading = ref(true);
    const saving = ref(false);
    const testingApi = ref(null);
    const newPaths = ref({ movies: "", series: "", anime: "" });

    const form = ref({
      browser: "edge",
      tmdb_api_key: "264a7dcdd8291a83c4a51727755343bc",
      hide_system_files: false,
      launch_browser_on_start: true,
      host: "127.0.0.1",
      port: 8000,
      metadata_sources: { enable_jikan: true },
      media_paths: {
        movies: [],
        series: [],
        anime: [],
      },
      disabled_paths: {
        movies: [],
        series: [],
        anime: [],
      },
      library: {
        scan_on_startup: true,
        scan_interval_hours: 0,
        skip_patterns: "sample,trailer",
      },
      updates: {
        auto_check: true,
      },
      subtitles: {
        auto_load: true,
        preferred_language: "Auto",
        font_size: "normal",
        opensubtitles_api_key: "",
        auto_download: false,
        appearance: { fontSize: "1.1rem", textColor: "#ffffff", bgOpacity: 0.5 },
      },
      playback: {
        auto_play_next: true,
        auto_skip_intro: false,
        seek_step: 10,
        default_volume: 1,
        default_speed: 1,
        resume_behavior: "ask",
        auto_fullscreen: false,
        start_muted: false,
      },
    });

    // Built-in default media folders were removed — all paths are user-provided.

    const initialFormJson = ref("");
    const showUnsavedModal = ref(false);
    const pendingNextRoute = ref(null);

    const isDirty = computed(() => {
      if (loading.value || !initialFormJson.value) return false;
      return JSON.stringify(form.value) !== initialFormJson.value;
    });

    const browsingFolder = ref(null);
    const pathStatuses = ref({});

    async function validatePaths() {
      const allPaths = [
        ...(form.value.media_paths.movies || []),
        ...(form.value.media_paths.series || []),
        ...(form.value.media_paths.anime || []),
      ];
      if (!allPaths.length) return;
      try {
        const res = await API.post("/api/system/validate-paths", { paths: allPaths });
        if (res) pathStatuses.value = res;
      } catch (e) {}
    }

    async function handleBrowseFolder(cat) {
      browsingFolder.value = cat;
      try {
        const res = await API.post("/api/system/browse-folder");
        if (res && res.ok && res.path) {
          newPaths.value[cat] = res.path;
          addPath(cat);
          await validatePaths();
        }
      } catch (e) {
        addToast("Failed to open folder picker", "error");
      } finally {
        browsingFolder.value = null;
      }
    }

    async function loadSettings() {
      loading.value = true;
      try {
        const data = await API.get("/api/settings");
        if (data) {
          form.value = {
            ...form.value,
            ...data,
            metadata_sources: { ...form.value.metadata_sources, ...(data.metadata_sources || {}) },
            media_paths: { ...form.value.media_paths, ...(data.media_paths || {}) },
            disabled_paths: {
              movies: [...(data.disabled_paths?.movies || [])],
              series: [...(data.disabled_paths?.series || [])],
              anime:  [...(data.disabled_paths?.anime  || [])],
            },
            library: { ...form.value.library, ...(data.library || {}) },
            updates: { ...form.value.updates, ...(data.updates || {}) },
            subtitles: {
              ...form.value.subtitles,
              ...(data.subtitles || {}),
              appearance: { ...form.value.subtitles.appearance, ...(data.subtitles?.appearance || {}) },
            },
            playback: { ...form.value.playback, ...(data.playback || {}) },
          };
        }
        initialFormJson.value = JSON.stringify(form.value);
        await validatePaths();
      } catch (e) {
        addToast("Failed to load settings", "error");
      } finally {
        loading.value = false;
      }
    }

    async function saveSettings() {
      saving.value = true;
      try {
        await API.post("/api/settings", form.value);
        initialFormJson.value = JSON.stringify(form.value);
        addToast("Settings saved successfully ✓", "success");
        return true;
      } catch (e) {
        addToast("Failed to save settings", "error");
        return false;
      } finally {
        saving.value = false;
      }
    }

    async function saveAndLeave() {
      const ok = await saveSettings();
      if (ok) {
        showUnsavedModal.value = false;
        const target = pendingNextRoute.value;
        pendingNextRoute.value = null;
        if (target) {
          router.push(target);
        }
      }
    }

    function discardAndLeave() {
      initialFormJson.value = JSON.stringify(form.value);
      showUnsavedModal.value = false;
      const target = pendingNextRoute.value;
      pendingNextRoute.value = null;
      if (target) {
        router.push(target);
      }
    }

    function cancelLeave() {
      showUnsavedModal.value = false;
      pendingNextRoute.value = null;
    }

    if (typeof VueRouter !== "undefined" && VueRouter.onBeforeRouteLeave) {
      VueRouter.onBeforeRouteLeave((to, from) => {
        if (isDirty.value && !saving.value) {
          showUnsavedModal.value = true;
          pendingNextRoute.value = to;
          return false;
        }
        return true;
      });
    }

    function handleBeforeUnload(e) {
      if (isDirty.value) {
        e.preventDefault();
        e.returnValue = "You have unsaved settings changes.";
      }
    }

    // ─── Updates ──────────────────────────────────────────────
    const sysInfo = ref(null);
    const updateState = ref({
      status: "idle",
      current: "",
      latest: "",
      changelog: "",
      last_checked: "",
      message: "",
    });
    const updateChecking = ref(false);
      const updateInstalling = ref(false);
      const restartPending = ref(false);

    async function loadSystemInfo() {
      try {
        sysInfo.value = await API.get("/api/system/info");
      } catch (e) {}
    }

    // ─── Changelog rendering: safe markdown → HTML ───────────
    // Escapes everything first, then re-adds a small whitelist:
    // headers, bullet lists, **bold**, *italic*, `code`.
    function renderChangelog(md) {
      if (!md) return "";
      const esc = String(md).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const inline = (s) => s
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
        .replace(/`([^`]+)`/g, '<code class="cl-code">$1</code>');

      let html = "";
      let inList = false;
      const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };

      for (const raw of esc.split(/\r?\n/)) {
        const t = raw.trim();
        if (!t) { closeList(); continue; }

        const h = t.match(/^(#{1,4})\s+(.*)$/);
        if (h) {
          closeList();
          const lvl = Math.min(h[1].length + 2, 6);
          html += `<h${lvl} class="cl-h">${inline(h[2])}</h${lvl}>`;
          continue;
        }

        if (/^[-*•]\s+/.test(t)) {
          if (!inList) { html += '<ul class="cl-list">'; inList = true; }
          html += `<li>${inline(t.replace(/^[-*•]\s+/, ""))}</li>`;
          continue;
        }

        closeList();
        html += `<p class="cl-p">${inline(t)}</p>`;
      }
      closeList();
      return html;
    }

    const changelogHtml = computed(() => renderChangelog(updateState.value.changelog));

    async function checkUpdates() {
      updateChecking.value = true;
      updateState.value = { ...updateState.value, status: "checking", message: "Checking for updates..." };
      try {
        await loadSystemInfo();
        const r = await API.get("/api/system/check-update");
        const pend = r.pending_swaps || 0;
        const pendNote = pend
          ? ` ${pend} updated file(s) will be finalized next time you run start.bat.`
          : "";
        updateState.value = {
          status: r.status || "error",
          current: r.current || (sysInfo.value?.version || ""),
          latest: r.latest || "",
          changelog: r.changelog || "",
          last_checked: r.last_checked || "",
          message:
            r.status === "available" ? `Update available — v${r.latest}` :
            r.status === "up_to_date" ? ("You're up to date." + pendNote) :
            "Could not check for updates. Is GITHUB_REPO configured in backend/updater.py?",
        };
      } catch (e) {
        updateState.value = { ...updateState.value, status: "error", message: "Update check failed: " + (e.message || "unknown error") };
      } finally {
        updateChecking.value = false;
      }
    }

    const updateProgress = ref(null);
    let progressTimer = null;

    function pollUpdateProgress() {
      if (progressTimer) clearInterval(progressTimer);
      progressTimer = setInterval(async () => {
        try {
          const p = await API.get("/api/system/update-progress");
          updateProgress.value = p;
          const stage = p.stage || "idle";
          if (!updateInstalling.value && !restartPending.value) {
            // Update finished or failed elsewhere — stop polling
            if (stage === "idle" || stage === "done" || stage === "failed") {
              clearInterval(progressTimer);
              progressTimer = null;
            }
          }
        } catch (e) {}
      }, 1000);
    }

    async function restartAfterUpdate() {
      restartPending.value = true;
      try {
        await API.post("/api/system/restart-after-update", {});
        updateState.value = { ...updateState.value, message: "Restarting — the server will come back in a few seconds…" };
        // Poll until the server comes back, then hard-reload
        const check = setInterval(async () => {
          try {
            await fetch("/api/system/info", { cache: "no-store" });
            clearInterval(check);
            location.href = location.origin + location.pathname + "?v=" + Date.now();
          } catch (e) {}
        }, 1500);
      } catch (e) {
        addToast(e.message || "Restart failed", "error");
        restartPending.value = false;
      }
    }

    async function installUpdate() {
      updateInstalling.value = true;
      updateProgress.value = null;
      pollUpdateProgress();
      try {
        const r = await API.post("/api/system/apply-update", {});
        if (r.success && r.ui_only) {
          updateState.value = { ...updateState.value, status: "up_to_date", message: "Update installed — reloading…" };
          setTimeout(() => {
            // Hard, cache-busting reload so the new UI appears immediately
            location.href = location.origin + location.pathname + "?v=" + Date.now();
          }, 900);
        } else if (r.success && r.restart_required) {
          updateState.value = { ...updateState.value, status: "up_to_date", message: r.message };
        } else if (r.success) {
          updateState.value = { ...updateState.value, status: "up_to_date", message: r.message };
        } else {
          updateState.value = { ...updateState.value, status: "error", message: r.message || "Install failed" };
        }
      } catch (e) {
        addToast(e.message || "Install failed", "error");
      } finally {
        updateInstalling.value = false;
        setTimeout(() => {
          if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
        }, 5000);
      }
    }

    onMounted(() => {
      if (store.profile?.is_kids) {
        addToast("Settings is locked in Kids Mode 🔒", "warning");
        router.push("/");
        return;
      }
      loadSettings();
      loadCacheInfo();
      loadSystemInfo();
      window.addEventListener("beforeunload", handleBeforeUnload);
      // Auto-run the update check when arriving from the update banner
      if (store.pendingUpdateCheck) {
        store.pendingUpdateCheck = false;
        checkUpdates();
      }
    });

    onUnmounted(() => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      if (animeDetectTimer) clearInterval(animeDetectTimer);
    });

    async function testApi(provider, key) {
      if (!key || !key.trim()) {
        addToast("Please enter an API key to test", "warning");
        return;
      }
      testingApi.value = provider;
      try {
        const res = await API.post("/api/settings/test-api", { provider, key: key.trim() });
        if (res.ok) {
          addToast(res.message, "success");
        } else {
          addToast(res.message || "API key test failed", "error");
        }
      } catch (e) {
        addToast("API key test request failed", "error");
      } finally {
        testingApi.value = null;
      }
    }

    async function addPath(cat) {
      let val = newPaths.value[cat]?.trim();
      if (!val) {
        addToast("Please enter or browse a folder path to add", "warning");
        return;
      }
      val = val.replace(/\\/g, "/");
      if (!form.value.media_paths[cat]) form.value.media_paths[cat] = [];
      if (form.value.media_paths[cat].includes(val)) {
        addToast("Path is already in list", "info");
        return;
      }
      form.value.media_paths[cat].push(val);
      newPaths.value[cat] = "";
      addToast(`Added path to ${cat} ✓`, "success");
      await validatePaths();
    }

    async function removePath(cat, idx) {
      const p = form.value.media_paths[cat][idx];
      const ok = await customConfirm({
        title: "Remove Media Path",
        message: `Remove path "${p}" from ${cat} scanner list?`,
        icon: "ph ph-folder-minus",
        danger: true,
        okText: "Remove Path"
      });
      if (!ok) return;
      form.value.media_paths[cat].splice(idx, 1);
      // Also remove from disabled_paths if present
      const di = (form.value.disabled_paths[cat] || []).indexOf(p);
      if (di !== -1) form.value.disabled_paths[cat].splice(di, 1);
    }

    function movePath(cat, idx, direction) {
      const target = idx + direction;
      const list = form.value.media_paths[cat];
      if (!list || target < 0 || target >= list.length) return;
      const item = list.splice(idx, 1)[0];
      list.splice(target, 0, item);
    }

    function togglePath(cat, idx) {
      const p = form.value.media_paths[cat][idx];
      if (!form.value.disabled_paths[cat]) form.value.disabled_paths[cat] = [];
      const di = form.value.disabled_paths[cat].indexOf(p);
      if (di === -1) {
        form.value.disabled_paths[cat].push(p);
        addToast(`Disabled "${p}" — media from this path is now hidden`, "info");
      } else {
        form.value.disabled_paths[cat].splice(di, 1);
        addToast(`Enabled "${p}"`, "success");
      }
    }

    const cacheInfo = ref({ file_count: 0, size_formatted: "0 KB" });
    const clearingCache = ref(false);
    const resetting = ref(false);
    const showResetModal = ref(false);
    const clearMediaFiles = ref(false);
    const resetConfirmText = ref("");

    async function loadCacheInfo() {
      try {
        const res = await API.get("/api/system/cache");
        if (res) cacheInfo.value = res;
      } catch (e) {}
    }

    // ─── Anime detection (Series → Anime) ──────────────────────
    const animeDetect = ref({ running: false, done: false, total: 0, processed: 0, reclassified: 0, error: null });
    let animeDetectTimer = null;

    function manualScan() {
      unlockAchievement("scan_master");
      startLibraryScan(true);
    }

    // ─── Backup & Restore ──────────────────────────────────────
    const backupIncludeMetadata = ref(false);
    const restoreResult = ref(null);

    async function restoreFromBackup(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      const ok = await customConfirm({
        title: "Restore From Backup",
        message: `Restore from "${file.name}"? Settings apply immediately; the library database is staged and applies on the next server start.`,
        icon: "ph ph-archive-box",
        okText: "Restore",
      });
      if (!ok) return;
      restoreResult.value = { ok: true, message: "Restoring…" };
      try {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch("/api/system/restore", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) {
          restoreResult.value = { ok: false, message: data.error || "Restore failed" };
          addToast(data.error || "Restore failed", "error", 6000);
          return;
        }
        restoreResult.value = { ok: true, message: data.message };
        addToast(data.message, "success", 6000);
        await loadSettings();
      } catch (e) {
        restoreResult.value = { ok: false, message: e.message || "Restore failed" };
        addToast(e.message || "Restore failed", "error", 6000);
      }
    }

    async function startAnimeDetect() {
      if (animeDetect.value.running) return;
      try {
        const r = await API.post("/api/library/detect-anime", {});
        if (!r.started) {
          addToast(r.message || "Detection already running", "warning");
          return;
        }
        animeDetect.value = { running: true, done: false, total: 0, processed: 0, reclassified: 0, error: null };
        animeDetectTimer = setInterval(async () => {
          try {
            const s = await API.get("/api/library/detect-anime/status");
            animeDetect.value = s;
            if (!s.running && s.done) {
              clearInterval(animeDetectTimer);
              animeDetectTimer = null;
              if (s.error) {
                addToast("Anime detection failed: " + s.error, "error");
              } else {
                addToast(`Anime detection complete — ${s.reclassified} show(s) moved to Anime`, "success");
              }
            }
          } catch (e) {}
        }, 1000);
      } catch (e) {
        addToast(e.message || "Failed to start anime detection", "error");
      }
    }

    async function handleClearCache() {
      clearingCache.value = true;
      try {
        const res = await API.del("/api/system/cache");
        addToast(`Cache cleared! (${res.cleared || 0} files removed) — scanning for new metadata…`, "success");
        await loadCacheInfo();
        // Signal HomePage to auto-start a scan when we arrive there
        store.pendingScanAfterCacheCleared = true;
        router.push("/");
      } catch (e) {
        addToast("Failed to clear cache", "error");
      } finally {
        clearingCache.value = false;
      }
    }

    const volumePercent = computed(() => {
      const vol = form.value?.playback?.default_volume;
      if (vol === undefined || vol === null) return 100;
      const num = Number(vol);
      return num <= 1 ? Math.round(num * 100) : Math.round(num);
    });

    function setVolumePercent(val) {
      const pct = Number(val);
      form.value.playback.default_volume = pct / 100;
    }

    async function confirmFreshStart() {
      if (resetConfirmText.value.trim().toUpperCase() !== "RESET" || resetting.value) return;
      resetting.value = true;
      try {
        await API.post("/api/system/reset", { clear_media_files: clearMediaFiles.value });
        store.profile = null;
        addToast("Unlinked external paths & reset complete! Restarting...", "success");
        setTimeout(() => {
          window.location.reload();
        }, 1200);
      } catch (e) {
        addToast("Failed to reset application", "error");
      } finally {
        resetting.value = false;
        showResetModal.value = false;
      }
    }

    const allProfiles = ref([]);
    // Use a writable ref (not computed) so v-model mutations on kp fields persist
    const kidsProfiles = ref([]);

    watch(allProfiles, (profiles) => {
      kidsProfiles.value = (profiles || []).filter((p) => p.is_kids);
    }, { deep: true });

    async function loadAllProfiles() {
      try {
        allProfiles.value = await API.get("/api/profiles") || [];
      } catch (e) {}
    }

    async function saveKidsProfileLimits(kp) {
      // Read the latest values directly from the kidsProfiles ref entry
      const source = kidsProfiles.value.find((p) => p.id === kp.id) || kp;
      const payload = {
        ...source,
        daily_limit_minutes: Number(source.daily_limit_minutes) || 0,
        bedtime_curfew: source.bedtime_curfew || "",
      };
      try {
        const updated = await API.put(`/api/profiles/${payload.id}`, payload);
        // Sync the backend response back into allProfiles so store stays consistent
        const idx = allProfiles.value.findIndex((p) => p.id === payload.id);
        if (idx !== -1) {
          allProfiles.value[idx] = { ...allProfiles.value[idx], ...updated };
          allProfiles.value = [...allProfiles.value]; // trigger reactivity
        }
        addToast(`Screen time settings saved for ${payload.name} ✓`, "success");
      } catch (e) {
        addToast(`Failed to save screen time settings: ${e.message}`, "error");
      }
    }

    // ─── Unmatched Media & Fix Match ────────────────────────────
    const unmatchedList = ref([]);
    const loadingUnmatched = ref(false);

    async function loadUnmatched() {
      loadingUnmatched.value = true;
      try {
        const res = await API.get("/api/unmatched");
        unmatchedList.value = res || [];
      } catch (e) {
        addToast("Failed to load unmatched media list", "error");
      } finally {
        loadingUnmatched.value = false;
      }
    }

    function openFixMatchForItem(item) {
      openGlobalFixMatch(item, async () => {
        await loadUnmatched();
      });
    }

    // ─── Outgoing Network Activity & Request Inspector ──────────
    const networkList = ref([]);
    const networkSummary = ref({ total: 0, success: 0, failed: 0, success_rate: 100, avg_latency_ms: 0 });
    const loadingNetwork = ref(false);
    const networkServiceFilter = ref("all");
    const networkStatusFilter = ref("all");
    const networkAutoRefresh = ref(false);
    let networkPollInterval = null;

    async function loadNetworkRequests() {
      loadingNetwork.value = true;
      try {
        const res = await API.get("/api/system/network-requests?limit=150");
        networkList.value = res?.requests || [];
        networkSummary.value = res?.summary || { total: 0, success: 0, failed: 0, success_rate: 100, avg_latency_ms: 0 };
      } catch (e) {
      } finally {
        loadingNetwork.value = false;
      }
    }

    async function clearNetworkRequests() {
      try {
        await API.post("/api/system/network-requests/clear");
        networkList.value = [];
        networkSummary.value = { total: 0, success: 0, failed: 0, success_rate: 100, avg_latency_ms: 0 };
        addToast("Network activity log cleared", "info");
      } catch (e) {
        addToast("Failed to clear network log", "error");
      }
    }

    const filteredNetworkList = computed(() => {
      let list = networkList.value || [];
      if (networkServiceFilter.value && networkServiceFilter.value !== "all") {
        list = list.filter(r => r.service === networkServiceFilter.value);
      }
      if (networkStatusFilter.value === "success") {
        list = list.filter(r => r.ok);
      } else if (networkStatusFilter.value === "error") {
        list = list.filter(r => !r.ok);
      }
      return list;
    });

    function getServiceBadgeClass(service) {
      if (!service) return "";
      const s = service.toLowerCase();
      if (s.includes("tmdb cdn")) return "tmdb-cdn";
      if (s.includes("tmdb")) return "tmdb-api";
      if (s.includes("opensub")) return "opensubtitles";
      if (s.includes("aniskip")) return "aniskip";
      if (s.includes("jikan") || s.includes("mal")) return "jikan";
      if (s.includes("github")) return "github";
      if (s.includes("yts")) return "yts";
      return "";
    }

    watch(networkAutoRefresh, (val) => {
      if (val) {
        if (!networkPollInterval) {
          networkPollInterval = setInterval(loadNetworkRequests, 3000);
        }
      } else {
        if (networkPollInterval) {
          clearInterval(networkPollInterval);
          networkPollInterval = null;
        }
      }
    });

    onUnmounted(() => {
      if (networkPollInterval) {
        clearInterval(networkPollInterval);
        networkPollInterval = null;
      }
    });

    onMounted(() => {
      if (store.profile?.is_kids) {
        addToast("Settings is locked in Kids Mode 🔒", "warning");
        router.push("/");
        return;
      }
      loadSettings();
      loadCacheInfo();
      loadAllProfiles();
      loadUnmatched();
      loadNetworkRequests();
    });

    const currentTheme = computed(() => store.profile?.theme || localStorage.getItem("capsstream_theme") || "crimson");

    function selectTheme(themeId) {
      applyTheme(themeId, true);
    }

    // ─── Server Shutdown & Power Management ─────────────────────
    const showShutdownModal = ref(false);
    const isShuttingDown = ref(false);
    const shutdownCountdown = ref(2);
    const shutdownCompleted = ref(false);
    let _windowCloseCalled = false;

    function _stopAllPolling() {
      // Kill network auto-refresh interval if running
      networkAutoRefresh.value = false;
      if (networkPollInterval) {
        clearInterval(networkPollInterval);
        networkPollInterval = null;
      }
    }

    async function executeShutdown() {
      // Re-entry guard: a second click must not reset the close state
      if (isShuttingDown.value) return;
      showShutdownModal.value = false;
      isShuttingDown.value = true;
      shutdownCountdown.value = 10;
      shutdownCompleted.value = false;
      _windowCloseCalled = false;

      // Stop all background polling immediately so no more API calls are made
      _stopAllPolling();

      // Prefetch the offline page while the server is still reachable — it is
      // rendered as the final screen if the browser blocks window.close()
      for (const url of ["/offline-page", "/static/offline.html"]) {
        try {
          const res = await fetch(url, { cache: "no-store" });
          if (res.ok) {
            _offlinePageHtml = await res.text();
            break;
          }
        } catch (e) {}
      }

      try {
        await API.post("/api/system/shutdown");
      } catch (e) {
        // Expected — server exits immediately after responding
      }

      const timer = setInterval(() => {
        shutdownCountdown.value--;
        if (shutdownCountdown.value <= 0) {
          clearInterval(timer);
          shutdownCompleted.value = true;
          closeCurrentWindow();
        }
      }, 1000);
    }

    let _offlinePageHtml = null;
    let _pageReplaced = false;

    function _tryWindowClose() {
      let closed = false;
      try { window.close(); } catch (e) {}
      // Re-check: window.close() is async-ish in some browsers
      try {
        if (window.closed) closed = true;
      } catch (e) {}
      if (closed) return true;
      // Legacy fallback: re-open self, then close (works in some engines)
      try {
        const win = window.open("", "_self");
        if (win) win.close();
        if (window.closed) closed = true;
      } catch (e) {}
      return closed;
    }

    function _blankOutPage() {
      // Browser refused window.close() — replace the document with the
      // prefetched offline page (auto-reloads when the server returns).
      if (_pageReplaced) return;
      _pageReplaced = true;
      try {
        if (_offlinePageHtml) {
          document.open();
          document.write(_offlinePageHtml);
          document.close();
          return;
        }
        document.title = "CapsStream";
        document.body.style.margin = "0";
        document.body.style.background = "#000";
        document.body.innerHTML =
          '<div style="position:fixed;inset:0;display:flex;align-items:center;justify-content:center;' +
          'flex-direction:column;gap:12px;color:#666;font-family:sans-serif;text-align:center;padding:2rem">' +
          '<i class="ph ph-power" style="font-size:3rem;color:#444"></i>' +
          '<div>Server stopped &mdash; this tab can now be closed.</div>' +
          '<div style="font-size:0.85em">To start again, launch <strong>start.bat</strong>.</div>' +
          "</div>";
      } catch (e) {}
    }

    function closeCurrentWindow() {
      // Guard: only attempt once to avoid repeated browser warnings
      if (_windowCloseCalled) return;
      _windowCloseCalled = true;

      if (_tryWindowClose()) return;

      // Give the browser a beat, then retry once before falling back
      setTimeout(() => {
        if (!_tryWindowClose()) _blankOutPage();
      }, 250);
    }

    return {
      THEME_PRESETS,
      currentTheme,
      selectTheme,
      kidsProfiles,
      saveKidsProfileLimits,
      store,
      sysInfo,
      loading,
      saving,
      testingApi,
      form,
      newPaths,
      updateState,
      updateChecking,
      updateInstalling,
      restartPending,
      updateProgress,
      restartAfterUpdate,
      changelogHtml,
      checkUpdates,
      installUpdate,
      saveSettings,
      testApi,
      addPath,
      removePath,
      movePath,
      togglePath,
      animeDetect,
      startAnimeDetect,
      manualScan,
      backupIncludeMetadata,
      restoreResult,
      restoreFromBackup,
      cacheInfo,
      clearingCache,
      resetting,
      handleClearCache,
      showResetModal,
      clearMediaFiles,
      resetConfirmText,
      confirmFreshStart,
      saveAndLeave,
      discardAndLeave,
      cancelLeave,
      showUnsavedModal,
      isDirty,
      browsingFolder,
      pathStatuses,
      handleBrowseFolder,
      validatePaths,
      volumePercent,
      setVolumePercent,
      unmatchedList,
      loadingUnmatched,
      loadUnmatched,
      openFixMatchForItem,
      formatFileSize,
      networkList,
      networkSummary,
      loadingNetwork,
      networkServiceFilter,
      networkStatusFilter,
      networkAutoRefresh,
      filteredNetworkList,
      loadNetworkRequests,
      clearNetworkRequests,
      getServiceBadgeClass,
      showShutdownModal,
      isShuttingDown,
      shutdownCountdown,
      shutdownCompleted,
      executeShutdown,
      closeCurrentWindow,
    };
  },
};

// ─── Shortcuts Modal Component ───────────────────────────────

const ShortcutsModal = {
  emits: ["close"],
  setup(props, { emit }) {
    // Esc closes the cheatsheet (both App-level and in-player instances)
    function onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        emit("close");
      }
    }
    onMounted(() => window.addEventListener("keydown", onKey));
    onUnmounted(() => window.removeEventListener("keydown", onKey));
  },
  template: `
    <div class="modal-backdrop" style="z-index: 500; background: rgba(0, 0, 0, 0.85); backdrop-filter: blur(16px);" @click.self="$emit('close')">
      <div class="shortcuts-modal-card" @click.stop>
        <div class="shortcuts-modal-inner">
          <div class="shortcuts-modal-header">
            <div class="shortcuts-header-title">
              <i class="ph ph-keyboard" style="color:var(--accent);font-size:1.5rem"></i>
              <span>Keyboard Shortcuts</span>
            </div>
            <button class="shortcuts-close-btn" @click="$emit('close')" title="Close (Esc)">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <div class="shortcuts-bento-grid">
            <!-- Player Shortcuts -->
            <div class="shortcuts-group">
              <div class="shortcuts-group-title">🎬 Video Player</div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Play / Pause</span>
                <div class="kbd-group"><kbd class="shortcut-kbd">Space</kbd> <kbd class="shortcut-kbd">K</kbd></div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Toggle Fullscreen</span>
                <kbd class="shortcut-kbd">F</kbd>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Mute / Unmute</span>
                <kbd class="shortcut-kbd">M</kbd>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Seek 10s Backward / Forward</span>
                <div class="kbd-group"><kbd class="shortcut-kbd">←</kbd> <kbd class="shortcut-kbd">→</kbd></div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Volume Up / Down</span>
                <div class="kbd-group"><kbd class="shortcut-kbd">↑</kbd> <kbd class="shortcut-kbd">↓</kbd></div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Subtitle Sync (±250ms / ±1s)</span>
                <div class="kbd-group"><kbd class="shortcut-kbd">[</kbd> <kbd class="shortcut-kbd">]</kbd></div>
              </div>
            </div>

            <!-- Navigation & Global -->
            <div class="shortcuts-group">
              <div class="shortcuts-group-title">🌐 Navigation & Global</div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Quick Search</span>
                <kbd class="shortcut-kbd">/</kbd>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Shortcuts Cheatsheet</span>
                <kbd class="shortcut-kbd">?</kbd>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Close Modal</span>
                <kbd class="shortcut-kbd">Esc</kbd>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-desc">Subtitle Menu Switcher</span>
                <kbd class="shortcut-kbd">S</kbd>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `
};

// ─── Player Page ──────────────────────────────────────────────

const PlayerPage = {
  components: { ShortcutsModal },
  template: `
    <div class="custom-player-wrapper" @mousemove="showControls" @click="handleContainerClick" @dblclick="toggleFullscreen">
      <!-- Shortcuts Modal -->
      <shortcuts-modal v-if="showShortcuts" @close="showShortcuts = false" />
      <!-- Native Video Surface -->
      <video
        ref="videoRef"
        class="custom-player-video"
        crossorigin="anonymous"
        playsinline
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @ended="onEnded"
        @waiting="isBuffering = true"
        @playing="onVideoPlaying"
        @pause="onVideoPause"
        @seeked="onVideoSeeked"
        @error="onVideoError"
      >
        <track
          v-for="sub in subtitles"
          :key="sub.url"
          kind="subtitles"
          :src="sub.url"
          :srclang="(sub.language || 'en').toLowerCase().slice(0,2)"
          :label="sub.label"
          @load="() => { syncTextTracks(); updateActiveCueText(); }"
          @error="onSubtitleTrackError(sub)"
        />
      </video>

      <!-- Custom High-Reliability Subtitle Overlay -->
      <div v-if="activeCueText" class="caps-sub-overlay" :style="customCueStyle">
        {{ activeCueText }}
      </div>

      <!-- Minimal Achievement Pill (left side, never covers controls) -->
      <transition name="fade">
        <div v-if="playerAch" class="player-achv-pill" :class="{ 'kids-achv-pill': playerAch.isKids }" :style="{ bottom: controlsHidden ? '40px' : '120px' }">
          <span v-if="playerAch.icon" style="font-size:1.15rem;margin-right:2px">{{ playerAch.icon }}</span>
          <i v-else class="ph-fill ph-trophy"></i>
          <span>{{ playerAch.title }}</span>
        </div>
      </transition>

      <!-- 4K HEVC Playback Risk Advisory (left-aligned, dismissible) -->
      <transition name="fade">
        <div v-if="playbackWarning && !warningDismissed" class="player-compat-banner" :id="'compat-banner'">
          <i :class="playbackWarning.icon"></i>
          <div class="player-compat-text">
            <strong>{{ playbackWarning.title }}</strong>
            <span>{{ playbackWarning.msg }}</span>
            <div class="player-compat-actions">
              <button
                v-if="!streamState.transcode && compatInfo && compatInfo.available"
                class="player-compat-btn"
                @click.stop="enableCompatPlayback"
              >
                <i class="ph ph-lightning"></i> Play converted (1080p)
              </button>
              <button
                v-else-if="streamState.transcode"
                class="player-compat-btn on"
                @click.stop="disableCompatPlayback"
              >
                <i class="ph ph-check-circle"></i> Converted — play original
              </button>
            </div>
          </div>
          <button class="player-compat-dismiss" @click.stop="dismissPlaybackWarning" title="Dismiss">
            <i class="ph ph-x"></i>
          </button>
        </div>
      </transition>

      <!-- Child Screen Lock Overlay -->
      <div v-if="isChildLocked" class="player-child-lock-overlay" @click.stop="promptUnlockHint">
        <transition name="fade">
          <div v-if="showUnlockHint" class="child-lock-hint-pill" @click.stop="toggleChildLock">
            <i class="ph-fill ph-lock-key"></i>
            <span>Screen Locked • Click to Unlock 🔓</span>
          </div>
        </transition>
      </div>

      <!-- Volume OSD (minimal vertical bar, right side) -->
      <transition name="fade">
        <div v-if="volumeOSD" class="player-volume-osd">
          <i :class="isMuted || volume === 0 ? 'ph-fill ph-speaker-x' : volume < 0.5 ? 'ph-fill ph-speaker-low' : 'ph-fill ph-speaker-high'"></i>
          <div class="player-volume-bar">
            <div class="player-volume-fill" :style="{ height: volumeOSDPct + '%' }"></div>
          </div>
          <span>{{ volumeOSDPct }}%</span>
        </div>
      </transition>

      <!-- Seek OSD (direction flash) -->
      <transition name="fade">
        <div v-if="seekOSD" class="player-seek-osd" :class="seekOSD.dir">
          <i class="ph" :class="seekOSD.dir === 'forward' ? 'ph ph-arrow-clockwise' : 'ph ph-arrow-counter-clockwise'"></i>
          <span>{{ seekOSD.dir === 'forward' ? '+' : '−' }}{{ seekOSD.seconds }}s</span>
        </div>
      </transition>

      <!-- Buffering Spinner -->
      <div v-if="isBuffering" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:15;pointer-events:none">
        <div class="loading-spinner" style="width:56px;height:56px;border-width:4px"></div>
      </div>

      <!-- Backdrop Blocker overlay when Resume Prompt is active (Blocks all clicks outside top bar) -->
      <div v-if="showResumeModal" class="resume-backdrop-blocker" @click.stop.prevent></div>

      <!-- Controls Overlay -->
      <div class="custom-player-controls" :class="{ hidden: controlsHidden && !showResumeModal }" @click.stop>
        <!-- Top Bar (Always Clickable) -->
        <div class="custom-player-top" style="z-index: 220; position: relative; pointer-events: auto;">
          <div style="display:flex;align-items:center;gap:8px">
            <div class="player-back" @click="goBack" title="Back" id="player-back-btn">
              <i class="ph ph-arrow-left" style="font-size:1.25rem"></i>
            </div>
            <div class="player-back" @click="goHome" title="Home" id="player-home-btn">
              <i class="ph ph-house" style="font-size:1.25rem"></i>
            </div>
            <div class="player-back" @click="showShortcuts = true" title="Keyboard Shortcuts (?)" id="player-shortcuts-btn">
              <i class="ph ph-keyboard" style="font-size:1.25rem"></i>
            </div>
          </div>
          <div>
            <div class="player-title">{{ media?.title }}</div>
            <div v-if="media?.ep_title" class="player-episode">
              S{{ (media.season||'').toString().padStart(2,'0') }}E{{ (media.episode||'').toString().padStart(2,'0') }} — {{ media.ep_title }}
            </div>
          </div>
        </div>

        <!-- Bottom Bar (Disabled when showResumeModal is true) -->
        <div class="custom-player-bottom" :class="{ 'resume-active-disabled': showResumeModal }">
          <!-- Side-by-Side Row above Seekbar: Show Info (LEFT), Auto-Advance Countdown (RIGHT) -->
          <div class="player-overlay-row" v-if="(showNextEp && isEnded) || (!isPlaying && media)">
            <!-- Paused Media Info (LEFT SIDE: Logo/Title & Description, strictly when paused) -->
            <div v-if="!isPlaying && media" class="player-paused-info">
              <div class="player-paused-logo-container">
                <img v-if="media.logo_path" :src="imgUrl(media.logo_path)" :alt="media.title" class="player-paused-logo" />
                <h2 v-else class="player-paused-title">{{ media.title }}</h2>
              </div>
              <p v-if="media.overview" class="player-paused-overview">{{ media.overview }}</p>
            </div>
            <div v-else></div>

            <!-- Next Episode Auto-Advance Card (RIGHT SIDE: Strictly when isEnded) -->
            <div v-if="showNextEp && isEnded" class="next-ep-bottom-container">
              <button class="btn-next-ep-bottom is-ended" @click="handleNextEpClick" id="player-next-btn">
                <div class="next-ep-thumb">
                  <img
                    v-if="nextEp && (nextEp.still_path || nextEp.backdrop_path || media.backdrop_path)"
                    :src="imgUrl(nextEp.still_path || nextEp.backdrop_path || media.backdrop_path)"
                    @error="e => e.target.style.display = 'none'"
                  />
                  <div v-else class="next-ep-thumb-fallback"><i class="ph ph-television"></i></div>
                  <div class="next-ep-ring-wrapper">
                    <svg class="next-ep-ring-svg" viewBox="0 0 36 36">
                      <path
                        class="next-ep-ring-bg"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      />
                      <path
                        class="next-ep-ring-fill"
                        :style="{ strokeDasharray: nextEpProgressPercent + ', 100' }"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      />
                    </svg>
                    <span class="next-ep-countdown-text">{{ Math.ceil(nextEpCountdownSeconds) }}</span>
                  </div>
                </div>
                <div class="next-ep-meta">
                  <span class="next-ep-label">Up Next in {{ Math.ceil(nextEpCountdownSeconds) }}s</span>
                  <span class="next-ep-title" :title="nextEp.ep_title || nextEp.title">
                    {{ nextEp.ep_title || nextEp.title }}
                  </span>
                  <span class="next-ep-code" v-if="nextEp.season || nextEp.episode">
                    S{{ (nextEp.season||1).toString().padStart(2,'0') }}E{{ (nextEp.episode||1).toString().padStart(2,'0') }}
                  </span>
                  <span class="next-ep-dur" v-if="nextEp.duration">{{ formatDuration(nextEp.duration) }}</span>
                </div>
              </button>

              <button class="btn-next-ep-cancel" @click.stop="cancelAutoAdvance" title="Cancel Auto-Advance">
                <i class="ph ph-x"></i>
              </button>
            </div>
          </div>

          <!-- Seekbar -->
          <div class="seekbar-wrapper"
               ref="seekbarRef"
               @click="seekToClick"
               @mousemove="hoverSeekbar"
               @mouseleave="showHoverTooltip = false"
               id="player-seekbar">
            <div v-if="showHoverTooltip" class="seekbar-tooltip" :class="{ 'has-preview': thumbSheet }" :style="{ left: hoverTooltipPos + 'px' }">
              <div
                v-if="thumbSheet"
                class="seekbar-thumb-preview"
                :style="thumbCellStyle(hoverTooltipTime)"
              ></div>
              {{ formatTime(hoverTooltipTime) }}
            </div>
            <div class="seekbar-track">
              <!-- Seekbar Segment Markers (Recap / Intro / Outro) -->
              <div v-if="skipTimes.recap" class="seekbar-segment recap-segment" :style="getSegmentStyle(skipTimes.recap)"></div>
              <div v-if="skipTimes.op" class="seekbar-segment op-segment" :style="getSegmentStyle(skipTimes.op)"></div>
              <div v-if="skipTimes.ed" class="seekbar-segment ed-segment" :style="getSegmentStyle(skipTimes.ed)"></div>
              <div v-if="skipTimes.preview" class="seekbar-segment preview-segment" :style="getSegmentStyle(skipTimes.preview)"></div>
              <div class="seekbar-fill" :style="{ width: progressPercent + '%' }">
                <div class="seekbar-handle"></div>
              </div>
            </div>
          </div>

          <!-- Controls Bar -->
          <div class="controls-bar">
            <div class="controls-left">
              <!-- Play / Pause -->
              <button class="ctrl-btn" @click="togglePlay" :title="isPlaying ? 'Pause (Space)' : 'Play (Space)'" id="ctrl-play">
                <i :class="isPlaying ? 'ph-fill ph-pause' : 'ph-fill ph-play'"></i>
              </button>

              <!-- Skip -10s -->
              <button class="ctrl-btn" @click="skip(-10)" title="Rewind 10s (Left Arrow)" id="ctrl-rewind">
                <i class="ph ph-arrow-counter-clockwise"></i>
              </button>

              <!-- Skip +10s -->
              <button class="ctrl-btn" @click="skip(10)" title="Forward 10s (Right Arrow)" id="ctrl-forward">
                <i class="ph ph-arrow-clockwise"></i>
              </button>

              <!-- Volume -->
              <div class="volume-group" style="position:relative">
                <div v-if="volume > 1.0" class="volume-boost-badge">{{ Math.round(volume * 100) }}% ⚡</div>
                <button class="ctrl-btn" @click="toggleMute" :title="isMuted ? 'Unmute (M)' : 'Mute (M)'" id="ctrl-volume">
                  <i :class="isMuted || volume === 0 ? 'ph-fill ph-speaker-x' : volume < 0.5 ? 'ph-fill ph-speaker-low' : 'ph-fill ph-speaker-high'"></i>
                </button>
                <div class="volume-slider-container">
                  <input type="range" class="volume-slider" min="0" max="2" step="0.05" :value="isMuted ? 0 : volume" @input="onVolumeInput" id="ctrl-volume-slider" />
                </div>
              </div>

              <!-- Time Display (content time vs real title duration) -->
              <div class="ctrl-time">
                {{ formatTime(displayTime) }} / {{ formatTime(displayDuration) }}
              </div>
            </div>

            <!-- Ends-At Clock (center of control bar) -->
            <div class="ctrl-end-time" v-if="endClockTime" :id="'ctrl-end-time'">
              <i class="ph ph-moon-stars"></i>
              <span>Ends at <strong>{{ endClockTime }}</strong></span>
            </div>

            <div class="controls-right">
              <!-- Next Episode Button (right side) + hover preview card -->
              <div
                v-if="hasNextEp"
                class="ctrl-next-wrap"
                @mouseenter="showNextPreview"
                @mouseleave="hideNextPreview"
              >
                <button class="ctrl-btn" @click="handleNextEpClick" title="Next Episode (N)" id="ctrl-next-ep">
                  <i class="ph-fill ph-skip-forward"></i>
                </button>
                <transition name="fade">
                  <div
                    v-if="nextEpHover && !activeSkipAction"
                    class="ctrl-next-preview"
                    @mouseenter="showNextPreview"
                    @mouseleave="hideNextPreview"
                    @click.stop="handleNextEpClick"
                  >
                    <div class="next-ep-thumb wide">
                      <img
                        v-if="nextEp && (nextEp.still_path || nextEp.backdrop_path || media.backdrop_path)"
                        :src="imgUrl(nextEp.still_path || nextEp.backdrop_path || media.backdrop_path)"
                        @error="e => e.target.style.display = 'none'"
                      />
                      <div v-else class="next-ep-thumb-fallback"><i class="ph ph-television"></i></div>
                      <span class="next-ep-dur" v-if="nextEp.duration">{{ formatDuration(nextEp.duration) }}</span>
                    </div>
                    <div class="next-ep-meta">
                      <span class="next-ep-label">Next Episode</span>
                      <span class="next-ep-title" :title="nextEp.ep_title || nextEp.title">
                        S{{ (nextEp.season||1).toString().padStart(2,'0') }} E{{ (nextEp.episode||1).toString().padStart(2,'0') }}
                        <template v-if="nextEp.ep_title"> · {{ nextEp.ep_title }}</template>
                      </span>
                      <span class="next-ep-overview" v-if="nextEp.overview">{{ nextEp.overview }}</span>
                    </div>
                  </div>
                </transition>
              </div>

              <!-- Audio Track Menu (Only shown if video has multiple audio tracks) -->
              <div v-if="audioTracks && audioTracks.length > 1" style="position:relative">
                <button class="ctrl-btn" @click="showAudioMenu = !showAudioMenu; showSubMenu = false; showSpeedMenu = false; showQualityMenu = false" title="Audio Track" id="ctrl-audio" style="font-size:0.85rem;font-weight:700">
                  <i class="ph ph-microphone-stage" style="font-size:1.35rem"></i>
                </button>
                <div v-if="showAudioMenu" class="player-popup-menu" @click.stop style="min-width:200px">
                  <div v-for="track in audioTracks" :key="track.index" class="player-menu-item" :class="{ active: (streamState.audioTrack ?? defaultAudioIndex) === track.index }" @click="selectAudioTrack(track.index)">
                    {{ track.title }}<span v-if="track.index === defaultAudioIndex" style="opacity:0.6;font-weight:400"> · Default</span>
                  </div>
                </div>
              </div>

              <!-- Subtitles Menu -->
              <div style="position:relative">
                <button class="ctrl-btn" @click="showSubMenu = !showSubMenu; showSpeedMenu = false; showAudioMenu = false; showQualityMenu = false" title="Subtitles" id="ctrl-subs" style="font-size:0.85rem;font-weight:700">
                  <i class="ph ph-closed-captioning" style="font-size:1.35rem"></i>
                </button>
                <div v-if="showSubMenu" class="player-popup-menu" @click.stop style="min-width:200px">
                  <div class="player-menu-item" :class="{ active: selectedSub === -1 }" @click="selectSub(-1)">
                    Off
                  </div>
                  <div v-if="!subtitles || !subtitles.length" class="player-menu-item" style="color:var(--text-muted);cursor:default">
                    No Subtitles Found
                  </div>
                  <div v-for="(sub, i) in subtitles" :key="sub.url" class="player-menu-item" :class="{ active: selectedSub === i }" @click="selectSub(i)" :title="sub.label || sub.raw_filename || sub.filename">
                    {{ sub.label }}
                  </div>
                  <div class="profile-dropdown-divider"></div>
                  <div class="player-menu-item" style="cursor:pointer;color:#38bdf8;font-weight:600" @click="openOnlineSubModal">
                    <i class="ph ph-magnifying-glass" style="margin-right:4px"></i> Search Online Subtitles
                  </div>
                  <div class="player-menu-item" style="cursor:pointer;color:#38bdf8;font-weight:600" @click="downloadSubtitles" :id="'ctrl-download-subs'">
                    <i :class="downloadingSubs ? 'ph ph-circle-notch' : 'ph ph-download-simple'" :style="downloadingSubs ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
                    {{ downloadingSubs ? 'Searching OpenSubtitles…' : 'Auto-Download Subtitles' }}
                  </div>
                  <label class="player-menu-item" style="cursor:pointer;color:var(--accent);font-weight:600">
                    <i class="ph ph-plus" style="margin-right:4px"></i> Load .srt / .vtt
                    <input type="file" accept=".vtt,.srt" @change="handleCustomSubFile" style="display:none" />
                  </label>

                  <!-- Subtitle Appearance Customizer Panel -->
                  <div class="sub-style-panel" @click.stop>
                    <div class="sub-style-title">Subtitle Appearance & Sync</div>
                    <div class="sub-style-row" style="flex-direction:column;align-items:stretch;gap:6px;margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.1)">
                      <div style="display:flex;justify-content:space-between;align-items:center">
                        <span class="sub-style-label">Sync / Delay</span>
                        <span style="font-size:0.75rem;font-weight:700;color:var(--accent)">
                          {{ subOffsetMs === 0 ? '0 ms (In Sync)' : (subOffsetMs > 0 ? '+' + subOffsetMs + ' ms' : subOffsetMs + ' ms') }}
                        </span>
                      </div>
                      <div style="display:flex;align-items:center;gap:4px;justify-content:space-between">
                        <button class="sub-size-btn" @click="adjustSubOffset(-1000)" title="Earlier 1.0s">−1.0s</button>
                        <button class="sub-size-btn" @click="adjustSubOffset(-250)" title="Earlier 0.25s">−0.25s</button>
                        <button class="sub-size-btn" @click="resetSubOffset" title="Reset delay to 0 ms" :class="{ active: subOffsetMs === 0 }">Reset</button>
                        <button class="sub-size-btn" @click="adjustSubOffset(250)" title="Later 0.25s">+0.25s</button>
                        <button class="sub-size-btn" @click="adjustSubOffset(1000)" title="Later 1.0s">+1.0s</button>
                      </div>
                    </div>
                    <div class="sub-style-row">
                      <span class="sub-style-label">Color</span>
                      <div class="sub-color-dots">
                        <div class="sub-color-dot" style="background:#ffffff" :class="{ active: subStyle.textColor === '#ffffff' }" @click="updateSubStyle('textColor', '#ffffff')" title="White"></div>
                        <div class="sub-color-dot" style="background:#ffd700" :class="{ active: subStyle.textColor === '#ffd700' }" @click="updateSubStyle('textColor', '#ffd700')" title="Yellow"></div>
                        <div class="sub-color-dot" style="background:#00f2fe" :class="{ active: subStyle.textColor === '#00f2fe' }" @click="updateSubStyle('textColor', '#00f2fe')" title="Cyan"></div>
                        <div class="sub-color-dot" style="background:#00ff87" :class="{ active: subStyle.textColor === '#00ff87' }" @click="updateSubStyle('textColor', '#00ff87')" title="Green"></div>
                      </div>
                    </div>
                    <div class="sub-style-row">
                      <span class="sub-style-label">Size</span>
                      <div style="display:flex;gap:4px">
                        <button class="sub-size-btn" :class="{ active: subStyle.fontSize === '0.85rem' }" @click="updateSubStyle('fontSize', '0.85rem')">S</button>
                        <button class="sub-size-btn" :class="{ active: subStyle.fontSize === '1.1rem' }" @click="updateSubStyle('fontSize', '1.1rem')">M</button>
                        <button class="sub-size-btn" :class="{ active: subStyle.fontSize === '1.4rem' }" @click="updateSubStyle('fontSize', '1.4rem')">L</button>
                        <button class="sub-size-btn" :class="{ active: subStyle.fontSize === '1.8rem' }" @click="updateSubStyle('fontSize', '1.8rem')">XL</button>
                      </div>
                    </div>
                    <div class="sub-style-row">
                      <span class="sub-style-label">Box Opacity</span>
                      <div style="display:flex;gap:4px">
                        <button class="sub-size-btn" :class="{ active: subStyle.bgOpacity === 0 }" @click="updateSubStyle('bgOpacity', 0)">Off</button>
                        <button class="sub-size-btn" :class="{ active: subStyle.bgOpacity === 0.5 }" @click="updateSubStyle('bgOpacity', 0.5)">50%</button>
                        <button class="sub-size-btn" :class="{ active: subStyle.bgOpacity === 0.85 }" @click="updateSubStyle('bgOpacity', 0.85)">Solid</button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Video Quality Resolution Menu (Gear Icon ⚙️) — always shown for Skip Markers, quality section only for movies with duplicates -->
              <div style="position:relative">
                <button class="ctrl-btn" @click="showQualityMenu = !showQualityMenu; showSpeedMenu = false; showSubMenu = false; showAudioMenu = false" title="Player Options & Quality" id="ctrl-quality" style="font-size:0.85rem;font-weight:700">
                  <i class="ph ph-gear-six" style="font-size:1.35rem"></i>
                </button>
                <div v-if="showQualityMenu" class="player-popup-menu" @click.stop style="min-width:210px">
                  <div style="font-size:0.75rem;color:var(--text-muted);padding:6px 12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                    Player Options
                  </div>
                  <div v-if="!store.profile?.is_kids" class="player-menu-item" @click="showSkipModal = true; showQualityMenu = false" id="player-menu-skip-markers">
                    <span>⏱️ Edit Skip Markers</span>
                  </div>
                  <!-- Video Quality: always visible; clickable only when an
                       alternative quality source actually exists -->
                  <div style="border-top:1px solid rgba(255,255,255,0.1);margin:4px 0"></div>
                  <div style="font-size:0.75rem;color:var(--text-muted);padding:6px 12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                    Video Quality
                  </div>
                  <div
                    v-for="opt in (qualityOptions.length ? qualityOptions : [{ display_label: 'Default', media_id: selectedQualityMediaId }])"
                    :key="opt.media_id"
                    class="player-menu-item"
                    :class="{ active: selectedQualityMediaId === opt.media_id, disabled: !canSwitchQuality }"
                    @click="canSwitchQuality && selectQuality(opt)"
                    style="display:flex;align-items:center;justify-content:space-between;gap:12px"
                  >
                    <span>{{ opt.display_label }}</span>
                    <span v-if="opt.size_str" style="font-size:0.75rem;color:var(--text-muted)">{{ opt.size_str }}</span>
                  </div>
                  <div v-if="!canSwitchQuality" style="font-size:0.68rem;color:var(--text-muted);padding:4px 12px 6px">
                    No alternative quality sources
                  </div>
                </div>
              </div>

              <!-- Playback Speed Menu -->
              <div style="position:relative">
                <button class="ctrl-btn" @click="showSpeedMenu = !showSpeedMenu; showSubMenu = false; showAudioMenu = false; showQualityMenu = false" title="Playback Speed" style="font-size:0.85rem;font-weight:700" id="ctrl-speed">
                  {{ playbackRate }}x
                </button>
                <div v-if="showSpeedMenu" class="player-popup-menu" @click.stop>
                  <div v-for="rate in [0.5, 0.75, 1, 1.25, 1.5, 2]" :key="rate" class="player-menu-item" :class="{ active: playbackRate === rate }" @click="selectSpeed(rate)">
                    {{ rate }}x
                  </div>
                </div>
              </div>

              <!-- Picture-in-Picture (PiP) -->
              <button
                v-if="isPipSupported"
                class="ctrl-btn"
                :class="{ active: isPipActive }"
                @click="togglePip"
                title="Picture-in-Picture (P)"
                id="ctrl-pip"
              >
                <i :class="isPipActive ? 'ph-fill ph-screencast' : 'ph ph-screencast'"></i>
              </button>

              <!-- Fullscreen -->
              <button class="ctrl-btn" @click="toggleFullscreen" title="Fullscreen (F)" id="ctrl-fullscreen">
                <i :class="isFullscreen ? 'ph ph-arrows-in-simple' : 'ph ph-arrows-out-simple'"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Floating Skip Intro / Recap / Outro Pill Button -->
      <div v-if="activeSkipAction" class="player-skip-container" @click.stop>
        <button class="player-skip-btn" @click="executeSkipAction" id="player-skip-btn">
          <!-- Next Episode: thumbnail + episode details -->
          <template v-if="activeSkipAction.type === 'Next' && nextEp">
            <div class="next-ep-thumb skip">
              <img
                v-if="nextEp.still_path || nextEp.backdrop_path || media.backdrop_path"
                :src="imgUrl(nextEp.still_path || nextEp.backdrop_path || media.backdrop_path)"
                @error="e => e.target.style.display = 'none'"
              />
              <div v-else class="next-ep-thumb-fallback"><i class="ph ph-television"></i></div>
              <span class="next-ep-dur" v-if="nextEp.duration">{{ formatDuration(nextEp.duration) }}</span>
            </div>
            <div class="player-skip-meta">
              <span class="player-skip-label">Up Next</span>
              <span class="player-skip-title">Next Episode</span>
              <span class="player-skip-sub" v-if="nextEp.season || nextEp.episode">
                S{{ (nextEp.season||1).toString().padStart(2,'0') }}E{{ (nextEp.episode||1).toString().padStart(2,'0') }}
                <template v-if="nextEp.ep_title"> · {{ nextEp.ep_title }}</template>
              </span>
            </div>
          </template>

          <!-- Other segments: icon chip -->
          <template v-else>
            <div class="player-skip-icon">
              <i class="ph ph-fast-forward"></i>
            </div>
            <div class="player-skip-meta">
              <span class="player-skip-label">Skip</span>
              <span class="player-skip-title">{{ activeSkipAction.type }}</span>
              <span class="player-skip-sub">Jump to {{ formatSecToTime(activeSkipAction.end) }}</span>
            </div>
          </template>
        </button>
      </div>

      <!-- Skip Timestamps Editor Modal -->
      <skip-timestamps-modal
        v-if="showSkipModal"
        :media="media"
        :currentTime="currentContentTime()"
        :inPlayer="true"
        @close="showSkipModal = false"
        @saved="handleSkipSaved"
      />

      <!-- Bottom-Right Cinematic Resume Card -->
      <div v-if="showResumeModal" class="resume-card-bottom-right" @click.stop>
        <div class="resume-card-inner">
          <!-- Thumbnail Header Preview -->
          <div class="resume-thumb-container">
            <img
              v-if="media?.backdrop_path || media?.still_path || media?.poster_path"
              :src="imgUrl(media.still_path || media.backdrop_path || media.poster_path)"
              :alt="media?.title"
              class="resume-thumb-img"
            />
            <div v-else class="resume-thumb-placeholder">🎬</div>
            <!-- Progress Line on Thumbnail -->
            <div class="resume-thumb-progress" v-if="duration > 0">
              <div class="resume-thumb-progress-fill" :style="{ width: (resumeTime / duration * 100) + '%' }"></div>
            </div>
          </div>

          <!-- Info & Title -->
          <div class="resume-card-info">
            <div class="resume-badge">
              <i class="ph-fill ph-clock-counter-clockwise"></i> RESUME PLAYBACK
            </div>
            <div class="resume-card-heading" :title="media?.title">{{ media?.title || 'Title' }}</div>
            <div v-if="media?.ep_title" class="resume-card-ep" :title="media.ep_title">
              S{{ (media.season||'').toString().padStart(2,'0') }}E{{ (media.episode||'').toString().padStart(2,'0') }} — {{ media.ep_title }}
            </div>
            <div class="resume-card-subtext">
              Stopped at <span class="resume-timestamp">{{ formatTime(resumeTime) }}</span>
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="resume-card-actions">
            <button class="btn btn-primary btn-full" @click="confirmResume" id="btn-resume-continue" autoFocus>
              <i class="ph-fill ph-play"></i>
              <span>Resume at {{ formatTime(resumeTime) }}</span>
            </button>
            <button class="btn btn-secondary btn-full" @click="confirmStartOver" id="btn-resume-startover">
              <i class="ph ph-arrow-counter-clockwise"></i>
              <span>Start from Beginning</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Online Subtitles Search Modal -->
      <div v-if="showOnlineSubModal" class="modal-backdrop" @click.self="showOnlineSubModal = false">
        <div class="online-sub-modal" @click.stop>
          <div class="online-sub-header">
            <div class="online-sub-title">
              <i class="ph ph-closed-captioning" style="color:var(--accent);font-size:1.3rem"></i>
              <div>
                <div style="font-weight:800;font-size:1rem">Search Online Subtitles</div>
                <div style="font-size:0.78rem;color:var(--text-muted);font-weight:500">{{ media?.title }}</div>
              </div>
            </div>
            <button class="shortcuts-close-btn" @click="showOnlineSubModal = false">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <div v-if="loadingOnlineSubs" class="loading-spinner" style="margin:2.5rem auto"></div>

          <div v-else-if="onlineSubResults && onlineSubResults.length" class="online-sub-list">
            <div
              v-for="sub in onlineSubResults"
              :key="sub.id"
              class="online-sub-item"
              @click="downloadAndApplyOnlineSub(sub)"
            >
              <i class="ph ph-chat-center-dots online-sub-icon"></i>
              <div class="online-sub-meta">
                <div class="online-sub-name">{{ sub.title }}</div>
                <div class="online-sub-info">{{ sub.lang }}</div>
              </div>
              <button class="btn btn-secondary btn-sm online-sub-btn" :disabled="downloadingSubId === sub.id" @click.stop>
                <i :class="downloadingSubId === sub.id ? 'ph ph-circle-notch' : 'ph ph-download-simple'" :style="downloadingSubId === sub.id ? 'animation:spin 1s linear infinite' : ''"></i>
                {{ downloadingSubId === sub.id ? '' : 'Apply' }}
              </button>
            </div>
          </div>

          <div v-else class="online-sub-empty">
            <i class="ph ph-file-x"></i>
            <div>No online subtitles found for this title.</div>
          </div>

          <button class="btn btn-ghost btn-full" style="margin-top:1rem" @click="showOnlineSubModal = false">
            Close
          </button>
        </div>
      </div>

      <!-- Playback Error Overlay -->
      <div v-if="playerError" class="empty-state" style="position:fixed;inset:0;background:rgba(10,10,15,0.95);z-index:300;padding:2rem">
        <div class="empty-icon">⚠️</div>
        <div class="empty-title">Playback Issue</div>
        <div class="empty-subtitle" style="max-width:480px;margin-bottom:1.5rem">
          {{ playerError }}
        </div>
        <div style="display:flex;gap:12px;justify-content:center">
          <button class="btn btn-primary" @click="playerError = null; if (videoRef) videoRef.play().catch(()=>{})">Resume Playback</button>
          <button class="btn btn-secondary" @click="goBack">Go Back</button>
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const videoRef = ref(null);
    const seekbarRef = ref(null);

    const media = ref(null);
    const nextEp = ref(null);
    const subtitles = ref([]);
    const playerSettings = ref(null);

    const isPlaying = ref(false);
    const isMuted = ref(false);
    const volume = ref(1);
    const currentTime = ref(0);
    const duration = ref(0);
    const isBuffering = ref(false);
    const isFullscreen = ref(false);
    const controlsHidden = ref(false);
    const playerError = ref(null);

    const playbackRate = ref(1);
    const selectedSub = ref(-1);
    const showSpeedMenu = ref(false);
    const showSubMenu = ref(false);
    const showShortcuts = ref(false);

    const showOnlineSubModal = ref(false);
    const onlineSubResults = ref([]);
    const loadingOnlineSubs = ref(false);
    const downloadingSubId = ref(null);

    async function openOnlineSubModal() {
      showSubMenu.value = false;
      showOnlineSubModal.value = true;
      loadingOnlineSubs.value = true;
      onlineSubResults.value = [];
      try {
        const id = route.params.id;
        const res = await API.get(`/api/subtitles/online/search?media_id=${id}`);
        onlineSubResults.value = res || [];
      } catch (e) {
        addToast("Failed to search subtitles online", "error");
      } finally {
        loadingOnlineSubs.value = false;
      }
    }

    async function downloadAndApplyOnlineSub(sub) {
      downloadingSubId.value = sub.id;
      try {
        const id = route.params.id;
        const subMeta = await API.post("/api/subtitles/online/download", {
          slug: sub.slug || sub.id,
          media_id: Number(id)
        });

        if (subMeta && subMeta.url) {
          subtitles.value.push(subMeta);
          const newIdx = subtitles.value.length - 1;
          selectSub(newIdx);
          showOnlineSubModal.value = false;
          addToast("Subtitle downloaded and applied!", "success");
        } else {
          addToast("Failed to download subtitle file", "error");
        }
      } catch (e) {
        addToast("Error downloading subtitle", "error");
      } finally {
        downloadingSubId.value = null;
      }
    }

    // ════════════════════════════════════════════════════════════════
    // STREAM CONTROLLER — single source of truth for playback source.
    //
    // DESIGN: the <video> element ALWAYS plays the original file natively
    // (HTTP range seeks, frame-exact). Non-default audio tracks are served
    // separately to a hidden <audio> element kept in sync with the video
    // (see REMOTE AUDIO ENGINE below). The video pipeline is therefore
    // never transcoded or restarted for audio changes — video sync issues
    // are impossible by construction.
    //
    // streamStart is permanently 0: PLAYER time === CONTENT time everywhere.
    // ════════════════════════════════════════════════════════════════

    const audioTracks = ref([]);
    const defaultAudioIndex = ref(0);        // container-default track = played by <video>
    const showAudioMenu = ref(false);

    // The active stream session. Changing any field triggers a stream swap.
    const streamState = reactive({
      mediaId: null,        // which file/quality is streaming
      audioTrack: null,     // null/undefined/default  native; otherwise remote-audio index
      transcode: false,     // hardware-accelerated compatibility playback
      streamStart: 0,       // content time where the converted stream begins
    });

    // Retained for compatibility with helpers below; video is never
    // transcoded anymore, so this is permanently false.
    const isTranscodeAudio = computed(() => false);

    function contentToPlayer(t) {
      return Math.max(0, t - (streamState.transcode ? streamState.streamStart : 0));
    }
    function playerToContent(t) {
      return (streamState.transcode ? streamState.streamStart : 0) + t;
    }
    function currentContentTime() {
      const v = videoRef.value;
      return currentTime.value || (v ? v.currentTime || 0 : 0);
    }

    // ── Stream swap: the ONLY way playback source changes ──────────
    let reloadToken = 0;

    function buildStreamUrl(mediaId) {
      if (!streamState.transcode) {
        return `/api/stream/${mediaId}`;
      }
      let url = `/api/stream/${mediaId}?transcode=1&max_height=1080`;
      if (streamState.streamStart > 0) {
        url += `&start=${Number(streamState.streamStart).toFixed(3)}`;
      }
      return url;
    }

    function swapStream(atContentTime) {
      const v = videoRef.value;
      if (!v) return;
      const token = ++reloadToken;
      // Converted streams are piped & non-seekable: always start at 0
      // (server cuts at the keyframe-aligned point).
      const playerPos = streamState.transcode
        ? 0
        : Math.max(0, Math.floor(atContentTime || 0));
      isBuffering.value = true;

      const onMeta = () => {
        v.removeEventListener("loadedmetadata", onMeta);
        if (token !== reloadToken) return;   // a newer swap superseded us
        try {
          if (playerPos > 0 && isFinite(playerPos)) v.currentTime = playerPos;
          currentTime.value = v.currentTime;
        } catch (e) {}
        applySubtitleOffset();
        [300, 700].forEach((d) => setTimeout(applySubtitleOffset, d));
        // Resume prompt takes priority — stay paused behind the modal
        if (showResumeModal.value) {
          v.pause();
          return;
        }
        v.play().catch(() => {});
        // Re-point the remote audio at this file/position (fresh src)
        if (isRemoteAudioActive()) {
          attachRemoteAudio(streamState.audioTrack);
          startRemoteSyncLoop();
        } else {
          detachRemoteAudio();
        }
      };
      v.addEventListener("loadedmetadata", onMeta);

      // Setting src runs the media load algorithm exactly once.
      const want = buildStreamUrl(streamState.mediaId);
      const absWant = new URL(want, location.origin).href;
      if (v.src !== absWant) {
        currentTime.value = playerPos;
        v.src = want;
        v.load();
      } else {
        // Same source already loaded — just reposition deterministically
        try {
          if (playerPos > 0 && isFinite(playerPos)) v.currentTime = playerPos;
          currentTime.value = v.currentTime;
        } catch (e) {}
        applySubtitleOffset();
        [300, 700].forEach((d) => setTimeout(applySubtitleOffset, d));
        v.play().catch(() => {});
        if (isRemoteAudioActive()) {
          attachRemoteAudio(streamState.audioTrack);
          startRemoteSyncLoop();
        }
      }
    }

    // ════════════════════════════════════════════════════════════════
    // REMOTE AUDIO ENGINE — non-default audio tracks.
    //
    // The <video> keeps playing the original file MUTED; the selected track
    // is streamed as AAC to a hidden <audio> element driven to match the
    // video clock. Switching tracks never touches the video pipeline, so
    // video playback is always frame-perfect and instantly continuous.
    // ════════════════════════════════════════════════════════════════

    let remoteAudioEl = null;
    let remoteAudioTimer = null;
    let remoteRestartToken = 0;
    let remoteSeekDebounce = null;
    let remoteRebuildCooldownUntil = 0;
    // The audio stream's internal timeline starts at 0 — it does NOT know
    // about absolute content positions. This is the content time where the
    // current audio stream was cut, i.e. content = base + el.currentTime.
    let remoteAudioBase = 0;
    // Until this timestamp the sync loop deliberately does NOT chase the
    // video clock — a freshly attached stream needs ~1-2s to fill its
    // buffer, and chasing past delivered data stalls the element
    // ("plays a little then stops").
    let remoteSettleUntil = 0;

    function isRemoteAudioActive() {
      return (
        streamState.audioTrack !== null &&
        streamState.audioTrack !== undefined &&
        streamState.audioTrack !== defaultAudioIndex.value
      );
    }

    function buildRemoteAudioUrl(trackIndex, atTime) {
      const id = streamState.mediaId || route.params.id;
      return `/api/stream/${id}?audio_only=1&audio_track=${trackIndex}&at=${Math.max(0, atTime).toFixed(2)}`;
    }

    function attachRemoteAudio(trackIndex) {
      const v = videoRef.value;
      if (!v || trackIndex === null || trackIndex === undefined) return;

      // Video goes silent; the remote element carries sound.
      v.muted = true;

      if (!remoteAudioEl) {
        remoteAudioEl = new Audio();
        remoteAudioEl.preload = "auto";
        // If the element hits a fatal decode/network error, rebuild once.
        remoteAudioEl.addEventListener("error", () => {
          if (isRemoteAudioActive() && remoteAudioEl === this) {
            setTimeout(() => attachRemoteAudio(streamState.audioTrack), 300);
          }
        });
      }
      remoteAudioEl.volume = Math.min(1, Math.max(0, volume.value));
      remoteAudioEl.muted = false;
      remoteAudioEl.playbackRate = playbackRate.value || 1;

      const at = Math.max(0, currentContentTime());   // CONTENT time at cut
      remoteAudioBase = at;                 // stream position 0 == content `at`
      remoteSettleUntil = Date.now() + 2000; // let the buffer establish first

      const token = ++remoteRestartToken;
      const el = remoteAudioEl;
      el.src = buildRemoteAudioUrl(trackIndex, at);
      // IMPORTANT: do NOT set el.currentTime to the absolute content time —
      // the piped ADTS stream is 0-based and non-seekable beyond its buffer.

      // Robust playback start: retry a few times in case the element is not
      // ready yet or an AbortError raced with pause/play mirroring.
      const tryPlay = (attempt) => {
        if (token !== remoteRestartToken || !isRemoteAudioActive()) return;
        const p = el.play();
        if (p && typeof p.catch === "function") {
          p.catch((err) => {
            if (token !== remoteRestartToken) return;
            if (err && err.name === "AbortError") return;   // superseded by pause/mirror
            if (attempt < 3) setTimeout(() => tryPlay(attempt + 1), 200 * (attempt + 1));
          });
        }
      };
      tryPlay(0);
    }

    function detachRemoteAudio() {
      remoteRestartToken++;
      stopRemoteSyncLoop();
      if (remoteSeekDebounce) { clearTimeout(remoteSeekDebounce); remoteSeekDebounce = null; }
      remoteRebuildCooldownUntil = 0;
      remoteAudioBase = 0;
      if (remoteAudioEl) {
        try {
          remoteAudioEl.pause();
          remoteAudioEl.removeAttribute("src");
          remoteAudioEl.load();
        } catch (e) {}
      }
      const v = videoRef.value;
      if (v) {
        // Restore only the user's own mute preference — never force-unmute
        v.muted = !!isMuted.value;
      }
    }

    // Keep the hidden audio glued to the video clock.
    function syncRemoteAudio(force = false) {
      if (!isRemoteAudioActive() || !remoteAudioEl || !videoRef.value) return;
      const v = videoRef.value;
      const a = remoteAudioEl;

      // Fatal element error → rebuild the stream once
      if (a.error) {
        attachRemoteAudio(streamState.audioTrack);
        return;
      }

      // Mirror transport state
      if (v.paused && !a.paused) a.pause();
      if (!v.paused && a.paused) a.play().catch(() => {});
      if (v.paused) return;

      const nowMs = Date.now();
      const settling =
        nowMs < remoteSettleUntil ||
        a.seeking ||
        a.readyState < 2;

      // HARD-DRIFT WATCHDOG — self-heals ANY missed seek regardless of cause
      // (e.g., seeking while the video was still loading fires no 'seeked'
      // event). Measures DIVERGENCE BETWEEN THE TWO CLOCKS (video position
      // minus audio position), NOT video advance-from-base — measuring the
      // latter grows unboundedly during normal playback and triggered an
      // endless kill/rebuild stutter (~1.6s cadence). A 4s divergence can
      // only exist if the audio genuinely failed to follow a seek.
      const streamDrift = (v.currentTime || 0) - remoteAudioBase - (a.currentTime || 0);
      if (
        Math.abs(streamDrift) > 4 &&
        nowMs > remoteRebuildCooldownUntil
      ) {
        remoteRebuildCooldownUntil = nowMs + 3000;
        attachRemoteAudio(streamState.audioTrack);
        return;
      }

      // SETTLE WINDOW: never chase the video while a freshly attached stream
      // is still filling its buffer, mid-seek, or below ready-state. Chasing
      // past delivered data is what stalls the element permanently.
      if (settling) return;

      // Convert both clocks to CONTENT time: expected position on the AUDIO
      // element's own (stream-relative) timeline for the video's current
      // content position.
      const rawExpected = playerToContent(v.currentTime || 0) - remoteAudioBase;

      // STALE BASE GUARD: video is at/before the point where this audio
      // stream was cut (e.g., a small backward seek whose rebuild is still
      // pending). Never clamp to zero here — that caused the audio to
      // loop its opening fragment. Silence until onVideoSeeked rebuilds
      // (or the watchdog above handles a large offset).
      if (rawExpected < -0.3) {
        if (!a.paused) a.pause();
        return;
      }
      const expected = Math.max(0, rawExpected);
      const delta = expected - a.currentTime;

      const baseRate = playbackRate.value || 1;
      if (force || Math.abs(delta) > 0.6) {
        const targetPos = Math.max(0, expected + 0.05);

        // NEVER chase beyond delivered data — that stalls the element
        // ("plays a little then stops"). Wait for the buffer to grow;
        // the next ticks will land the resync once data exists.
        let bEnd = 0;
        try {
          const b = a.buffered;
          if (b && b.length) bEnd = b.end(b.length - 1);
        } catch (e) {}
        if (delta > 0 && bEnd > 0 && targetPos > bEnd - 0.2) return;

        try { a.currentTime = targetPos; } catch (e) {}
        a.playbackRate = baseRate;
      } else if (Math.abs(delta) > 0.12) {
        // Gentle drift correction via playback rate (video ahead → speed up)
        a.playbackRate = Math.min(baseRate * 1.12, Math.max(baseRate * 0.88, baseRate + delta * 0.25));
      } else if (a.playbackRate !== baseRate) {
        a.playbackRate = baseRate;
      }
    }

    function startRemoteSyncLoop() {
      stopRemoteSyncLoop();
      remoteAudioTimer = setInterval(() => syncRemoteAudio(false), 300);
    }
    function stopRemoteSyncLoop() {
      if (remoteAudioTimer) { clearInterval(remoteAudioTimer); remoteAudioTimer = null; }
    }

    // ── Audio switching ─────────────────────────────────────────────
    async function selectAudioTrack(index) {
      if (index === null || index === undefined) return;
      if (streamState.audioTrack === index) {
        showAudioMenu.value = false;
        return;
      }
      saveProgressNow();
      suppressResume = true;

      streamState.audioTrack = index;
      showAudioMenu.value = false;
      trackPlayerFeature("audio");

      // NOTE: the <video> element is NOT reloaded. Only the audio routing
      // changes, so playback continues seamlessly at the exact same frame.
      if (isRemoteAudioActive()) {
        attachRemoteAudio(index);
        startRemoteSyncLoop();
      } else {
        detachRemoteAudio();
      }

      API.post("/api/achievements/unlock", { achievement_id: "audio_enthusiast" }).catch(() => {});
    }

    // ── Quality options ─────────────────────────────────────────────
    const qualityOptions = ref([]);
    const selectedQualityMediaId = ref(null);
    const showQualityMenu = ref(false);

    // Only offer switching when another REAL alternative exists.
    const canSwitchQuality = computed(() =>
      !!media.value &&
      media.value.type === "movie" &&
      qualityOptions.value.some((o) => !o.is_current && o.media_id !== selectedQualityMediaId.value)
    );

    async function loadQualityOptions(mediaId) {
      try {
        const opts = await API.get(`/api/quality-options/${mediaId}`);
        qualityOptions.value = opts || [];
        const current = qualityOptions.value.find((o) => o.is_current);
        if (current) {
          selectedQualityMediaId.value = current.media_id;
        } else if (qualityOptions.value.length > 0) {
          selectedQualityMediaId.value = qualityOptions.value[0].media_id;
        }
      } catch (e) {
        qualityOptions.value = [];
      }
    }

    async function selectQuality(option) {
      if (!option || option.media_id === selectedQualityMediaId.value) {
        showQualityMenu.value = false;
        return;
      }
      showQualityMenu.value = false;
      trackPlayerFeature("quality");
      suppressResume = true;
      saveProgressNow();

      // Preserve BOTH the position AND the chosen audio track across files.
      // The remote audio (if any) is re-pointed at the new file by
      // syncRemoteAudio once the new video source reports its position.
      const atContent = currentContentTime();
      selectedQualityMediaId.value = option.media_id;
      streamState.mediaId = option.media_id;
      swapStream(atContent);

      API.post("/api/achievements/unlock", { achievement_id: "quality_switcher" }).catch(() => {});
    }

    const showHoverTooltip = ref(null);
    const showSkipModal = ref(false);

    const activeSkipAction = computed(() => {
      // Skip windows are stored in ABSOLUTE content time — compare against
      // content time, not raw player time.
      const ct = Math.floor(playerToContent(currentTime.value));
      if (!media.value || ct <= 0) return null;

      // 1. Manual DB Timestamps (Highest Priority)
      const rStart = media.value.recap_start || 0;
      const rEnd = media.value.recap_end || 0;
      if (rEnd > rStart && ct >= rStart && ct < rEnd) {
        return { type: "Recap", start: rStart, end: rEnd };
      }

      const iStart = media.value.intro_start || 0;
      const iEnd = media.value.intro_end || 0;
      if (iEnd > iStart && ct >= iStart && ct < iEnd) {
        return { type: "Intro", start: iStart, end: iEnd };
      }

      const oStart = media.value.outro_start || 0;
      const oEnd = media.value.outro_end || 0;
      if (oEnd > oStart && ct >= oStart && ct < oEnd) {
        return { type: "Outro", start: oStart, end: oEnd };
      }

      const pStart = media.value.preview_start || 0;
      const pEnd = media.value.preview_end || 0;
      if (pEnd > pStart && ct >= pStart && ct < pEnd) {
        return { type: "Preview", start: pStart, end: pEnd };
      }

      // 2. Auto-resolved segments (secondary): AniSkip for detected anime,
      //    otherwise FFprobe embedded chapters. Manual markers always win.
      if (skipTimes.value) {
        if (skipTimes.value.recap && ct >= skipTimes.value.recap.start && ct < skipTimes.value.recap.end) {
          return { type: "Recap", start: skipTimes.value.recap.start, end: skipTimes.value.recap.end };
        }
        if (skipTimes.value.op && ct >= skipTimes.value.op.start && ct < skipTimes.value.op.end) {
          return { type: "Intro", start: skipTimes.value.op.start, end: skipTimes.value.op.end };
        }
        if (skipTimes.value.ed && ct >= skipTimes.value.ed.start && ct < skipTimes.value.ed.end) {
          return { type: "Outro", start: skipTimes.value.ed.start, end: skipTimes.value.ed.end };
        }
        if (skipTimes.value.preview && ct >= skipTimes.value.preview.start && ct < skipTimes.value.preview.end) {
          return { type: "Preview", start: skipTimes.value.preview.start, end: skipTimes.value.preview.end };
        }
      }

      // 3. Tail fallback — nothing marked/skipped here and a next episode
      //    exists: offer it during the final stretch of the title.
      if (
        nextEp.value &&
        displayDuration.value > 0 &&
        ct >= displayDuration.value - 90 &&
        ct < displayDuration.value
      ) {
        return { type: "Next", start: Math.max(0, displayDuration.value - 90), end: displayDuration.value };
      }

      return null;
    });

    // Keyframe-align a content timestamp for converted-stream restarts.
    async function alignedStreamStart(contentTime) {
      let target = Math.max(0, Math.floor(contentTime));
      try {
        const id = streamState.mediaId || route.params.id;
        const r = await API.get(`/api/stream-start/${id}?start=${target}`);
        if (r && typeof r.start === "number") target = r.start;
      } catch (e) {}
      return target;
    }

    function seekTo(targetTime) {
      if (!videoRef.value) return;
      const maxDur = media.value?.duration || duration.value || 0;
      const validTarget = Math.min(Math.max(0, targetTime), maxDur > 0 ? maxDur : targetTime);
      suppressResume = true;

      if (streamState.transcode) {
        // Converted stream: align to keyframe, restart stream there
        isBuffering.value = true;
        const token = ++reloadToken;
        alignedStreamStart(validTarget).then((startAt) => {
          if (token !== reloadToken) return;
          streamState.streamStart = startAt;
          swapStream(0);
        });
      } else {
        // Video seeks natively (range requests). The remote audio element is
        // re-pointed at the new position by the seeked-hook below.
        videoRef.value.currentTime = validTarget;
        currentTime.value = validTarget;
      }
      saveProgressNow();
    }

    function executeSkipAction() {
      const action = activeSkipAction.value;
      if (!action) return;

      // "Next Episode" tail action (no outro marker, or already past it)
      if (action.type === "Next") {
        handleNextEpClick();
        return;
      }

      // Outro: always just skip PAST the credits window — the Next Episode
      // pill takes over afterwards when there's a following episode.
      seekTo(action.end);

      // Skip Champion: count intro/recap/outro skip uses across sessions
      try {
        const count = (parseInt(localStorage.getItem("cs_skip_count") || "0", 10) || 0) + 1;
        localStorage.setItem("cs_skip_count", String(count));
        if (count >= 10) unlockAchievementSilently("skip_champion");
      } catch (e) {}
    }

    // ─── 4K HEVC Playback Risk Guard ────────────────────────────────
    // Software-decoding 4K (10-bit) HEVC exhausts browser renderers and can
    // crash the whole tab. Probe actual HEVC decode support up-front and
    // surface a small dismissible advisory instead of letting the tab die
    // silently.
    const codecInfo = computed(() => {
      if (!media.value) return { hasWarning: false, tags: [], note: "", base_label: "", width: 0, height: 0 };
      return getCodecInfo(media.value.file_path || "");
    });

    const hevcSupported = (() => {
      try {
        const probe = document.createElement("video");
        return [
          'video/mp4; codecs="hvc1.1.6.L153.B0"',
          'video/mp4; codecs="hev1.1.6.L153.B0"',
          'video/mp4; codecs="hvc1"',
        ].some((t) => (probe.canPlayType(t) || "") !== "");
      } catch (e) {
        return false;
      }
    })();

    const warningDismissed = ref(false);
    const playbackWarning = computed(() => {
      if (!media.value || !codecInfo.value.hasWarning) return null;
      const p = (media.value.file_path || "").toLowerCase();
      const isHevc = codecInfo.value.tags.some((t) => t.includes("HEVC"));
      const is4k =
        p.includes("2160") || p.includes("4k") || p.includes("uhd");

      if (isHevc && !hevcSupported) {
        return {
          icon: "ph ph-warning-octagon",
          title: "HEVC decoding unsupported",
          msg: "This browser cannot decode HEVC — playback may fail or crash the tab. Use Microsoft Edge with hardware acceleration enabled.",
        };
      }
      if (isHevc && is4k) {
        return {
          icon: "ph ph-warning",
          title: "4K HEVC — high decode load",
          msg: "Without hardware acceleration, 4K HEVC can crash the browser. Enable hardware acceleration in browser settings if playback stutters.",
        };
      }
      if (is4k) {
        return {
          icon: "ph ph-gauge",
          title: "4K content — demanding decode",
          msg: "If playback stutters or becomes unresponsive, close other apps or switch to a lower-quality source.",
        };
      }
      return null;
    });

    function dismissPlaybackWarning() {
      warningDismissed.value = true;
    }

    // ─── Hardware-accelerated compatibility playback ────────────────
    const compatInfo = ref(null);
    let compatCapsFetched = false;

    function fetchCompatCaps() {
      if (compatCapsFetched) return;
      compatCapsFetched = true;
      API.get("/api/transcode-caps")
        .then((c) => { compatInfo.value = c || { available: false }; })
        .catch(() => { compatInfo.value = { available: false }; });
    }

    async function enableCompatPlayback() {
      if (!media.value) return;
      suppressResume = true;
      isBuffering.value = true;
      const token = ++reloadToken;
      const at = currentContentTime();
      const startAt = await alignedStreamStart(at);
      if (token !== reloadToken) return;   // superseded
      streamState.transcode = true;
      streamState.streamStart = startAt;
      swapStream(0);
    }

    function disableCompatPlayback() {
      suppressResume = true;
      streamState.transcode = false;
      streamState.streamStart = 0;
      reloadToken++;
      swapStream(currentContentTime());
    }

    // Fetch encoder capabilities once when the risk advisory appears
    watch(playbackWarning, (w) => {
      if (w) fetchCompatCaps();
    });

    function handleSkipSaved(updatedData) {
      if (media.value) {
        // Instant priority: manual fields drive activeSkipAction right away
        Object.assign(media.value, updatedData);
      }
      // Re-resolve segments (seekbar overlays + floating skip buttons read
      // skipTimes, not media fields). Server returns fresh manual-first data,
      // so new/edited/cleared markers appear with NO reload needed.
      loadSkipTimes(route.params.id);
    }

    // NOTE: auto-skip is handled by checkAutoSkip() inside onTimeUpdate —
    // it reads the live playerSettings and covers manual markers first.
    const hoverTooltipPos = ref(0);
    const hoverTooltipTime = ref(0);

    let hideTimer = null;
    let progressTimer = null;
    let stallTimer = null;

    const activeStreamMediaId = computed(() => selectedQualityMediaId.value || route.params.id);
    // Display timeline: CONTENT time vs the title's REAL duration. In
    // converted mode the piped stream reports bogus/tiny durations, so we
    // anchor to the DB duration and content-converted position instead.
    const displayDuration = computed(() => {
      const md = Number(media.value?.duration) || 0;
      if (md > 0) return md;
      const d = Number(duration.value);
      return isFinite(d) && d > 0 ? d : 0;
    });
    const displayTime = computed(() => playerToContent(currentTime.value));
    const progressPercent = computed(() => {
      if (!displayDuration.value) return 0;
      const pct = (Math.min(displayTime.value, displayDuration.value) / displayDuration.value) * 100;
      return Math.max(0, Math.min(100, pct));
    });

    // Wall-clock time the title will finish, e.g. "11:42 PM" (updates live)
    const endClockTime = computed(() => {
      const dur = Number(duration.value) || Number(media.value?.duration) || 0;
      if (!dur || dur <= 0) return "";
      const remainingSec = Math.max(0, dur - (Number(currentTime.value) || 0));
      if (!isFinite(remainingSec)) return "";
      const d = new Date(Date.now() + remainingSec * 1000);
      let h = d.getHours();
      const m = String(d.getMinutes()).padStart(2, "0");
      const ampm = h >= 12 ? "PM" : "AM";
      h = h % 12 || 12;
      return `${h}:${m} ${ampm}`;
    });

    function showControls() {
      controlsHidden.value = false;
      clearTimeout(hideTimer);
      if (videoRef.value && !videoRef.value.paused) {
        hideTimer = setTimeout(() => {
          controlsHidden.value = true;
          showSpeedMenu.value = false;
          showSubMenu.value = false;
          showAudioMenu.value = false;
          showQualityMenu.value = false;
        }, 3500);
      }
    }

    async function saveProgressNow() {
      if (!store.profile || !media.value?.id) return;
      // currentTime is PLAYER time — convert to absolute content time for storage
      const rawPos = Math.floor(playerToContent(currentTime.value || (videoRef.value ? videoRef.value.currentTime : 0)));
      const pos = rawPos;
      const dur = Math.floor(media.value.duration || duration.value || (videoRef.value ? videoRef.value.duration : 0));
      if (pos < 5) return;
      const completed = dur > 0 && pos >= dur * 0.9;

      // keepalive: true lets the request complete even if the page is being
      // unloaded (refresh / close / navigate) — this is what makes Continue
      // Watching stick reliably. One silent retry covers transient server load.
      async function post(attempt) {
        try {
          const r = await fetch("/api/progress", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              media_id: Number(media.value.id),
              position: pos,
              duration: dur,
              completed,
            }),
            keepalive: true,
          });
          if (!r.ok) throw new Error(`status ${r.status}`);
          return await r.json().catch(() => null);
        } catch (e) {
          if (attempt < 1) {
            await new Promise((res) => setTimeout(res, 750));
            return post(attempt + 1);
          }
          return null;
        }
      }

      const res = await post(0);
      // Watch-progress achievements: show only the newest as the minimal pill
      if (res && res.unlocked_achievements && res.unlocked_achievements.length) {
        showPlayerAchievement(res.unlocked_achievements[res.unlocked_achievements.length - 1]);
      }
    }

    function flushProgressOnHide() {
      saveProgressNow();
    }

    function handleVisibilityChange() {
      if (document.hidden) saveProgressNow();
    }

    let hasAutoFullscreened = false;

    function togglePlay() {
      if (!videoRef.value) return;
      if (videoRef.value.paused) {
        const p = videoRef.value.play();
        if (p && typeof p.then === "function") {
          p.then(() => {
            isPlaying.value = true;
            playerError.value = null;
            maybeAutoFullscreen();
          }).catch((err) => {
            console.log("Autoplay / play interaction handled:", err);
            isPlaying.value = false;
          });
        } else {
          isPlaying.value = true;
          maybeAutoFullscreen();
        }
      } else {
        videoRef.value.pause();
        isPlaying.value = false;
        saveProgressNow();
        if (store.profile?.is_kids) {
          unlockAchievementSilently("kids_play_pause");
        }
      }
    }

    function maybeAutoFullscreen() {
      if (hasAutoFullscreened) return;
      if (!playerSettings.value?.playback?.auto_fullscreen) return;
      hasAutoFullscreened = true;
      const container = videoRef.value?.closest(".custom-player-wrapper") || videoRef.value?.parentElement;
      if (container && container.requestFullscreen) {
        container.requestFullscreen().catch(() => {});
        isFullscreen.value = true;
      }
    }

    function handleContainerClick(e) {
      if (e.target.closest(".custom-player-controls")) return;
      togglePlay();
    }

    function skip(seconds) {
      if (!videoRef.value) return;
      const step = seconds !== undefined && seconds !== null ? seconds : playerSettings.value?.playback?.seek_step || 10;
      // currentTime is player time - seekTo expects CONTENT time
      const targetTime = Math.min(Math.max(0, playerToContent((currentTime.value || 0) + step)), duration.value || 0);
      triggerSeekOSD(step >= 0 ? "forward" : "back", Math.abs(step));
      seekTo(targetTime);
    }

    // ─── Minimal OSDs (volume bar / seek flash) ──────────────
    const volumeOSD = ref(false);
    let volumeOSDTimer = null;
    const volumeOSDPct = computed(() => {
      if (isMuted.value) return 0;
      return Math.max(0, Math.min(100, Math.round((Number(volume.value) || 0) * 100)));
    });
    function triggerVolumeOSD() {
      volumeOSD.value = true;
      clearTimeout(volumeOSDTimer);
      volumeOSDTimer = setTimeout(() => { volumeOSD.value = false; }, 1000);
    }
    watch(volume, () => triggerVolumeOSD());
    watch(isMuted, () => triggerVolumeOSD());

    const seekOSD = ref(null);
    let seekOSDTimer = null;
    function triggerSeekOSD(dir, seconds) {
      seekOSD.value = { dir, seconds };
      clearTimeout(seekOSDTimer);
      seekOSDTimer = setTimeout(() => { seekOSD.value = null; }, 800);
    }

    function onVideoSeeked() {
      // After a native video seek, decide how to realign the remote audio:
      //
      //  1. SLIDE — if the new position is still covered by the audio
      //     element's own buffered stream (typical small backward seeks),
      //     just move the element. Instant and seamless, nothing restarts.
      //  2. REBUILD — otherwise cut a fresh audio stream at the new position
      //     (debounced so dragging the bar doesn't spawn one per tick).
      //     While waiting, the element stays SILENT — never left playing
      //     from a stale base (that caused repeat-looping audio).
      if (!isRemoteAudioActive() || !remoteAudioEl || !videoRef.value) return;
      const v = videoRef.value;
      const a = remoteAudioEl;

      let bufferedEnd = 0;
      try {
        const b = a.buffered;
        if (b && b.length) bufferedEnd = b.end(b.length - 1);
      } catch (e) {}

      const relTarget = v.currentTime - remoteAudioBase;
      if (relTarget >= 0 && relTarget <= Math.max(0, bufferedEnd - 0.25)) {
        // Slide inside the existing stream
        try { a.currentTime = Math.max(0, relTarget); } catch (e) {}
        a.play().catch(() => {});
        return;
      }

      // Rebuild path — silence immediately, never loop stale audio
      try { a.pause(); } catch (e) {}
      if (remoteSeekDebounce) clearTimeout(remoteSeekDebounce);
      remoteSeekDebounce = setTimeout(() => {
        remoteSeekDebounce = null;
        attachRemoteAudio(streamState.audioTrack);
      }, 180);
    }

    function toggleMute() {
      if (!videoRef.value) return;
      isMuted.value = !isMuted.value;
      if (isRemoteAudioActive() && remoteAudioEl) {
        // Remote mode: video stays muted; mute intent applies to the audio element
        videoRef.value.muted = true;
        remoteAudioEl.muted = isMuted.value;
      } else {
        videoRef.value.muted = isMuted.value;
      }
      API.post("/api/achievements/unlock", { achievement_id: "mute_master" }).catch(() => {});
    }

    let audioCtx = null;
    let gainNode = null;
    let audioSource = null;

    function initAudioBoost() {
      if (audioCtx || !videoRef.value) return;
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContext();
        gainNode = audioCtx.createGain();
        audioSource = audioCtx.createMediaElementSource(videoRef.value);
        audioSource.connect(gainNode);
        gainNode.connect(audioCtx.destination);
      } catch (e) {
        console.log("AudioContext init notice:", e);
      }
    }

    function onVolumeInput(e) {
      const val = parseFloat(e.target.value);
      volume.value = val;

      // Remote-audio mode: route volume to the audio element. The video is
      // muted, so its boost graph is irrelevant here (no >1x boost remotely).
      if (isRemoteAudioActive() && remoteAudioEl) {
        remoteAudioEl.volume = Math.min(1, Math.max(0, val));
        remoteAudioEl.muted = val === 0;
        if (videoRef.value) {
          videoRef.value.muted = true;
          videoRef.value.volume = 1.0;
        }
        isMuted.value = val === 0;
        return;
      }

      if (videoRef.value) {
        if (val > 1.0) {
          initAudioBoost();
          videoRef.value.volume = 1.0;
          if (gainNode) gainNode.gain.value = val;
          if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
          unlockAchievementSilently("volume_booster");
        } else {
          if (gainNode) gainNode.gain.value = 1.0;
          videoRef.value.volume = val;
        }
        videoRef.value.muted = val === 0;
        isMuted.value = val === 0;
      }
    }

    // Record routine playback achievements and surface them as a MINIMAL
    // pill on the LEFT side of the player — never the large overlay, which
    // covered the right side (next-episode card / controls).
    const playerAch = ref(null);
    let playerAchTimer = null;
    function showPlayerAchievement(ach) {
      if (!ach) return;
      playAchievementSound();
      playerAch.value = {
        icon: ach.icon || "🏆",
        title: store.profile?.is_kids ? `⭐ Badge Unlocked: ${ach.title}` : (ach.title || "Achievement Unlocked!"),
        isKids: !!store.profile?.is_kids
      };
      if (playerAchTimer) clearTimeout(playerAchTimer);
      playerAchTimer = setTimeout(() => {
        playerAch.value = null;
      }, 2800);
    }
    function unlockAchievementSilently(achievementId) {
      API.post("/api/achievements/unlock", { achievement_id: achievementId })
        .then((res) => {
          if (res && res.unlocked) showPlayerAchievement(res.unlocked);
        })
        .catch(() => {});
    }

    function seekToClick(e) {
      if (!seekbarRef.value || !duration.value) return;
      const rect = seekbarRef.value.getBoundingClientRect();
      const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      // Seekbar is player-relative — seekTo expects CONTENT time
      const targetTime = playerToContent(pos * displayDuration.value);
      seekTo(targetTime);
      unlockAchievementSilently("seeker");
    }

    function hoverSeekbar(e) {
      if (!seekbarRef.value || !displayDuration.value) return;
      const rect = seekbarRef.value.getBoundingClientRect();
      const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      hoverTooltipPos.value = e.clientX - rect.left;
      hoverTooltipTime.value = pos * displayDuration.value;
      showHoverTooltip.value = true;
    }

    const nextEpHover = ref(false);
    let nextEpHideTimer = null;
    function showNextPreview() {
      if (nextEpHideTimer) { clearTimeout(nextEpHideTimer); nextEpHideTimer = null; }
      nextEpHover.value = true;
    }
    function hideNextPreview() {
      if (nextEpHideTimer) clearTimeout(nextEpHideTimer);
      // Small delay bridges the gap between the button and the floating card
      nextEpHideTimer = setTimeout(() => { nextEpHover.value = false; }, 180);
    }
    const hasNextEp = computed(() => {
      return !!(
        nextEp.value &&
        nextEp.value.id &&
        nextEp.value.is_local !== false &&
        nextEp.value.is_mounted !== false
      );
    });

    const showNextEp = computed(() => hasNextEp.value);

    const showAutoAdvanceOverlay = computed(() => {
      if (!hasNextEp.value || !duration.value || duration.value === 0) return false;
      const remaining = displayDuration.value - displayTime.value;
      return remaining <= 90 || (displayDuration.value && displayTime.value / displayDuration.value >= 0.85);
    });

    function selectSpeed(rate) {
      playbackRate.value = rate;
      if (videoRef.value) videoRef.value.playbackRate = rate;
      // Mirror playback speed to the remote audio element
      if (isRemoteAudioActive() && remoteAudioEl) remoteAudioEl.playbackRate = rate;
      showSpeedMenu.value = false;
      trackPlayerFeature("speed");

      let achId = null;
      if (rate >= 2.0) achId = "double_speed";
      else if (rate <= 0.5) achId = "slow_motion";
      else if (rate >= 1.25) achId = "speed_demon";

      if (achId) {
        unlockAchievementSilently(achId);
      }
    }

    // ─── Subtitle pipeline ──────────────────────────────────────────
    // Subtitle cues carry absolute content timestamps. The video now ALWAYS
    // plays natively from the real file, so player time === content time and
    // the offset is permanently zero — this function is kept as an identity
    // safety-net (it restores original cue timings if they were ever shifted).
    function applySubtitleOffset() {
      const video = videoRef.value;
      if (!video || !video.textTracks) return;
      const offset = streamState.transcode ? (streamState.streamStart || 0) : 0;
      const tracks = video.textTracks;
      for (let i = 0; i < tracks.length; i++) {
        const cues = tracks[i].cues;
        if (!cues || cues.length === 0) continue;
        const list = Array.from(cues);
        for (const cue of list) {
          if (cue._origStart === undefined) {
            cue._origStart = cue.startTime;
            cue._origEnd = cue.endTime;
          }
          const s = Math.max(0, cue._origStart - offset);
          const e = Math.max(0, cue._origEnd - offset);
          if (cue.startTime !== s) cue.startTime = s;
          if (cue.endTime !== e) cue.endTime = e;
        }
      }
    }

    // Cues load ASYNC after every stream swap. The TextTrack 'load' event is
    // the only reliable signal that cues are ready — hook each track once and
    // re-apply the offset whenever its cues arrive.
    function hookTextTrack(track) {
      if (!track || track._capsHooked) return;
      track._capsHooked = true;
      track.addEventListener("load", () => {
        applySubtitleOffset();
        setTimeout(applySubtitleOffset, 150);
      });
      track.addEventListener("error", () => {
        console.warn("[Player] Subtitle track failed to load:", track.label);
      });
    }

    function syncTextTracks() {
      if (!videoRef.value) return;
      const tracks = videoRef.value.textTracks;
      if (!tracks || tracks.length === 0) return;
      for (let i = 0; i < tracks.length; i++) hookTextTrack(tracks[i]);
      applySubtitleOffset();
      const activeIdx = selectedSub.value;
      for (let i = 0; i < tracks.length; i++) {
        try {
          const newMode = i === activeIdx ? "hidden" : "disabled";
          if (tracks[i].mode !== newMode) {
            tracks[i].mode = newMode;
          }
          // Attach cuechange listener on active track for instant subtitle updates
          if (i === activeIdx) {
            tracks[i].oncuechange = updateActiveCueText;
          } else {
            tracks[i].oncuechange = null;
          }
        } catch (e) {}
      }
    }

    function selectSub(index) {
      selectedSub.value = index;
      showSubMenu.value = false;
      if (index >= 0) {
        unlockAchievementSilently("sub_master");
        trackPlayerFeature("subs");
      }
      nextTick(() => {
        syncTextTracks();
        setTimeout(syncTextTracks, 100);
        setTimeout(syncTextTracks, 300);
      });
    }

    // A subtitle track failed to load (404 — e.g. ffmpeg could not convert
    // the embedded stream). Drop it from the menu so it can't be picked again.
    function onSubtitleTrackError(sub) {
      const idx = subtitles.value.indexOf(sub);
      if (idx === -1) return;
      subtitles.value.splice(idx, 1);
      if (selectedSub.value === idx) {
        selectedSub.value = -1;
      } else if (selectedSub.value > idx) {
        selectedSub.value--;
      }
      console.warn(`[Player] Subtitle track unavailable, removed: ${sub.label || sub.filename}`);
    }

    function onVideoPlaying() {
      isPlaying.value = true;
      isBuffering.value = false;
      playerError.value = null;
      syncTextTracks();
      setTimeout(syncTextTracks, 150);
      // Instantly resume the remote audio track with the video
      if (isRemoteAudioActive() && remoteAudioEl) {
        remoteAudioEl.play().catch(() => {});
      }
      showControls();
    }

    function onVideoPause() {
      isPlaying.value = false;
      controlsHidden.value = false;
      clearTimeout(hideTimer);
      // Instantly pause the remote audio track with the video
      if (isRemoteAudioActive() && remoteAudioEl) remoteAudioEl.pause();
    }

    watch(
      [subtitles, selectedSub],
      () => {
        nextTick(() => {
          syncTextTracks();
          setTimeout(syncTextTracks, 100);
          setTimeout(syncTextTracks, 300);
        });
      },
      { deep: true }
    );

    // Watch serverOnline for seamless video playback recovery on reconnection
    watch(
      () => store.serverOnline,
      (isOnline, wasOnline) => {
        if (isOnline && wasOnline === false && videoRef.value) {
          const pos = currentContentTime();
          console.log("[Player] Server reconnected. Restoring stream playback at position:", pos);
          swapStream(pos);
          if (isRemoteAudioActive()) {
            attachRemoteAudio(streamState.audioTrack);
          }
        }
      }
    );

    const subStyle = ref({
      fontSize: "1.1rem",
      textColor: "#ffffff",
      bgOpacity: 0.5
    });

    async function loadSubStyleFromConfig() {
      try {
        const cfg = await API.get("/api/settings");
        if (cfg && cfg.subtitles && cfg.subtitles.appearance) {
          subStyle.value = { ...subStyle.value, ...cfg.subtitles.appearance };
        }
      } catch (e) {}
      applySubStyleCSS();
    }

    async function updateSubStyle(key, value) {
      subStyle.value[key] = value;
      applySubStyleCSS();
      unlockAchievementSilently("sub_styler");
      try {
        await API.post("/api/settings", {
          subtitles: {
            appearance: { ...subStyle.value }
          }
        });
      } catch (e) {}
    }

    const activeCueText = ref("");

    // Sanitize raw VTT cue text. FFmpeg's ASS/SSA -> VTT conversion often
    // fragments styled lines into ONE CHARACTER PER LINE cues (karaoke /
    // position tags), which the overlay would render as a vertical letter
    // stack. Collapse that pathology and cap visible lines.
    function sanitizeCueText(raw) {
      if (!raw) return "";
      let t = String(raw).replace(/<[^>]*>/g, "");
      let lines = t
        .split(/\r?\n/)
        .map((l) => l.replace(/[\u200b\u200e\u200f]/g, "").replace(/[ \t]+/g, " ").trim())
        .filter(Boolean);
      if (lines.length === 0) return "";

      // Degenerate fragmentation: many single-character lines → fuse them
      const singleChar = lines.filter((l) => Array.from(l).length === 1).length;
      if (lines.length > 2 && singleChar / lines.length >= 0.6) {
        return lines.join("").replace(/\s+/g, " ").trim();
      }
      return lines.slice(0, 3).join("\n");
    }

    const subOffsetMs = ref(0);

    function adjustSubOffset(deltaMs) {
      subOffsetMs.value += deltaMs;
      const displayStr = subOffsetMs.value === 0 ? "0 ms (In Sync)" : (subOffsetMs.value > 0 ? `+${subOffsetMs.value} ms` : `${subOffsetMs.value} ms`);
      addToast(`Subtitle Delay: ${displayStr}`, "info", 1500);
      updateActiveCueText();
    }

    function resetSubOffset() {
      subOffsetMs.value = 0;
      addToast("Subtitle Delay Reset: 0 ms (In Sync)", "info", 1500);
      updateActiveCueText();
    }

    function updateActiveCueText() {
      try {
        if (!videoRef.value) return;
        const tracks = videoRef.value.textTracks;
        if (!tracks || selectedSub.value < 0 || !tracks[selectedSub.value]) {
          activeCueText.value = "";
          return;
        }
        const track = tracks[selectedSub.value];
        const offsetSec = (subOffsetMs.value || 0) / 1000;
        const now = currentTime.value - offsetSec;

        // Primary: manual cue scan using currentTime.value (total media time).
        if (track.cues && track.cues.length > 0) {
          const active = [];
          for (let i = 0; i < track.cues.length; i++) {
            const c = track.cues[i];
            if (c && now >= c.startTime && now <= c.endTime) {
              const s = sanitizeCueText(c.text);
              if (s) active.push(s);
            }
          }
          activeCueText.value = active.length > 0 ? active.join("\n") : "";
          return;
        }

        // Secondary fallback: browser-managed activeCues.
        if (track.activeCues && track.activeCues.length > 0) {
          const active = [];
          for (let i = 0; i < track.activeCues.length; i++) {
            if (track.activeCues[i]) {
              const s = sanitizeCueText(track.activeCues[i].text);
              if (s) active.push(s);
            }
          }
          activeCueText.value = active.length > 0 ? active.join("\n") : "";
          return;
        }

        activeCueText.value = "";
      } catch (err) {
        console.warn("Subtitle update error:", err);
        activeCueText.value = "";
      }
    }

    const customCueStyle = computed(() => {
      const { fontSize, textColor, bgOpacity } = subStyle.value;
      const pxSize = fontSize === "0.85rem" ? "18px" : fontSize === "1.4rem" ? "30px" : fontSize === "1.8rem" ? "40px" : "24px";
      const bg = bgOpacity === 0 ? "transparent" : `rgba(0, 0, 0, ${bgOpacity})`;
      return {
        display: "inline-block",
        width: "fit-content",
        fontSize: pxSize,
        color: textColor,
        backgroundColor: bg,
        textShadow: "0 2px 8px rgba(0,0,0,0.95), 0 0 2px rgba(0,0,0,0.95)",
        padding: "6px 14px",
        borderRadius: "6px",
        position: "absolute",
        bottom: controlsHidden.value ? "35px" : "105px",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: "14",
        maxWidth: "80%",
        textAlign: "center",
        pointerEvents: "none",
        whiteSpace: "pre-line",
        fontWeight: "600",
        transition: "bottom 0.25s ease, font-size 0.2s ease, color 0.2s ease, background 0.2s ease"
      };
    });

    function applySubStyleCSS() {
      let styleEl = document.getElementById("caps-sub-style-el");
      if (!styleEl) {
        styleEl = document.createElement("style");
        styleEl.id = "caps-sub-style-el";
        document.head.appendChild(styleEl);
      }
      const { fontSize, textColor, bgOpacity } = subStyle.value;
      const pxSize = fontSize === "0.85rem" ? "20px" : fontSize === "1.4rem" ? "34px" : fontSize === "1.8rem" ? "44px" : "26px";
      const bg = bgOpacity === 0 ? "transparent" : `rgba(0, 0, 0, ${bgOpacity})`;
      styleEl.textContent = `
        video::cue {
          font-size: ${pxSize} !important;
          color: ${textColor} !important;
          background-color: ${bg} !important;
          background: ${bg} !important;
          text-shadow: 0 2px 8px rgba(0,0,0,0.95), 0 0 2px rgba(0,0,0,0.95) !important;
          line-height: 1.3 !important;
        }
        video::-webkit-media-text-track-display,
        video::-webkit-media-text-track-container,
        video::-webkit-media-text-track-region {
          background: transparent !important;
          background-color: transparent !important;
        }
      `;
    }

    onMounted(loadSubStyleFromConfig);

    function handleCustomSubFile(e) {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (event) => {
        let content = event.target.result;
        if (file.name.toLowerCase().endsWith(".srt")) {
          content = convertSrtToVtt(content);
        }
        const blob = new Blob([content], { type: "text/vtt" });
        const url = URL.createObjectURL(blob);
        const newSub = { label: file.name.replace(/\.(vtt|srt)$/i, ""), url };
        if (!subtitles.value) subtitles.value = [];
        subtitles.value.push(newSub);
        selectSub(subtitles.value.length - 1);
        addToast(`Loaded subtitle: ${file.name}`, "success");
      };
      reader.readAsText(file);
    }

    const isPipActive = ref(false);
    const isPipSupported = computed(() => {
      return typeof document !== "undefined" && "pictureInPictureEnabled" in document && document.pictureInPictureEnabled;
    });

    async function togglePip() {
      if (!videoRef.value) return;
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
          isPipActive.value = false;
        } else {
          await videoRef.value.requestPictureInPicture();
          isPipActive.value = true;
        }
      } catch (e) {
        console.log("Picture-in-Picture interaction:", e);
        addToast("Unable to toggle Picture-in-Picture", "error");
      }
    }

    function bindPipListeners() {
      if (!videoRef.value) return;
      videoRef.value.addEventListener("enterpictureinpicture", () => {
        isPipActive.value = true;
        addToast("Entered Picture-in-Picture 📺", "info");
        unlockAchievementSilently("pip_master");
      });
      videoRef.value.addEventListener("leavepictureinpicture", () => {
        isPipActive.value = false;
        addToast("Exited Picture-in-Picture", "info");
      });
    }

    const showResumeModal = ref(false);
    const resumeTime = ref(0);

    const skipTimes = ref({});
    const autoSkippedOp = ref(false);
    const autoSkippedEd = ref(false);

    async function loadSkipTimes(mediaId) {
      try {
        const data = await API.get(`/api/skip-times/${mediaId}`);
        skipTimes.value = data || {};
      } catch (e) {
        skipTimes.value = {};
      }
    }

    // ─── OpenSubtitles download ─────────────────────────────────
    const downloadingSubs = ref(false);

    // ─── Seekbar preview thumbnails ─────────────────────────────
    const thumbSheet = ref(null);
    let thumbRetryTimer = null;

    async function loadThumbSheet(mediaId) {
      thumbSheet.value = null;
      clearTimeout(thumbRetryTimer);
      try {
        const r = await API.get(`/api/media/${mediaId}/thumbnails`);
        if (r && r.ready) {
          thumbSheet.value = r;
        } else if (r && !r.ready) {
          // Sheet is generating in the background — retry once after 90s
          thumbRetryTimer = setTimeout(async () => {
            try {
              const r2 = await API.get(`/api/media/${mediaId}/thumbnails`);
              if (r2 && r2.ready) thumbSheet.value = r2;
            } catch (e) {}
          }, 90000);
        }
      } catch (e) {}
    }

    function thumbCellStyle(time) {
      const s = thumbSheet.value;
      if (!s) return {};
      const clamped = Math.max(0, Math.min(s.duration - 1, time));
      const idx = Math.min(s.count - 1, Math.floor(clamped / s.interval));
      const col = idx % s.cols;
      const row = Math.floor(idx / s.cols);
      const cellH = s.cell_height || Math.round(s.cell_width * 9 / 16);
      return {
        backgroundImage: `url(${s.url})`,
        backgroundPosition: `-${col * s.cell_width}px -${row * cellH}px`,
        width: s.cell_width + "px",
        height: cellH + "px",
      };
    }

    async function downloadSubtitles() {
      const mediaId = media.value?.id || route.params.id;
      if (!mediaId || downloadingSubs.value) return;
      downloadingSubs.value = true;
      try {
        const r = await API.post(`/api/media/${mediaId}/download-subtitles`, {});
        if (r.added > 0) {
          addToast(r.message, "success");
          // Reload the subtitle list — new external subs appear after saving
          const fresh = await API.get(`/api/media/${mediaId}`);
          subtitles.value = fresh?.subtitles || [];
          if (selectedSub.value === -1 && subtitles.value.length) {
            selectSub(0);
          }
        } else {
          addToast(r.message || "No subtitles found", "info", 5000);
        }
      } catch (e) {
        addToast(e.message || "Subtitle download failed", "error", 5000);
      } finally {
        downloadingSubs.value = false;
      }
    }

    async function maybeAutoDownloadSubs() {
      // Auto-download when the title has zero subtitles and the user opted in
      if (subtitles.value.length > 0) return;
      const cfg = playerSettings.value;
      if (!cfg?.subtitles?.auto_download || !cfg?.subtitles?.opensubtitles_api_key) return;
      const mediaId = media.value?.id || route.params.id;
      if (!mediaId) return;
      try {
        const r = await API.post(`/api/media/${mediaId}/download-subtitles`, {});
        if (r.added > 0) {
          addToast(`📺 ${r.message} — reloading subtitles`, "success", 5000);
          const fresh = await API.get(`/api/media/${mediaId}`);
          subtitles.value = fresh?.subtitles || [];
          if (subtitles.value.length) selectSub(0);
        }
      } catch (e) {}
    }

    const activeSkipButton = computed(() => {
      if (!skipTimes.value) return null;
      const time = currentTime.value;
      if (skipTimes.value.op && time >= skipTimes.value.op.start && time <= skipTimes.value.op.end - 1) {
        return { type: "op", label: "Skip Intro", target: skipTimes.value.op.end };
      }
      if (skipTimes.value.recap && time >= skipTimes.value.recap.start && time <= skipTimes.value.recap.end - 1) {
        return { type: "recap", label: "Skip Recap", target: skipTimes.value.recap.end };
      }
      if (skipTimes.value.ed && time >= skipTimes.value.ed.start && time <= skipTimes.value.ed.end - 1) {
        return { type: "ed", label: "Skip Outro", target: skipTimes.value.ed.end };
      }
      if (skipTimes.value.preview && time >= skipTimes.value.preview.start && time <= skipTimes.value.preview.end - 1) {
        return { type: "preview", label: "Skip Preview", target: skipTimes.value.preview.end };
      }
      return null;
    });

    function getSegmentStyle(segment) {
      const dur = displayDuration.value;
      if (!segment || !dur || dur < 10 || segment.start >= dur) return { display: "none" };
      // Segments are stored in CONTENT time; the seekbar shows PLAYER time.
      // In direct mode this is identity — in transcode mode it shifts by streamStart.
      const segStart = contentToPlayer(segment.start);
      const segEnd = contentToPlayer(segment.end);
      if (segEnd <= 0) return { display: "none" };
      const left = Math.max(0, Math.min(100, (segStart / dur) * 100));
      const width = Math.max(0, Math.min(100 - left, ((segEnd - segStart) / dur) * 100));
      return {
        left: `${left}%`,
        width: `${width}%`
      };
    }

    function performSkip(button) {
      if (!button) return;
      seekTo(button.target);
      unlockAchievementSilently("skip_master");
    }

    // Auto-skip: when enabled in settings, jump past Recap / Intro / Outro
    // windows (manual markers take priority, then AniSkip/chapters).
    // Outro auto-skips by seeking to its end — episode advance still
    // requires the normal end-of-playback flow.
    let lastAutoSkipAt = 0;
    function checkAutoSkip() {
      if (!playerSettings.value?.playback?.auto_skip_intro) return;
      const action = activeSkipAction.value;
      if (!action) return;

      const now = Date.now();
      if (now - lastAutoSkipAt < 1500) return;   // debounce re-entry
      lastAutoSkipAt = now;

      seekTo(action.end);
    }

    function onTimeUpdate() {
      if (!videoRef.value) return;
      // currentTime mirrors raw PLAYER time; content conversions go through
      // playerToContent()/currentContentTime() only.
      currentTime.value = videoRef.value.currentTime || 0;
      isPlaying.value = !videoRef.value.paused;
      // Auto-clear false-positive stall errors if the stream is actively progressing
      if (playerError.value && (playerError.value.includes("stuck") || playerError.value.includes("Stuck"))) {
        playerError.value = null;
      }
      updateActiveCueText();
      checkAutoSkip();
    }

    let hasResumedProgress = false;
    // Set while the user is actively switching audio/seeks — the resume
    // prompt must never fire mid-session on programmatic reloads.
    let suppressResume = false;

    function applyResumedProgress() {
      if (hasResumedProgress || suppressResume || !videoRef.value || !media.value) return;
      if (Number(media.value.id) !== Number(route.params.id)) return;
      const progress = media.value.progress;
      if (progress && progress.position > 5 && !progress.completed) {
        const dur = media.value.duration || duration.value || 0;
        if (dur > 0 && progress.position >= dur * 0.9) return;
        resumeTime.value = progress.position;
        hasResumedProgress = true;

        // Resume behavior: ask (modal) / always (auto-resume) / never (start over)
        const behavior = playerSettings.value?.playback?.resume_behavior || "ask";
        if (behavior === "never") return;
        if (behavior === "always") {
          confirmResume();
          return;
        }

        showResumeModal.value = true;
        if (videoRef.value) {
          videoRef.value.pause();
        }
      }
    }

    function confirmResume() {
      showResumeModal.value = false;
      if (videoRef.value) {
        videoRef.value.currentTime = resumeTime.value;
        currentTime.value = resumeTime.value;
        videoRef.value.play().catch(() => {});
      }
      unlockAchievementSilently("resume_master");
    }

    function confirmStartOver() {
      showResumeModal.value = false;
      if (videoRef.value) {
        videoRef.value.currentTime = 0;
        currentTime.value = 0;
        videoRef.value.play().catch(() => {});
      }
      if (store.profile && media.value?.id) {
        API.post("/api/progress", {
          media_id: Number(media.value.id),
          position: 0,
          duration: Math.floor(duration.value || 0),
          completed: false,
        }).catch(() => {});
      }
    }

    function onLoadedMetadata() {
      if (!videoRef.value) return;
      if (streamState.transcode) {
        // Piped converted streams report bogus/fragment durations — never
        // adopt them. displayDuration falls back to the DB value instead.
      } else if (media.value && media.value.duration > 0) {
        duration.value = media.value.duration;
      } else if (videoRef.value.duration && isFinite(videoRef.value.duration) && videoRef.value.duration > 10) {
        duration.value = videoRef.value.duration;
      }
      if (playbackRate.value) {
        videoRef.value.playbackRate = playbackRate.value;
      }
      // Resolution-based achievements (direct play reports true height;
      // transcodes fall back to the quality option height if present)
      const vHeight = videoRef.value.videoHeight || 0;
      if (vHeight >= 2160) {
        unlockAchievementSilently("four_k_king");
        unlockAchievementSilently("hd_master");
      } else if (vHeight >= 1080) {
        unlockAchievementSilently("hd_master");
      }
      bindPipListeners();
      syncTextTracks();
      setTimeout(syncTextTracks, 200);
      applyResumedProgress();
    }

    const isEnded = ref(false);
    const nextEpCountdownSeconds = ref(5);
    const nextEpProgressPercent = ref(0);
    let autoAdvanceInterval = null;

    function startAutoAdvanceCountdown() {
      cancelAutoAdvance();
      isEnded.value = true;
      controlsHidden.value = false;
      nextEpCountdownSeconds.value = 5.0;
      nextEpProgressPercent.value = 0;

      const durationSec = 5.0;
      const startTime = Date.now();

      autoAdvanceInterval = setInterval(() => {
        const elapsed = (Date.now() - startTime) / 1000;
        const remaining = Math.max(0, durationSec - elapsed);
        nextEpCountdownSeconds.value = remaining;
        nextEpProgressPercent.value = Math.min(100, (elapsed / durationSec) * 100);

        if (remaining <= 0) {
          cancelAutoAdvance();
          playNext();
        }
      }, 50);
    }

    function cancelAutoAdvance() {
      if (autoAdvanceInterval) {
        clearInterval(autoAdvanceInterval);
        autoAdvanceInterval = null;
      }
      isEnded.value = false;
      nextEpProgressPercent.value = 0;
    }

    function handleNextEpClick() {
      cancelAutoAdvance();
      playNext();
      unlockAchievementSilently("next_ep_advance");
    }


    function onEnded() {
      isPlaying.value = false;
      const autoNext = playerSettings.value?.playback?.auto_play_next !== false;
      if (showNextEp.value && autoNext) {
        startAutoAdvanceCountdown();
      }
    }

    function onVideoError(e) {
      const v = videoRef.value;
      if (!v || !v.currentSrc || v.currentSrc.endsWith('/stream/') || v.currentSrc.endsWith('/null') || v.currentSrc.endsWith('/undefined')) {
        return;
      }
      if (v.error && v.error.code !== 0 && v.currentSrc && v.currentSrc.includes('/api/stream/')) {
        console.error("[HTML5 Player Error]", e, v.error);
        const p = (media.value?.file_path || "").toLowerCase();
        const isHeavy4k = p.includes("2160") || p.includes("4k") || p.includes("uhd");
        playerError.value = isHeavy4k
          ? "Playback failed — 4K/HEVC content needs hardware acceleration or a compatible browser (Edge recommended). Try another quality source or enable HW acceleration."
          : "Your browser cannot play this video codec natively (e.g. AC-3 audio or HEVC in MKV). Try another file format or Edge browser.";
      }
    }

    // Decoder-stall watchdog: 4K HEVC software decode can wedge the renderer
    // without firing an error event. If the video claims to be playing but
    // time stops advancing for >= 16s while not paused/seeking, surface a recovery notice.
    let lastStallCheckTime = Date.now();
    let lastStallVideoTime = -1;
    let stallDurationSec = 0;

    function checkPlaybackStall() {
      const v = videoRef.value;
      if (!v || v.paused || v.ended || v.seeking || !media.value) {
        stallDurationSec = 0;
        lastStallVideoTime = v ? v.currentTime : -1;
        lastStallCheckTime = Date.now();
        return;
      }

      const now = Date.now();
      const deltaReal = (now - lastStallCheckTime) / 1000;
      lastStallCheckTime = now;

      const curr = v.currentTime;
      // If playback position has advanced by at least 0.25s, video is actively progressing
      if (lastStallVideoTime >= 0 && Math.abs(curr - lastStallVideoTime) >= 0.25) {
        stallDurationSec = 0;
        lastStallVideoTime = curr;
        if (playerError.value && (playerError.value.includes("stuck") || playerError.value.includes("Stuck"))) {
          playerError.value = null; // recovered on its own
        }
        return;
      }

      lastStallVideoTime = curr;
      stallDurationSec += deltaReal;

      // Only flag as stalled if frozen for at least 16 continuous seconds
      if (stallDurationSec >= 16) {
        const p = (media.value?.file_path || "").toLowerCase();
        const heavy = p.includes("2160") || p.includes("4k") || p.includes("uhd") ||
                      (codecInfo.value?.tags || []).some((t) => t.includes("HEVC"));
        playerError.value = heavy
          ? "Decoder appears stuck — this 4K/HEVC stream exceeds what this device can handle. Enable hardware acceleration, use Edge, or pick a lower-quality source."
          : "Playback appears stuck. Press Play again or reload the stream.";
      }
    }

    function formatTime(seconds) {
      if (!seconds || isNaN(seconds)) return "00:00";
      const s = Math.floor(seconds);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const sec = s % 60;
      const mStr = m.toString().padStart(2, "0");
      const sStr = sec.toString().padStart(2, "0");
      return h > 0 ? `${h}:${mStr}:${sStr}` : `${mStr}:${sStr}`;
    }

    function handleKeyboard(e) {
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
      unlockAchievementSilently("keyboard_ninja");

      if (showResumeModal.value) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          confirmResume();
          return;
        } else if (e.key === "Escape") {
          e.preventDefault();
          confirmResume();
          return;
        }
      }

      const step = playerSettings.value?.playback?.seek_step || 10;

      switch (e.key) {
        case " ":
        case "k":
        case "K":
          e.preventDefault();
          togglePlay();
          break;
        case "ArrowRight":
        case "l":
        case "L":
          e.preventDefault();
          skip(step);
          break;
        case "ArrowLeft":
        case "j":
        case "J":
          e.preventDefault();
          skip(-step);
          break;
        case "ArrowUp":
          e.preventDefault();
          if (videoRef.value) {
            const newVol = Math.min(1, videoRef.value.volume + 0.1);
            videoRef.value.volume = newVol;
            volume.value = newVol;
          }
          break;
        case "ArrowDown":
          e.preventDefault();
          if (videoRef.value) {
            const newVol = Math.max(0, videoRef.value.volume - 0.1);
            videoRef.value.volume = newVol;
            volume.value = newVol;
          }
          break;
        case "f":
        case "F":
          e.preventDefault();
          toggleFullscreen();
          break;
        case "p":
        case "P":
          e.preventDefault();
          togglePip();
          break;
        case "m":
        case "M":
          e.preventDefault();
          toggleMute();
          break;
        case "n":
        case "N":
          e.preventDefault();
          if (hasNextEp.value) handleNextEpClick();
          break;
        case "[":
        case "BracketLeft":
          e.preventDefault();
          adjustSubOffset(e.shiftKey ? -1000 : -250);
          break;
        case "]":
        case "BracketRight":
          e.preventDefault();
          adjustSubOffset(e.shiftKey ? 1000 : 250);
          break;
      }
    }

    function toggleFullscreen() {
      if (!videoRef.value) return;
      const container = videoRef.value.closest(".custom-player-wrapper") || videoRef.value;
      if (!document.fullscreenElement) {
        if (container.requestFullscreen) container.requestFullscreen();
        isFullscreen.value = true;
      } else {
        if (document.exitFullscreen) document.exitFullscreen();
        isFullscreen.value = false;
      }
      API.post("/api/achievements/unlock", { achievement_id: "fullscreen_pro" }).then((res) => {
        if (res && res.unlocked) {
          addToast(`🏆 Achievement Unlocked: ${res.unlocked.icon} ${res.unlocked.title}!`, "success");
        }
      }).catch(() => {});
    }

    async function initPlayer() {
      const mediaId = route.params.id;
      playerError.value = null;
      showResumeModal.value = false;
      resumeTime.value = 0;
      hasResumedProgress = false;
      suppressResume = false;
      reloadToken++;                       // invalidate any in-flight swaps
      streamState.mediaId = Number(mediaId);
      streamState.audioTrack = null;
      streamState.transcode = false;
      streamState.streamStart = 0;
      // Fresh session — drop any previous remote-audio element state
      detachRemoteAudio();
      cancelAutoAdvance();

      if (videoRef.value) {
        videoRef.value.pause();
        try { videoRef.value.currentTime = 0; } catch (e) {}
      }
      currentTime.value = 0;
      duration.value = 0;
      media.value = null;

      selectedQualityMediaId.value = Number(mediaId);
      loadQualityOptions(mediaId);

      autoSkippedOp.value = false;
      autoSkippedEd.value = false;
      loadSkipTimes(mediaId);
      loadThumbSheet(mediaId);

      try {
        playerSettings.value = await API.get("/api/settings");
      } catch (e) {}

      if (playerSettings.value) {
        const pb = playerSettings.value.playback || {};
        const sub = playerSettings.value.subtitles || {};

        if (pb.default_volume !== undefined) {
          const rawVol = Number(pb.default_volume);
          const defaultVol = rawVol <= 1 ? rawVol : Math.min(1, Math.max(0, rawVol / 100));
          volume.value = defaultVol;
          if (videoRef.value) videoRef.value.volume = defaultVol;
        }

        if (pb.start_muted && videoRef.value) {
          videoRef.value.muted = true;
          isMuted.value = true;
          if (remoteAudioEl) remoteAudioEl.muted = true;
        }

        if (pb.default_speed !== undefined) {
          const rate = Number(pb.default_speed) || 1;
          playbackRate.value = rate;
          if (videoRef.value) videoRef.value.playbackRate = rate;
          if (isRemoteAudioActive() && remoteAudioEl) remoteAudioEl.playbackRate = rate;
        }

        if (sub.font_size) {
          const fontMap = { small: "0.85rem", normal: "1rem", large: "1.2rem", "extra-large": "1.4rem" };
          const fontVal = fontMap[sub.font_size] || sub.font_size;
          document.documentElement.style.setProperty("--sub-font-size", fontVal);
        }
      }

      try {
        media.value = await API.get(`/api/media/${mediaId}`);
        subtitles.value = media.value.subtitles || [];

        // Auto-download subtitles via OpenSubtitles when none exist and enabled
        if (!subtitles.value.length) {
          maybeAutoDownloadSubs();
        }

        applyResumedProgress();

        // Auto-select preferred subtitle language if auto_load enabled
        if (subtitles.value.length > 0) {
          const autoLoad = playerSettings.value?.subtitles?.auto_load !== false;
          if (autoLoad) {
            let prefLang = (playerSettings.value?.subtitles?.preferred_language || "en").toLowerCase();
            if (prefLang === "auto") prefLang = "en";
            const prefIdx = subtitles.value.findIndex((s) => (s.language || "").toLowerCase().startsWith(prefLang) || (s.label || "").toLowerCase().includes(prefLang));
            const defaultIdx = prefIdx >= 0 ? prefIdx : 0;
            selectSub(defaultIdx);
          }
        }
      } catch (e) {
        addToast("Failed to load media", "error");
        return;
      }

      try {
        audioTracks.value = await API.get(`/api/audio-tracks/${mediaId}`);
      } catch (e) {
        audioTracks.value = [];
      }

      // Browsers direct-play the container's DEFAULT-flagged track — align the
      // UI selection with it so "Track 1" isn't silently playing another track.
      const defTrack = audioTracks.value.find((t) => t.default);
      defaultAudioIndex.value = defTrack ? defTrack.index : 0;
      streamState.audioTrack = defaultAudioIndex.value;

      if (media.value.type !== "movie" && media.value.tmdb_id) {
        try {
          const show = await API.get(`/api/show/${media.value.tmdb_id}?type=${media.value.type}`);
          const allEps = Object.values(show.seasons || {})
            .flat()
            .sort((a, b) => {
              if (a.season !== b.season) return (a.season || 0) - (b.season || 0);
              return (a.episode || 0) - (b.episode || 0);
            });
          const idx = allEps.findIndex((e) => e.id === Number(mediaId));
          if (idx >= 0) {
            let foundNext = null;
            for (let i = idx + 1; i < allEps.length; i++) {
              const candidate = allEps[i];
              if (candidate && candidate.id && candidate.is_local !== false && candidate.is_mounted !== false) {
                foundNext = candidate;
                break;
              }
            }
            nextEp.value = foundNext;
          } else {
            nextEp.value = null;
          }
        } catch (e) {
          nextEp.value = null;
        }
      } else {
        nextEp.value = null;
      }

      if (store.profile) {
        progressTimer = setInterval(() => {
          if (!videoRef.value || videoRef.value.paused || !media.value?.id) return;
          saveProgressNow();
        }, 5000);
        // Belt-and-braces: flush progress when the tab is hidden or closing
        window.addEventListener("pagehide", flushProgressOnHide);
        document.addEventListener("visibilitychange", handleVisibilityChange);
      }

      // Decoder-stall watchdog runs independently of media events —
      // a wedged 4K HEVC decoder stops firing timeupdate entirely.
      stallTimer = setInterval(() => checkPlaybackStall(), 2000);

      // Kick off initial playback through the controller (it owns the src)
      swapStream(0);
      window.addEventListener("keydown", handleKeyboard);
      showControls();
    }

    async function goBack() {
      await saveProgressNow();
      if (media.value) {
        if (media.value.type === "movie" && media.value.id) {
          router.push(`/title/movie/${media.value.id}`);
          return;
        } else if (media.value.tmdb_id) {
          router.push(`/title/${media.value.type || "series"}/${media.value.tmdb_id}`);
          return;
        } else if (media.value.id) {
          router.push(`/title/${media.value.type || "movie"}/${media.value.id}`);
          return;
        }
      }
      router.back();
    }

    async function goHome() {
      await saveProgressNow();
      router.push("/");
    }

    async function playNext() {
      await saveProgressNow();
      if (videoRef.value) {
        videoRef.value.pause();
        try { videoRef.value.currentTime = 0; } catch (e) {}
      }
      currentTime.value = 0;
      showResumeModal.value = false;
      resumeTime.value = 0;
      hasResumedProgress = false;
      if (nextEp.value && nextEp.value.id && nextEp.value.is_local !== false && nextEp.value.is_mounted !== false) {
        router.push(`/watch/${nextEp.value.id}`);
      }
    }

    onMounted(initPlayer);

    onUnmounted(() => {
      cancelAutoAdvance();
      saveProgressNow();
      detachRemoteAudio();
      clearInterval(progressTimer);
      clearInterval(stallTimer);
      clearTimeout(hideTimer);
      if (playerAchTimer) clearTimeout(playerAchTimer);
      window.removeEventListener("pagehide", flushProgressOnHide);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("keydown", handleKeyboard);
    });

    watch(
      () => route.params.id,
      () => {
        cancelAutoAdvance();
        clearInterval(progressTimer);
        if (videoRef.value) {
          videoRef.value.pause();
          try { videoRef.value.currentTime = 0; } catch (e) {}
        }
        currentTime.value = 0;
        duration.value = 0;
        media.value = null;
        showResumeModal.value = false;
        resumeTime.value = 0;
        hasResumedProgress = false;
        initPlayer();
      },
    );

    return {
      store,
      videoRef,
      seekbarRef,
      media,
      nextEp,
      nextEpHover,
      showNextPreview,
      hideNextPreview,
      formatDuration,
      hasNextEp,
      showNextEp,
      showAutoAdvanceOverlay,
      subtitles,
      playerSettings,
      isPlaying,
      isMuted,
      volume,
      currentTime,
      duration,
      isBuffering,
      isPipSupported,
      isPipActive,
      togglePip,
      toggleFullscreen,
      isFullscreen,
      controlsHidden,
      playerError,
      playbackRate,
      selectedSub,
      showSpeedMenu,
      showSubMenu,
      showOnlineSubModal,
      onlineSubResults,
      loadingOnlineSubs,
      downloadingSubId,
      openOnlineSubModal,
      downloadAndApplyOnlineSub,
      audioTracks,
      streamState,
      defaultAudioIndex,
      canSwitchQuality,
      currentContentTime,
      playerAch,
      playbackWarning,
      warningDismissed,
      dismissPlaybackWarning,
      compatInfo,
      enableCompatPlayback,
      disableCompatPlayback,
      showAudioMenu,
      selectAudioTrack,
      qualityOptions,
      selectedQualityMediaId,
      showQualityMenu,
      selectQuality,
      skipTimes,
      downloadingSubs,
      downloadSubtitles,
      thumbSheet,
      thumbCellStyle,
      activeSkipButton,
      getSegmentStyle,
      performSkip,
      showHoverTooltip,
      hoverTooltipPos,
      hoverTooltipTime,
      progressPercent,
      endClockTime,
      displayDuration,
      displayTime,
      volumeOSD,
      volumeOSDPct,
      seekOSD,
      showControls,
      showSkipModal,
      activeSkipAction,
      executeSkipAction,
      handleSkipSaved,
      formatSecToTime,
      togglePlay,
      handleContainerClick,
      skip,
      toggleMute,
      onVolumeInput,
      seekToClick,
      hoverSeekbar,
      selectSpeed,
      selectSub,
      onSubtitleTrackError,
      syncTextTracks,
      onVideoPlaying,
      onVideoPause,
      handleCustomSubFile,
      toggleFullscreen,
      onTimeUpdate,
      onLoadedMetadata,
      onEnded,
      onVideoError,
      subStyle,
      updateSubStyle,
      subOffsetMs,
      adjustSubOffset,
      resetSubOffset,
      activeCueText,
      updateActiveCueText,
      customCueStyle,
      formatTime,
      imgUrl,
      goBack,
      goHome,
      playNext,
      showResumeModal,
      showShortcuts,
      resumeTime,
      confirmResume,
      confirmStartOver,
      isEnded,
      nextEpCountdownSeconds,
      nextEpProgressPercent,
      handleNextEpClick,
      cancelAutoAdvance,
    };
  },
};

// ─── Browse Page ──────────────────────────────────────────────

const BrowsePage = {
  components: { MediaCard },
  template: `
    <div class="browse-page">
      <div class="browse-header">
        <h1 class="browse-title">{{ pageTitle }}</h1>
        <div class="browse-filters">
          <button
            v-for="t in types"
            :key="t.value"
            class="filter-btn"
            :class="{ active: activeType === t.value }"
            @click="setType(t.value)"
            :id="'filter-' + t.value"
          >{{ t.label }}</button>

          <select
            v-model="selectedGenre"
            @change="onGenreChange"
            class="form-input"
            style="width:160px;margin-left:8px;font-size:0.85rem;padding:6px 10px"
            id="filter-genre"
          >
            <option value="">All Genres</option>
            <option v-for="g in displayGenres" :key="g" :value="g">{{ g }}</option>
          </select>

          <button
            v-if="!store.profile?.is_kids"
            class="filter-btn"
            :class="{ active: hideUnmounted }"
            @click="toggleHideUnmounted"
            id="filter-unmounted-toggle"
            style="margin-left:8px"
            title="Toggle hiding media from unmounted drives"
          >
            {{ hideUnmounted ? '👁️ Unmounted Hidden' : '👁️ Show Unmounted' }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="media-grid">
        <div v-for="i in 12" :key="i" class="skeleton" style="aspect-ratio:2/3;border-radius:10px"></div>
      </div>

      <div v-else-if="filteredItems.length === 0" class="empty-state">
        <div class="empty-icon">🎬</div>
        <div class="empty-title">No titles found</div>
        <div class="empty-subtitle">Add media to your folders or reconnect unmounted storage drives.</div>
      </div>

      <div v-else class="media-grid">
        <media-card
          v-for="item in paginatedItems"
          :key="item.id || item.tmdb_id"
          :item="item"
          @click="handleClick"
        />
      </div>

      <!-- Classic Page Number Bar Pagination -->
      <div v-if="filteredItems.length > 0" class="pagination-bar">
        <button class="pagination-btn" :disabled="currentPage === 1" @click="setPage(1)" title="First Page">
          « First
        </button>
        <button class="pagination-btn" :disabled="currentPage === 1" @click="setPage(currentPage - 1)" title="Previous Page">
          ‹ Prev
        </button>

        <div class="pagination-numbers" v-if="totalPages > 1">
          <button
            v-for="p in visiblePageNumbers"
            :key="p"
            class="pagination-num-btn"
            :class="{ active: currentPage === p }"
            @click="setPage(p)"
          >
            {{ p }}
          </button>
        </div>

        <span class="pagination-info">
          Page <strong>{{ currentPage }}</strong> of <strong>{{ totalPages }}</strong>
          <span style="font-size:0.75rem;color:var(--text-muted);margin-left:6px">({{ filteredItems.length }} total titles)</span>
        </span>

        <button class="pagination-btn" :disabled="currentPage === totalPages" @click="setPage(currentPage + 1)" title="Next Page">
          Next ›
        </button>
        <button class="pagination-btn" :disabled="currentPage === totalPages" @click="setPage(totalPages)" title="Last Page">
          Last »
        </button>

        <!-- Items Per Page Selector -->
        <div class="pagination-size-selector">
          <span style="font-size:0.8rem;color:var(--text-muted)">Per page:</span>
          <select v-model.number="pageSize" class="form-input pagination-select" @change="currentPage = 1" id="browse-page-size-select">
            <option :value="12">12 / page</option>
            <option :value="24">24 / page</option>
            <option :value="48">48 / page</option>
            <option :value="96">96 / page</option>
            <option :value="999999">Show All</option>
          </select>
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const items = ref([]);
    const loading = ref(true);
    const activeType = ref(route.query.type || "");

    const pageSize = ref(24);
    const currentPage = ref(1);

    const types = [
      { label: "All", value: "" },
      { label: "🎬 Movies", value: "movie" },
      { label: "📺 Series", value: "series" },
      { label: "🎌 Anime", value: "anime" },
    ];

    const pageTitle = computed(() => {
      if (route.query.genre) return route.query.genre;
      if (activeType.value === "movie") return "Movies";
      if (activeType.value === "series") return "Series";
      if (activeType.value === "anime") return "Anime";
      return "Browse All";
    });

    async function load() {
      loading.value = true;
      try {
        const genre = route.query.genre;
        const type = activeType.value;
        let data;
        if (genre) {
          const q = new URLSearchParams();
          q.set("q", genre);
          if (type) q.set("type", type);
          q.set("genre", genre);
          data = await API.get(`/api/search?${q}`);
        } else {
          const url = type ? `/api/library?type=${type}` : "/api/library";
          data = await API.get(url);
        }
        items.value = kidsFilter(data);
      } catch (e) {
        addToast("Failed to load library", "error");
      } finally {
        loading.value = false;
      }
    }

    function setType(t) {
      activeType.value = t;
      currentPage.value = 1;
      if (t) unlockAchievement("filter_pro");
      if (t) {
        router.push({ path: "/browse", query: { type: t } });
      } else {
        router.push({ path: "/browse" });
      }
    }

    // ─── Genre filter (client-side over the loaded library) ─────
    const genres = ref([]);
    const selectedGenre = ref("");

    function onGenreChange() {
      currentPage.value = 1;
      if (selectedGenre.value) unlockAchievement("filter_pro");
    }

    function handleClick(item) {
      if (item.type === "movie") {
        router.push(`/title/movie/${item.id}`);
      } else {
        router.push(`/title/${item.type}/${item.tmdb_id}`);
      }
    }

    const displayGenres = computed(() => {
      const all = genres.value || [];
      if (!store.profile?.is_kids) return all;
      return all.filter(g => {
        const gl = g.toLowerCase();
        return KIDS_SAFE_GENRES.some(k => gl.includes(k)) && !KIDS_BLOCKED_GENRES.some(b => gl === b && b !== "adventure");
      });
    });

    onMounted(() => {
      load();
      API.get("/api/genres").then((g) => { genres.value = g || []; }).catch(() => {});
    });
    watch(
      () => route.query.type,
      (newType) => {
        activeType.value = newType || "";
        currentPage.value = 1;
        load();
      },
    );
    watch(() => route.query.genre, () => {
      currentPage.value = 1;
      load();
    });
    watch(
      () => store.scanRunning,
      (running, prev) => {
        if (!running && prev === true) {
          load();
        }
      },
    );

    const hideUnmounted = ref(false);

    function toggleHideUnmounted() {
      hideUnmounted.value = !hideUnmounted.value;
      currentPage.value = 1;
    }

    const filteredItems = computed(() => {
      let list = items.value || [];
      if (hideUnmounted.value) {
        list = list.filter((item) => item.is_mounted !== false);
      }
      if (selectedGenre.value) {
        const g = selectedGenre.value.toLowerCase();
        list = list.filter(
          (item) => (item.genres || "").toLowerCase().split(",").map((x) => x.trim()).includes(g)
        );
      }
      return list;
    });

    const totalPages = computed(() => {
      return Math.ceil(filteredItems.value.length / pageSize.value) || 1;
    });

    const paginatedItems = computed(() => {
      const start = (currentPage.value - 1) * pageSize.value;
      return filteredItems.value.slice(start, start + pageSize.value);
    });

    const visiblePageNumbers = computed(() => {
      const total = totalPages.value;
      const current = currentPage.value;
      const pages = [];
      const delta = 2;
      const start = Math.max(1, current - delta);
      const end = Math.min(total, current + delta);
      for (let i = start; i <= end; i++) {
        pages.push(i);
      }
      return pages;
    });

    function setPage(page) {
      if (page < 1 || page > totalPages.value) return;
      currentPage.value = page;
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    return {
      store,
      items,
      filteredItems,
      paginatedItems,
      loading,
      activeType,
      genres,
      displayGenres,
      selectedGenre,
      onGenreChange,
      types,
      pageTitle,
      hideUnmounted,
      toggleHideUnmounted,
      setType,
      handleClick,
      currentPage,
      pageSize,
      totalPages,
      visiblePageNumbers,
      setPage,
    };
  },
};

// ─── Collections Page ─────────────────────────────────────────

const CollectionsPage = {
  template: `
    <div class="collections-page">
      <div class="collections-header-bar">
        <div>
          <h1 class="page-title">Collections & Universes</h1>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap">
          <div class="collections-filter-tabs" v-if="collections.length > 0">
            <button
              class="collections-tab-btn"
              :class="{ active: activeTab === 'all' }"
              @click="activeTab = 'all'"
            >
              All <span class="collections-tab-count">{{ collections.length }}</span>
            </button>
            <button
              v-if="universesCount > 0"
              class="collections-tab-btn"
              :class="{ active: activeTab === 'universes' }"
              @click="activeTab = 'universes'"
            >
              <i class="ph ph-sparkle"></i> Universes <span class="collections-tab-count">{{ universesCount }}</span>
            </button>
            <button
              v-if="smartCount > 0"
              class="collections-tab-btn"
              :class="{ active: activeTab === 'smart' }"
              @click="activeTab = 'smart'"
            >
              <i class="ph ph-lightning"></i> Smart Lists <span class="collections-tab-count">{{ smartCount }}</span>
            </button>
            <button
              v-if="customCount > 0"
              class="collections-tab-btn"
              :class="{ active: activeTab === 'custom' }"
              @click="activeTab = 'custom'"
            >
              <i class="ph ph-folder"></i> Custom <span class="collections-tab-count">{{ customCount }}</span>
            </button>
          </div>
          <button v-if="!store.profile?.is_kids" class="btn btn-primary" @click="showCreate = true" id="create-collection-btn">
            <i class="ph ph-plus"></i> New Collection
          </button>
        </div>
      </div>

      <div v-if="!store.profile" class="empty-state">
        <div class="empty-icon">👤</div>
        <div class="empty-title">Select a profile first</div>
      </div>

      <div v-else-if="collections.length === 0" class="empty-state">
        <div class="empty-icon">📚</div>
        <div class="empty-title">No collections yet</div>
        <div class="empty-subtitle">Create a collection to group your favourite titles or add titles to auto-generate cinematic universes.</div>
        <button v-if="!store.profile?.is_kids" class="btn btn-primary" style="margin-top:1rem" @click="showCreate = true" id="create-first-col-btn">
          <i class="ph ph-plus"></i> Create First Collection
        </button>
      </div>

      <div v-else-if="filteredCollections.length === 0" class="empty-state">
        <div class="empty-icon">🔍</div>
        <div class="empty-title">No matching collections</div>
        <div class="empty-subtitle">Try selecting a different filter tab.</div>
      </div>

      <div v-else class="collections-grid">
        <div
          v-for="col in filteredCollections"
          :key="col.id"
          class="collection-card"
          @click="router.push('/collection/' + col.id)"
          :id="'collection-' + col.id"
        >
          <div class="collection-cover" :class="'cover-count-' + Math.min(col.items ? col.items.length : 0, 4)">
            <template v-if="col.items && col.items.length">
              <img
                v-for="item in col.items.slice(0, 4)"
                :key="item.id"
                :src="imgUrl(col.items.length === 1 && item.backdrop_path ? item.backdrop_path : (item.poster_path || item.backdrop_path))"
                class="collection-cover-img"
                :alt="item.title"
                loading="lazy"
              >
            </template>
            <div v-else class="collection-cover-empty">
              <i class="ph ph-stack"></i>
              <span>Empty Collection</span>
            </div>
          </div>
          <div class="collection-info">
            <div class="collection-name">
              {{ col.name }}
              <span v-if="col.universe" class="universe-card-badge" style="margin-left:6px">
                <i class="ph ph-sparkle"></i> Universe
              </span>
              <span v-else-if="col.smart" class="skip-src-badge" style="margin-left:6px">✨ Smart</span>
            </div>
            <div class="collection-count">{{ col.items ? col.items.length : 0 }} title{{ !col.items || col.items.length !== 1 ? 's' : '' }}</div>
          </div>
        </div>
      </div>

      <!-- Create Modal -->
      <div class="modal-backdrop" v-if="showCreate" @click.self="showCreate = false">
        <div class="modal">
          <h3>New Collection</h3>
          <div class="form-group">
            <label class="form-label">Name</label>
            <input id="new-collection-name" class="form-input" v-model="newName" placeholder="e.g. Marvel Order" @keyup.enter="createCollection">
          </div>
          <div class="form-group">
            <label class="form-label">Description (optional)</label>
            <input id="new-collection-desc" class="form-input" v-model="newDesc" placeholder="A brief description">
          </div>
          <div style="display:flex;gap:0.75rem;margin-top:1rem">
            <button class="btn btn-primary btn-full" @click="createCollection" id="save-collection-btn">Create</button>
            <button class="btn btn-ghost btn-full" @click="showCreate = false">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const collections = ref([]);
    const activeTab = ref("all");
    const showCreate = ref(false);
    const newName = ref("");
    const newDesc = ref("");

    const universesCount = computed(() => collections.value.filter((c) => c.universe).length);
    const smartCount = computed(() => collections.value.filter((c) => c.smart && !c.universe).length);
    const customCount = computed(() => collections.value.filter((c) => !c.smart).length);

    const filteredCollections = computed(() => {
      if (activeTab.value === "universes") return collections.value.filter((c) => c.universe);
      if (activeTab.value === "smart") return collections.value.filter((c) => c.smart && !c.universe);
      if (activeTab.value === "custom") return collections.value.filter((c) => !c.smart);
      return collections.value;
    });

    async function load() {
      if (!store.profile) return;
      try {
        collections.value = await API.get("/api/collections");
      } catch (e) {
        addToast("Failed to load collections", "error");
      }
    }

    async function createCollection() {
      if (!newName.value.trim()) return;
      try {
        const col = await API.post("/api/collections", { name: newName.value.trim(), description: newDesc.value });
        col.items = [];
        collections.value.unshift(col);
        newName.value = "";
        newDesc.value = "";
        showCreate.value = false;
        addToast("Collection created", "success");
      } catch (e) {
        addToast("Failed to create collection", "error");
      }
    }

    onMounted(load);
    watch(() => store.profile, load);

    return {
      store,
      collections,
      activeTab,
      universesCount,
      smartCount,
      customCount,
      filteredCollections,
      showCreate,
      newName,
      newDesc,
      router,
      imgUrl,
      createCollection
    };
  },
};

// ─── Collection Detail Page ───────────────────────────────────

const CollectionDetailPage = {
  components: { MediaCard },
  template: `
    <div class="browse-page">
      <div v-if="collection" class="collection-hero">
        <img
          v-if="heroBackdrop"
          :src="imgUrl(heroBackdrop)"
          class="collection-hero-backdrop"
          :alt="collection.name"
        />
        <div class="collection-hero-overlay"></div>
        <div class="collection-hero-content">
          <div class="collection-hero-main">
            <div class="collection-hero-badges">
              <span v-if="collection.universe" class="collection-hero-badge badge-universe">
                <i class="ph ph-sparkle"></i> Cinematic Universe
              </span>
              <span v-else-if="collection.smart" class="collection-hero-badge badge-smart">
                <i class="ph ph-lightning"></i> Smart Collection
              </span>
              <span v-else class="collection-hero-badge">
                <i class="ph ph-stack"></i> Custom Collection
              </span>
              <span class="collection-hero-badge">
                {{ displayItems ? displayItems.length : 0 }} title{{ !displayItems || displayItems.length !== 1 ? 's' : '' }}
              </span>
            </div>
            <h1 class="collection-hero-title">{{ collection.name }}</h1>
            <p v-if="collection.description" class="collection-hero-desc">{{ collection.description }}</p>
          </div>
          <div class="collection-hero-actions">
            <!-- Timeline toggle for universes with chronological mapping -->
            <div v-if="collection.has_timeline" class="timeline-toggle-group">
              <button
                class="timeline-toggle-btn"
                :class="{ active: sortMode === 'release' }"
                @click="sortMode = 'release'"
                title="Sort by Release Date"
              >
                <i class="ph ph-calendar"></i> Release
              </button>
              <button
                class="timeline-toggle-btn"
                :class="{ active: sortMode === 'timeline' }"
                @click="sortMode = 'timeline'"
                title="Sort by In-Universe Chronological Timeline"
              >
                <i class="ph ph-hourglass-high"></i> Timeline
              </button>
            </div>

            <button
              v-if="displayItems && displayItems.length > 0"
              class="btn btn-primary"
              @click="playFirst"
              id="collection-play-first-btn"
            >
              <i class="ph ph-play-fill"></i> Play First
            </button>
            <button
              v-if="displayItems && displayItems.length > 1"
              class="btn btn-secondary"
              @click="playRandom"
              id="collection-shuffle-btn"
              title="Shuffle Play"
            >
              <i class="ph ph-shuffle"></i> Shuffle
            </button>
            <button
              v-if="!collection.smart && !store.profile?.is_kids"
              class="btn btn-ghost"
              @click="deleteCollection"
              style="color:var(--accent)"
              id="delete-collection-btn"
            >
              <i class="ph ph-trash"></i> Delete
            </button>
          </div>
        </div>
      </div>

      <div v-if="!collection || !displayItems || displayItems.length === 0" class="empty-state">
        <div class="empty-icon"><i class="ph ph-stack" style="font-size:3rem;color:var(--accent)"></i></div>
        <div class="empty-title">Collection is empty</div>
        <div class="empty-subtitle">Add titles from their detail pages to populate this collection.</div>
      </div>

      <div v-else class="media-grid">
        <media-card
          v-for="item in displayItems"
          :key="item.id"
          :item="item"
          @click="handleClick"
        />
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const collection = ref(null);
    const sortMode = ref("release");

    const displayItems = computed(() => {
      if (!collection.value) return [];
      if (sortMode.value === "timeline" && collection.value.timeline_items && collection.value.timeline_items.length) {
        return collection.value.timeline_items;
      }
      return collection.value.items || [];
    });

    const heroBackdrop = computed(() => {
      if (!displayItems.value?.length) return null;
      const firstWithBackdrop = displayItems.value.find((i) => i.backdrop_path);
      return firstWithBackdrop ? firstWithBackdrop.backdrop_path : (displayItems.value[0]?.poster_path || null);
    });

    async function load() {
      try {
        const cols = await API.get("/api/collections");
        collection.value = cols.find((c) => String(c.id) === String(route.params.id)) || null;
      } catch (e) {
        addToast("Failed to load collection", "error");
      }
    }

    async function deleteCollection() {
      const ok = await customConfirm({
        title: "Delete Collection",
        message: `Are you sure you want to delete collection "${collection.value?.name}"?`,
        icon: "ph ph-trash",
        danger: true,
        okText: "Delete Collection"
      });
      if (!ok) return;
      try {
        await API.del(`/api/collections/${route.params.id}`);
        addToast("Collection deleted", "success");
        router.push("/collections");
      } catch (e) {
        addToast("Failed to delete", "error");
      }
    }

    function handleClick(item) {
      if (item.type === "movie") router.push(`/title/movie/${item.id}`);
      else router.push(`/title/${item.type}/${item.tmdb_id}`);
    }

    function playFirst() {
      if (displayItems.value?.length) {
        handleClick(displayItems.value[0]);
      }
    }

    function playRandom() {
      if (displayItems.value?.length) {
        const idx = Math.floor(Math.random() * displayItems.value.length);
        handleClick(displayItems.value[idx]);
      }
    }

    onMounted(load);

    return {
      store,
      collection,
      sortMode,
      displayItems,
      heroBackdrop,
      imgUrl,
      handleClick,
      playFirst,
      playRandom,
      deleteCollection
    };
  },
};

// ─── Favorites Page ───────────────────────────────────────────

const FavoritesPage = {
  components: { MediaCard },
  template: `
    <div class="favorites-page">
      <div class="page-header">
        <h1 class="page-title">Watchlist</h1>
      </div>

      <div v-if="!store.profile" class="empty-state">
        <div class="empty-icon">👤</div>
        <div class="empty-title">Select a profile first</div>
      </div>

      <div v-else-if="items.length === 0" class="empty-state">
        <div class="empty-icon">❤️</div>
        <div class="empty-title">Nothing saved yet</div>
        <div class="empty-subtitle">Heart any title to add it to your watchlist.</div>
      </div>

      <div v-else class="media-grid">
        <media-card
          v-for="item in items"
          :key="item.id"
          :item="item"
          @click="handleClick"
        />
      </div>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const items = ref([]);

    async function load() {
      if (!store.profile) return;
      try {
        items.value = kidsFilter(await API.get("/api/favorites"));
      } catch (e) {
        addToast("Failed to load watchlist", "error");
      }
    }

    function handleClick(item) {
      if (item.type === "movie") router.push(`/title/movie/${item.id}`);
      else router.push(`/title/${item.type}/${item.tmdb_id}`);
    }

    onMounted(load);
    watch(() => store.profile, load);

    return { store, items, handleClick };
  },
};

// ─── Profile Selector (Netflix Style) ─────────────────────────

const ProfilesPage = {
  template: `
    <div class="netflix-profile-page">
      <!-- Netflix Brand Logo Top Left -->
      <div class="netflix-profile-brand" @click="viewMode = 'select'">
        <img src="/static/img/favicon.png" alt="CapsStream" class="netflix-profile-brand-logo">
        <span class="netflix-profile-brand-text">CapsStream</span>
      </div>

      <!-- 1. Who's Watching / Manage Profiles View -->
      <div v-if="viewMode === 'select' || viewMode === 'manage'" class="netflix-profile-container">
        <div class="netflix-profile-header">
          <h1 class="netflix-profile-title">
            {{ viewMode === 'manage' ? 'Manage Profiles:' : "Who's watching?" }}
          </h1>
        </div>

        <div class="netflix-profiles-list">
          <!-- Profile Cards -->
          <div
            v-for="profile in profiles"
            :key="profile.id"
            class="netflix-profile-card"
            @click="onProfileClick(profile)"
            :id="'profile-' + profile.id"
          >
            <div
              class="netflix-avatar-wrap"
              :style="{
                background: profile.color ? profile.color + '44' : 'rgba(255,255,255,0.08)',
                border: profile.color ? '3px solid ' + profile.color + '88' : '3px solid transparent'
              }"
            >
              <span>{{ profile.avatar || '🎬' }}</span>

              <!-- Edit Pencil Overlay in Manage Mode -->
              <div v-if="viewMode === 'manage'" class="netflix-avatar-edit-overlay">
                <div class="netflix-avatar-edit-badge">
                  <i class="ph-bold ph-pencil-simple"></i>
                </div>
              </div>
            </div>

            <div class="netflix-profile-label">
              {{ profile.name }}
            </div>
            <div v-if="profile.is_kids" class="kids-profile-badge">🧒 Kids</div>
          </div>

          <!-- Add Profile Card (visible if under 5 profiles) -->
          <div
            v-if="profiles.length < 5"
            class="netflix-profile-card netflix-add-card"
            @click="openCreateView"
            id="add-profile-btn"
          >
            <div class="netflix-avatar-wrap">
              <i class="ph ph-plus-circle"></i>
            </div>
            <div class="netflix-profile-label">Add Profile</div>
          </div>
        </div>

        <!-- Manage Profiles / Done Button -->
        <div style="text-align:center">
          <button
            v-if="viewMode === 'select'"
            class="netflix-action-btn"
            @click="viewMode = 'manage'"
            id="manage-profiles-btn"
          >
            Manage Profiles
          </button>
          <button
            v-else
            class="netflix-action-btn active-done"
            @click="viewMode = 'select'"
            id="done-profiles-btn"
          >
            Done
          </button>
        </div>
      </div>

      <!-- 2. Dedicated Netflix Edit Profile View -->
      <div v-else-if="viewMode === 'edit' && editTarget" class="netflix-form-container">
        <h1 class="netflix-form-header">Edit Profile</h1>
        <div class="netflix-form-divider"></div>

        <div class="netflix-form-body">
          <!-- Left: Avatar Preview & Picker -->
          <div class="netflix-form-left">
            <div
              class="netflix-form-avatar-preview"
              :style="{
                background: editProfile.color ? editProfile.color + '44' : 'rgba(255,255,255,0.08)',
                border: '3px solid ' + editProfile.color
              }"
            >
              <span>{{ editProfile.avatar }}</span>
            </div>

            <!-- Avatar Choices Grid -->
            <div style="margin-top:14px;max-width:140px">
              <div style="font-size:0.75rem;color:#808080;margin-bottom:6px;font-weight:600">ICON</div>
              <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px">
                <div
                  v-for="a in avatars"
                  :key="a"
                  @click="editProfile.avatar = a"
                  style="cursor:pointer;font-size:1.3rem;padding:4px;border-radius:4px;text-align:center;transition:background 0.2s"
                  :style="editProfile.avatar === a ? { background: 'rgba(255,255,255,0.2)' } : {}"
                >
                  {{ a }}
                </div>
              </div>
            </div>

            <!-- Color Palette -->
            <div style="margin-top:14px;max-width:140px">
              <div style="font-size:0.75rem;color:#808080;margin-bottom:6px;font-weight:600">COLOR</div>
              <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px">
                <div
                  v-for="c in colors"
                  :key="c"
                  @click="editProfile.color = c"
                  style="width:22px;height:22px;border-radius:50%;cursor:pointer;box-sizing:border-box"
                  :style="{
                    background: c,
                    border: editProfile.color === c ? '2px solid #ffffff' : 'none',
                    transform: editProfile.color === c ? 'scale(1.15)' : 'scale(1)'
                  }"
                ></div>
              </div>
            </div>
          </div>

          <!-- Right: Profile Name, Kids Settings, PIN -->
          <div class="netflix-form-right">
            <div>
              <input
                id="edit-profile-name"
                class="netflix-input"
                v-model="editProfile.name"
                placeholder="Name"
                autofocus
              >
            </div>

            <!-- Kids Setting -->
            <div style="border-top:1px solid #282828;padding-top:18px">
              <label class="netflix-checkbox-label">
                <input type="checkbox" v-model="editProfile.is_kids" id="edit-kids-mode-switch">
                <div>
                  <div class="netflix-checkbox-title">Kid?</div>
                  <div class="netflix-checkbox-desc">Only see TV shows and movies rated for kids. Locks app Settings.</div>
                </div>
              </label>
            </div>

            <!-- Kids Screen Time Controls -->
            <div v-if="editProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <div style="font-size:0.95rem;color:#ffffff;font-weight:600;margin-bottom:4px">⏰ Daily Watch Limit</div>
              <div style="font-size:0.85rem;color:#808080;margin-bottom:8px">Automatically lock Kids Mode after watching this amount today.</div>
              <select v-model.number="editProfile.daily_limit_minutes" class="form-input" style="max-width:240px;background:#1a1a1a;color:#fff;border:1px solid #333;padding:8px;border-radius:8px">
                <option :value="0">No Limit (Unlimited)</option>
                <option :value="30">30 Minutes / day</option>
                <option :value="45">45 Minutes / day</option>
                <option :value="60">1 Hour / day</option>
                <option :value="90">1.5 Hours / day</option>
                <option :value="120">2 Hours / day</option>
                <option :value="180">3 Hours / day</option>
              </select>
            </div>

            <div v-if="editProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <div style="font-size:0.95rem;color:#ffffff;font-weight:600;margin-bottom:4px">🌙 Bedtime Curfew</div>
              <div style="font-size:0.85rem;color:#808080;margin-bottom:8px">Locks Kids Mode at this time in the evening.</div>
              <select v-model="editProfile.bedtime_curfew" class="form-input" style="max-width:240px;background:#1a1a1a;color:#fff;border:1px solid #333;padding:8px;border-radius:8px">
                <option value="">Off (No Bedtime Curfew)</option>
                <option value="19:00">7:00 PM</option>
                <option value="19:30">7:30 PM</option>
                <option value="20:00">8:00 PM</option>
                <option value="20:30">8:30 PM</option>
                <option value="21:00">9:00 PM</option>
                <option value="21:30">9:30 PM</option>
                <option value="22:00">10:00 PM</option>
              </select>
            </div>

            <!-- PIN Protection -->
            <div v-if="!editProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <label class="netflix-checkbox-label" style="margin-bottom:8px">
                <input type="checkbox" v-model="editProfile.update_pin">
                <div>
                  <div class="netflix-checkbox-title">Lock Profile with PIN</div>
                  <div class="netflix-checkbox-desc">Require a 4-digit PIN to access this profile.</div>
                </div>
              </label>

              <div v-if="editProfile.update_pin" style="margin-top:10px">
                <input
                  id="edit-profile-pin"
                  class="netflix-input"
                  v-model="editProfile.pin"
                  placeholder="Enter 4-digit PIN (leave empty to remove PIN)"
                  maxlength="4"
                  inputmode="numeric"
                  style="max-width:240px"
                >
              </div>
            </div>
          </div>
        </div>

        <div class="netflix-form-divider"></div>

        <!-- Action Buttons -->
        <div class="netflix-form-buttons">
          <button class="netflix-btn-white" @click="saveEditProfile" id="save-edit-profile-btn">
            Save
          </button>
          <button class="netflix-btn-ghost" @click="viewMode = 'manage'">
            Cancel
          </button>
          <button
            v-if="profiles.length > 1 && !store.profile?.is_kids"
            class="netflix-btn-danger"
            @click="confirmDeleteProfile(editTarget)"
            id="delete-profile-btn"
          >
            Delete Profile
          </button>
        </div>
      </div>

      <!-- 3. Dedicated Netflix Add Profile View -->
      <div v-else-if="viewMode === 'create'" class="netflix-form-container">
        <h1 class="netflix-form-header">Add Profile</h1>
        <div class="netflix-form-subtitle">Add a profile for another person watching CapsStream.</div>
        <div class="netflix-form-divider"></div>

        <div class="netflix-form-body">
          <!-- Left: Avatar Preview & Picker -->
          <div class="netflix-form-left">
            <div
              class="netflix-form-avatar-preview"
              :style="{
                background: newProfile.color ? newProfile.color + '44' : 'rgba(255,255,255,0.08)',
                border: '3px solid ' + newProfile.color
              }"
            >
              <span>{{ newProfile.avatar }}</span>
            </div>

            <!-- Avatar Choices Grid -->
            <div style="margin-top:14px;max-width:140px">
              <div style="font-size:0.75rem;color:#808080;margin-bottom:6px;font-weight:600">ICON</div>
              <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px">
                <div
                  v-for="a in avatars"
                  :key="a"
                  @click="newProfile.avatar = a"
                  style="cursor:pointer;font-size:1.3rem;padding:4px;border-radius:4px;text-align:center;transition:background 0.2s"
                  :style="newProfile.avatar === a ? { background: 'rgba(255,255,255,0.2)' } : {}"
                >
                  {{ a }}
                </div>
              </div>
            </div>

            <!-- Color Palette -->
            <div style="margin-top:14px;max-width:140px">
              <div style="font-size:0.75rem;color:#808080;margin-bottom:6px;font-weight:600">COLOR</div>
              <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px">
                <div
                  v-for="c in colors"
                  :key="c"
                  @click="newProfile.color = c"
                  style="width:22px;height:22px;border-radius:50%;cursor:pointer;box-sizing:border-box"
                  :style="{
                    background: c,
                    border: newProfile.color === c ? '2px solid #ffffff' : 'none',
                    transform: newProfile.color === c ? 'scale(1.15)' : 'scale(1)'
                  }"
                ></div>
              </div>
            </div>
          </div>

          <!-- Right: Profile Name, Kids Settings, PIN -->
          <div class="netflix-form-right">
            <div>
              <input
                id="new-profile-name"
                class="netflix-input"
                v-model="newProfile.name"
                placeholder="Name"
                autofocus
              >
            </div>

            <!-- Kids Setting -->
            <div style="border-top:1px solid #282828;padding-top:18px">
              <label class="netflix-checkbox-label">
                <input type="checkbox" v-model="newProfile.is_kids" id="kids-mode-switch">
                <div>
                  <div class="netflix-checkbox-title">Kid?</div>
                  <div class="netflix-checkbox-desc">Only see TV shows and movies rated for kids. Locks app Settings.</div>
                </div>
              </label>
            </div>

            <!-- Kids Screen Time Controls -->
            <div v-if="newProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <div style="font-size:0.95rem;color:#ffffff;font-weight:600;margin-bottom:4px">⏰ Daily Watch Limit</div>
              <div style="font-size:0.85rem;color:#808080;margin-bottom:8px">Automatically lock Kids Mode after watching this amount today.</div>
              <select v-model.number="newProfile.daily_limit_minutes" class="form-input" style="max-width:240px;background:#1a1a1a;color:#fff;border:1px solid #333;padding:8px;border-radius:8px">
                <option :value="0">No Limit (Unlimited)</option>
                <option :value="30">30 Minutes / day</option>
                <option :value="45">45 Minutes / day</option>
                <option :value="60">1 Hour / day</option>
                <option :value="90">1.5 Hours / day</option>
                <option :value="120">2 Hours / day</option>
                <option :value="180">3 Hours / day</option>
              </select>
            </div>

            <div v-if="newProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <div style="font-size:0.95rem;color:#ffffff;font-weight:600;margin-bottom:4px">🌙 Bedtime Curfew</div>
              <div style="font-size:0.85rem;color:#808080;margin-bottom:8px">Locks Kids Mode at this time in the evening.</div>
              <select v-model="newProfile.bedtime_curfew" class="form-input" style="max-width:240px;background:#1a1a1a;color:#fff;border:1px solid #333;padding:8px;border-radius:8px">
                <option value="">Off (No Bedtime Curfew)</option>
                <option value="19:00">7:00 PM</option>
                <option value="19:30">7:30 PM</option>
                <option value="20:00">8:00 PM</option>
                <option value="20:30">8:30 PM</option>
                <option value="21:00">9:00 PM</option>
                <option value="21:30">9:30 PM</option>
                <option value="22:00">10:00 PM</option>
              </select>
            </div>

            <!-- PIN Protection -->
            <div v-if="!newProfile.is_kids" style="border-top:1px solid #282828;padding-top:18px">
              <div style="font-size:0.95rem;color:#ffffff;font-weight:600;margin-bottom:4px">PIN Protection (Optional)</div>
              <div style="font-size:0.85rem;color:#808080;margin-bottom:8px">Leave empty for instant access without a PIN.</div>
              <input
                id="new-profile-pin"
                class="netflix-input"
                v-model="newProfile.pin"
                placeholder="4-digit PIN"
                maxlength="4"
                inputmode="numeric"
                style="max-width:240px"
              >
            </div>
          </div>
        </div>

        <div class="netflix-form-divider"></div>

        <!-- Action Buttons -->
        <div class="netflix-form-buttons">
          <button class="netflix-btn-white" @click="createProfile" id="save-profile-btn">
            Continue
          </button>
          <button class="netflix-btn-ghost" @click="viewMode = 'select'">
            Cancel
          </button>
        </div>
      </div>

      <!-- PIN Modal (Netflix styled) -->
      <div class="modal-backdrop" v-if="pinTarget" @click.self="pinTarget = null" style="background:rgba(0,0,0,0.85)">
        <div class="modal" style="background:#181818;border:1px solid #333;text-align:center;max-width:380px">
          <h3 style="font-size:1.4rem;font-weight:600;margin-bottom:1rem">Enter PIN for {{ pinTarget?.name }}</h3>
          <div class="pin-display" style="justify-content:center;gap:12px;margin-bottom:1.5rem">
            <div v-for="i in 4" :key="i" class="pin-dot"
              :class="{ filled: pin.length >= i, error: pinError }">
            </div>
          </div>
          <div class="pin-pad">
            <button v-for="n in [1,2,3,4,5,6,7,8,9,'',0,'⌫']" :key="n"
              class="pin-key"
              :class="{ backspace: n === '⌫' }"
              @click="handlePinKey(n)"
              :id="'pin-key-' + n"
              :disabled="n === ''"
            >{{ n }}</button>
          </div>
          <div class="modal-error" v-if="pinError" style="margin-top:10px">{{ pinError }}</div>
          <button class="btn btn-ghost btn-full" style="margin-top:1.25rem" @click="pinTarget = null">Cancel</button>
        </div>
      </div>

      <!-- Delete PIN Confirmation Modal -->
      <div class="modal-backdrop" v-if="deletePinTarget" @click.self="deletePinTarget = null" style="background:rgba(0,0,0,0.85)">
        <div class="modal" style="background:#181818;border:1px solid #333;text-align:center;max-width:380px">
          <h3 style="font-size:1.4rem;font-weight:600;margin-bottom:1rem">Enter PIN to Delete {{ deletePinTarget?.name }}</h3>
          <div class="pin-display" style="justify-content:center;gap:12px;margin-bottom:1.5rem">
            <div v-for="i in 4" :key="i" class="pin-dot"
              :class="{ filled: deletePin.length >= i, error: deletePinError }">
            </div>
          </div>
          <div class="pin-pad">
            <button v-for="n in [1,2,3,4,5,6,7,8,9,'',0,'⌫']" :key="n"
              class="pin-key"
              :class="{ backspace: n === '⌫' }"
              @click="handleDeletePinKey(n)"
              :id="'delete-pin-key-' + n"
              :disabled="n === ''"
            >{{ n }}</button>
          </div>
          <div class="modal-error" v-if="deletePinError" style="margin-top:10px">{{ deletePinError }}</div>
          <button class="btn btn-ghost btn-full" style="margin-top:1.25rem" @click="deletePinTarget = null">Cancel</button>
        </div>
      </div>

      <!-- Parental Math Challenge Gate Modal -->
      <div class="modal-backdrop" v-if="mathGateTarget" @click.self="mathGateTarget = null" style="background:rgba(0,0,0,0.88)">
        <div class="modal parental-gate-modal" style="text-align:center;max-width:380px;border-radius:22px;padding:2rem 1.5rem">
          <div class="parental-gate-icon">🛡️</div>
          <h3 style="font-size:1.35rem;font-weight:700;margin:0.5rem 0">Parental Exit Gate</h3>
          <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1.2rem">
            Please solve the math puzzle to switch to <strong>{{ mathGateTarget?.name }}</strong>:
          </p>
          <div class="math-question-badge">
            {{ mathProblem.num1 }} + {{ mathProblem.num2 }} = ?
          </div>
          <div class="pin-display" style="justify-content:center;margin:1rem 0">
            <div class="math-answer-display">{{ mathAnswer || '?' }}</div>
          </div>
          <div class="pin-pad">
            <button v-for="n in [1,2,3,4,5,6,7,8,9,'',0,'⌫']" :key="n"
              class="pin-key"
              :class="{ backspace: n === '⌫' }"
              @click="handleMathKey(n)"
              :id="'math-key-' + n"
              :disabled="n === ''"
            >{{ n }}</button>
          </div>
          <div class="modal-error" v-if="mathGateError" style="margin-top:10px">{{ mathGateError }}</div>
          <button class="btn btn-ghost btn-full" style="margin-top:1.25rem;border-radius:12px" @click="mathGateTarget = null">Cancel</button>
        </div>
      </div>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const route = VueRouter.useRoute();
    const profiles = ref([]);
    const viewMode = ref("select"); // 'select' | 'manage' | 'edit' | 'create'
    const pinTarget = ref(null);
    const pin = ref("");
    const pinError = ref("");
    const mathGateTarget = ref(null);
    const mathAnswer = ref("");
    const mathGateError = ref("");
    const mathProblem = reactive({ num1: 7, num2: 8, answer: 15 });

    const editTarget = ref(null);
    const editProfile = reactive({
      name: "",
      avatar: "🎬",
      color: "#e50914",
      theme: "crimson",
      is_kids: false,
      pin: "",
      update_pin: false,
      daily_limit_minutes: 0,
      bedtime_curfew: "",
    });

    const avatars = ["🎬", "🎭", "🍿", "🎮", "🚀", "🐱", "🐶", "🦊", "🎵", "🌟", "🔥", "💫"];
    const colors = ["#e50914", "#6c5ce7", "#0984e3", "#00b894", "#fdcb6e", "#e17055", "#fd79a8", "#a29bfe"];

    const newProfile = reactive({
      name: "",
      avatar: "🎬",
      color: "#e50914",
      theme: "crimson",
      pin: "",
      is_kids: false,
      daily_limit_minutes: 0,
      bedtime_curfew: "",
    });

    function generateMathProblem() {
      const n1 = Math.floor(Math.random() * 8) + 4;
      const n2 = Math.floor(Math.random() * 8) + 3;
      mathProblem.num1 = n1;
      mathProblem.num2 = n2;
      mathProblem.answer = n1 + n2;
      mathAnswer.value = "";
      mathGateError.value = "";
    }

    function handleMathKey(key) {
      mathGateError.value = "";
      if (key === "⌫") {
        mathAnswer.value = mathAnswer.value.slice(0, -1);
        return;
      }
      if (key === "") return;
      if (mathAnswer.value.length >= 3) return;
      mathAnswer.value += key.toString();

      if (Number(mathAnswer.value) === mathProblem.answer) {
        const target = mathGateTarget.value;
        mathGateTarget.value = null;
        authProfile(target, "");
      } else if (mathAnswer.value.length >= String(mathProblem.answer).length) {
        mathGateError.value = "Incorrect. Try again!";
        setTimeout(() => {
          generateMathProblem();
        }, 900);
      }
    }

    watch(
      () => newProfile.is_kids,
      (kids) => {
        if (kids) newProfile.pin = "";
      }
    );

    watch(
      () => editProfile.is_kids,
      (kids) => {
        if (kids) {
          editProfile.pin = "";
          editProfile.update_pin = false;
        }
      }
    );

    async function load() {
      try {
        profiles.value = await API.get("/api/profiles");
        checkQueryManage();
      } catch (e) {
        addToast("Failed to load profiles", "error");
      }
    }

    function checkQueryManage() {
      if (route.query.manage === "true") {
        viewMode.value = "manage";
        if (route.query.edit_id && profiles.value && profiles.value.length) {
          const target = profiles.value.find((p) => p.id === Number(route.query.edit_id));
          if (target) openEditView(target);
        }
      } else if (viewMode.value !== "create" && viewMode.value !== "edit") {
        viewMode.value = "select";
      }
    }

    function onProfileClick(profile) {
      if (viewMode.value === "manage") {
        openEditView(profile);
      } else {
        selectProfile(profile);
      }
    }

    function openEditView(profile) {
      editTarget.value = profile;
      editProfile.name = profile.name;
      editProfile.avatar = profile.avatar || "🎬";
      editProfile.color = profile.color || "#e50914";
      editProfile.theme = profile.theme || "crimson";
      editProfile.is_kids = !!profile.is_kids;
      editProfile.pin = "";
      editProfile.update_pin = false;
      editProfile.daily_limit_minutes = profile.daily_limit_minutes || 0;
      editProfile.bedtime_curfew = profile.bedtime_curfew || "";
      viewMode.value = "edit";
    }

    function openCreateView() {
      newProfile.name = "";
      newProfile.avatar = "🎬";
      newProfile.color = "#e50914";
      newProfile.theme = "crimson";
      newProfile.pin = "";
      newProfile.is_kids = false;
      viewMode.value = "create";
    }

    async function saveEditProfile() {
      if (!editProfile.name.trim()) {
        addToast("Please enter a name", "error");
        return;
      }
      try {
        const res = await API.put(`/api/profiles/${editTarget.value.id}`, {
          name: editProfile.name.trim(),
          avatar: editProfile.avatar,
          color: editProfile.color,
          theme: editProfile.theme || editTarget.value?.theme || "crimson",
          is_kids: editProfile.is_kids,
          pin: editProfile.pin || "",
          update_pin: editProfile.update_pin,
          daily_limit_minutes: editProfile.daily_limit_minutes,
          bedtime_curfew: editProfile.bedtime_curfew,
        });

        const idx = profiles.value.findIndex((p) => p.id === editTarget.value.id);
        if (idx !== -1) {
          profiles.value[idx] = { ...profiles.value[idx], ...res };
        }

        if (store.profile?.id === editTarget.value.id) {
          store.profile = { ...store.profile, ...res };
        }

        viewMode.value = "manage";
        editTarget.value = null;
        addToast("Profile updated ✓", "success");
      } catch (e) {
        addToast(e.message || "Failed to update profile", "error");
      }
    }

    const deletePinTarget = ref(null);
    const deletePin = ref("");
    const deletePinError = ref("");

    async function confirmDeleteProfile(profile) {
      if (store.profile?.is_kids) {
        addToast("Kids profiles cannot delete profiles", "error");
        return;
      }
      if (profiles.value.length <= 1) {
        addToast("Cannot delete the only profile", "error");
        return;
      }
      if (profile.has_pin) {
        deletePinTarget.value = profile;
        deletePin.value = "";
        deletePinError.value = "";
      } else {
        const ok = await customConfirm({
          title: "Delete Profile",
          message: `Are you sure you want to delete profile "${profile.name}"? This action cannot be undone.`,
          icon: "ph ph-user-minus",
          danger: true,
          okText: "Delete Profile"
        });
        if (!ok) return;
        executeDeleteProfile(profile, "");
      }
    }

    function handleDeletePinKey(key) {
      deletePinError.value = "";
      if (key === "⌫") {
        deletePin.value = deletePin.value.slice(0, -1);
        return;
      }
      if (key === "") return;
      if (deletePin.value.length >= 4) return;
      deletePin.value += key.toString();
      if (deletePin.value.length === 4) {
        executeDeleteProfile(deletePinTarget.value, deletePin.value);
      }
    }

    async function executeDeleteProfile(profile, pinVal) {
      try {
        await API.post(`/api/profiles/${profile.id}`, { pin: pinVal });
        profiles.value = profiles.value.filter((p) => p.id !== profile.id);
        if (store.profile?.id === profile.id) {
          store.profile = null;
        }
        viewMode.value = "manage";
        editTarget.value = null;
        deletePinTarget.value = null;
        addToast("Profile deleted", "success");
      } catch (e) {
        if (profile.has_pin) {
          deletePinError.value = "Incorrect PIN";
          deletePin.value = "";
        } else {
          addToast(e.message || "Failed to delete profile", "error");
        }
      }
    }

    function selectProfile(profile) {
      if (profile.has_pin) {
        pinTarget.value = profile;
        pin.value = "";
        pinError.value = "";
      } else {
        authProfile(profile, "");
      }
    }

    async function authProfile(profile, enteredPin) {
      try {
        const res = await API.post("/api/profiles/auth", {
          profile_id: profile.id,
          pin: enteredPin,
        });
        if (res.ok) {
          store.profile = res.profile;
          pinTarget.value = null;
          router.push("/");
          // Active login — start the library scan (once per session)
          startLibraryScan();
        }
      } catch (e) {
        if (enteredPin === "") {
          pinTarget.value = profile;
        } else {
          pinError.value = "Incorrect PIN";
          pin.value = "";
        }
      }
    }

    function handlePinKey(key) {
      // Any new input clears a previous wrong-PIN error state immediately
      pinError.value = "";
      if (key === "⌫") {
        pin.value = pin.value.slice(0, -1);
        return;
      }
      if (key === "") return;
      if (pin.value.length >= 4) return;
      pin.value += key.toString();
      if (pin.value.length === 4) {
        authProfile(pinTarget.value, pin.value);
      }
    }

    async function createProfile() {
      if (!newProfile.name.trim()) {
        addToast("Please enter a name", "error");
        return;
      }
      try {
        const p = await API.post("/api/profiles", {
          name: newProfile.name.trim(),
          pin: newProfile.pin || "",
          avatar: newProfile.avatar,
          color: newProfile.color,
          theme: newProfile.theme || "crimson",
          is_kids: newProfile.is_kids,
          daily_limit_minutes: newProfile.daily_limit_minutes,
          bedtime_curfew: newProfile.bedtime_curfew,
        });
        profiles.value.push(p);
        viewMode.value = "select";
        newProfile.name = "";
        newProfile.pin = "";
        newProfile.is_kids = false;
        if (newProfile.is_kids) unlockAchievement("kids_creator");
        addToast(newProfile.is_kids ? "Kids profile created 🧒" : "Profile created", "success");
      } catch (e) {
        addToast(e.message || "Failed to create profile", "error");
      }
    }

    watch(
      () => route.query,
      () => {
        checkQueryManage();
      },
      { deep: true }
    );

    onMounted(() => {
      load();
    });

    return {
      store,
      profiles,
      viewMode,
      pinTarget,
      pin,
      pinError,
      editTarget,
      editProfile,
      newProfile,
      avatars,
      colors,
      onProfileClick,
      openEditView,
      openCreateView,
      saveEditProfile,
      confirmDeleteProfile,
      deletePinTarget,
      deletePin,
      deletePinError,
      handleDeletePinKey,
      selectProfile,
      handlePinKey,
      createProfile,
    };
  },
};

// ─── Setup Wizard Page (Fresh Setup) ─────────────────────────

const SetupPage = {
  template: `
    <div class="setup-container">
      <div class="setup-card">
        <div class="setup-header">
          <div class="setup-logo">
            <img src="/static/img/favicon.png" alt="CapsStream" style="height:32px;width:32px;vertical-align:middle;margin-right:8px;display:inline-block">
            <span>CapsStream</span>
          </div>
          <h1 class="setup-title">Welcome to CapsStream</h1>
          <p class="setup-subtitle">Create your primary profile to set up your media streaming library</p>
        </div>

        <form @submit.prevent="submitSetup" class="setup-form">
          <div class="form-group" style="margin-bottom:1.25rem">
            <label class="form-label">Profile Name</label>
            <input
              type="text"
              v-model="name"
              class="form-input"
              placeholder="e.g. Primary User"
              required
              id="setup-name-input"
            />
          </div>

          <div class="form-group" style="margin-bottom:1.25rem">
            <label class="form-label">Choose Avatar</label>
            <div class="avatar-picker-grid">
              <div
                v-for="av in avatars"
                :key="av.icon"
                class="avatar-picker-item"
                :class="{ active: avatar === av.icon }"
                @click="avatar = av.icon"
              >
                <span>{{ av.icon }}</span>
              </div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom:1.75rem">
            <label class="form-label">4-Digit PIN (Optional)</label>
            <input
              type="password"
              v-model="pin"
              maxlength="4"
              class="form-input"
              placeholder="Leave empty for no PIN"
              id="setup-pin-input"
            />
            <span style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;display:block">
              You can lock your profile with a PIN or leave it empty for instant access.
            </span>
          </div>

          <button
            type="submit"
            class="btn btn-primary btn-full btn-lg"
            :disabled="creating || !name.trim()"
            id="setup-submit-btn"
          >
            <span v-if="creating" class="loading-spinner-sm"></span>
            <span v-else>Complete Setup & Start Streaming 🚀</span>
          </button>
        </form>
      </div>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const name = ref("");
    const avatar = ref("🎬");
    const pin = ref("");
    const creating = ref(false);

    const avatars = [{ icon: "🎬" }, { icon: "🍿" }, { icon: "🐉" }, { icon: "🚀" }, { icon: "👑" }, { icon: "🔥" }, { icon: "⚡" }, { icon: "🎭" }];

    async function submitSetup() {
      if (!name.value.trim() || creating.value) return;
      creating.value = true;
      try {
        const created = await API.post("/api/profiles", {
          name: name.value.trim(),
          avatar: avatar.value,
          pin: pin.value.trim() || null,
        });

        // Log into profile
        const authRes = await API.post("/api/profiles/auth", {
          profile_id: created.id,
          pin: pin.value.trim() || null,
        });

        store.profile = authRes.profile || created;
        addToast(`Welcome, ${created.name}!`, "success");

        // Active login — start the library scan (once per session)
        startLibraryScan();

        router.push("/");
      } catch (e) {
        addToast(e.message || "Failed to create profile", "error");
      } finally {
        creating.value = false;
      }
    }

    return { store, name, avatar, pin, avatars, creating, submitSetup };
  },
};

// ─── Search Page ──────────────────────────────────────────────

const SearchPage = {
  components: { MediaCard },
  template: `
    <div class="search-page">
      <!-- Search Hero Header -->
      <div class="search-hero">
        <div class="search-hero-content">
          <div class="search-pill-badge">
            <i class="ph ph-sparkle"></i> DEEP MEDIA DISCOVERY
          </div>
          <h1 class="search-hero-title">Find Movies, Series & Anime</h1>

          <!-- Double-Bezel Search Bar -->
          <div class="search-input-card">
            <div class="card-inner search-input-inner">
              <div v-if="loading" class="search-input-spinner"></div>
              <i v-else class="ph ph-magnifying-glass search-input-icon"></i>
              <input
                ref="searchInputRef"
                type="text"
                v-model="query"
                placeholder="Search titles, actors (e.g. Eric Nam), genres, or year (e.g. 2026)..."
                class="search-text-input"
                @input="onQueryInput"
                @keyup.enter="performSearch"
                id="search-input"
                autofocus
              />
              <button v-if="query" class="search-clear-btn" @click="clearSearch" title="Clear search">
                <i class="ph ph-x"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Filters & Control Bar -->
      <div class="search-controls-container">
        <div class="search-controls-inner">
          <!-- Type Filter Tabs -->
          <div class="search-type-pills">
            <button
              v-for="t in typeOptions"
              :key="t.value"
              class="type-pill"
              :class="{ active: selectedType === t.value }"
              @click="selectType(t.value)"
            >
              <i :class="t.icon"></i> {{ t.label }}
            </button>
          </div>

          <div class="search-filter-selectors">
            <!-- Genre Selector -->
            <select v-model="selectedGenre" class="form-input search-select" @change="performSearch">
              <option value="all">All Genres</option>
              <option v-for="g in genresList" :key="g" :value="g">{{ g }}</option>
            </select>

            <!-- Sort Selector -->
            <select v-model="selectedSort" class="form-input search-select" @change="performSearch">
              <option value="relevance">Sort: Highest Rated</option>
              <option value="year_desc">Sort: Release Year (Newest)</option>
              <option value="title_asc">Sort: Title (A - Z)</option>
            </select>
          </div>
        </div>
      </div>

      <!-- Results Body -->
      <div class="search-results-container">
        <!-- Double-Bezel Loading Card -->
        <div v-if="loading" class="search-loading-card">
          <div class="search-loading-inner">
            <div class="search-bento-spinner"></div>
            <div class="search-loading-title">Searching media library...</div>
            <div class="search-loading-subtitle">Probing audio tracks, titles & cast metadata</div>
          </div>
        </div>

        <!-- Dynamic Results Header -->
        <div v-else-if="results.length" class="search-results-header">
          <div class="search-results-count">
            Found <strong style="color:var(--text-primary)">{{ results.length }}</strong> {{ results.length === 1 ? 'title' : 'titles' }}
            <span v-if="query"> matching "<strong style="color:var(--accent)">{{ query }}</strong>"</span>
          </div>
        </div>

        <!-- Results Grid -->
        <div v-if="!loading && results.length" class="search-grid">
          <MediaCard v-for="item in paginatedResults" :key="item.id || item.tmdb_id" :item="item" @click="handleClick" />
        </div>

        <!-- Classic Page Number Bar Pagination -->
        <div v-if="!loading && results.length > 0" class="pagination-bar">
          <button class="pagination-btn" :disabled="currentPage === 1" @click="setPage(1)" title="First Page">
            « First
          </button>
          <button class="pagination-btn" :disabled="currentPage === 1" @click="setPage(currentPage - 1)" title="Previous Page">
            ‹ Prev
          </button>

          <div class="pagination-numbers" v-if="totalPages > 1">
            <button
              v-for="p in visiblePageNumbers"
              :key="p"
              class="pagination-num-btn"
              :class="{ active: currentPage === p }"
              @click="setPage(p)"
            >
              {{ p }}
            </button>
          </div>

          <span class="pagination-info">
            Page <strong>{{ currentPage }}</strong> of <strong>{{ totalPages }}</strong>
            <span style="font-size:0.75rem;color:var(--text-muted);margin-left:6px">({{ results.length }} total matches)</span>
          </span>

          <button class="pagination-btn" :disabled="currentPage === totalPages" @click="setPage(currentPage + 1)" title="Next Page">
            Next ›
          </button>
          <button class="pagination-btn" :disabled="currentPage === totalPages" @click="setPage(totalPages)" title="Last Page">
            Last »
          </button>

          <!-- Items Per Page Selector -->
          <div class="pagination-size-selector">
            <span style="font-size:0.8rem;color:var(--text-muted)">Per page:</span>
            <select v-model.number="pageSize" class="form-input pagination-select" @change="currentPage = 1" id="search-page-size-select">
              <option :value="12">12 / page</option>
              <option :value="24">24 / page</option>
              <option :value="48">48 / page</option>
              <option :value="96">96 / page</option>
              <option :value="999999">Show All</option>
            </select>
          </div>
        </div>

        <!-- Empty Results State (Double-Bezel Card) -->
        <div v-else-if="!loading && searched && results.length === 0" class="search-empty-card">
          <div class="search-empty-inner">
            <div class="search-empty-icon">🔍</div>
            <h2 class="search-empty-title">No Media Found</h2>
            <div class="search-empty-subtitle">
              No matching titles found<span v-if="query"> for "<strong style="color:var(--text-primary)">{{ query }}</strong>"</span>. Try searching for an actor, release year, multi-audio tracks, or choosing another genre filter.
            </div>
            <div class="search-suggestions" v-if="store.profile?.is_kids">
              <span class="suggestion-tag" @click="quickSearch('Animation')">🎨 Animation</span>
              <span class="suggestion-tag" @click="quickSearch('Fantasy')">🪄 Magic</span>
              <span class="suggestion-tag" @click="quickSearch('Family')">🐾 Animals & Family</span>
              <span class="suggestion-tag" @click="quickSearch('Comedy')">😄 Comedy</span>
            </div>
            <div class="search-suggestions" v-else>
              <span class="suggestion-tag" @click="quickSearch('Multi Audio')">🌐 Multi Audio</span>
              <span class="suggestion-tag" @click="quickSearch('x265')">⚡ HEVC / x265</span>
              <span class="suggestion-tag" @click="quickSearch('1080p')">📺 1080p Quality</span>
              <span class="suggestion-tag" @click="quickSearch('Action')">🔥 Action</span>
              <span class="suggestion-tag" @click="quickSearch('2026')">📅 2026</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const searchInputRef = ref(null);

    const query = ref('');
    const selectedType = ref('all');
    const selectedGenre = ref('all');
    const selectedSort = ref('relevance');

    const pageSize = ref(24);
    const currentPage = ref(1);

    const results = ref([]);
    const loading = ref(false);
    const searched = ref(false);
    const allGenresList = [
      'Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary', 
      'Drama', 'Family', 'Fantasy', 'Horror', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller'
    ];
    const kidsGenresList = [
      'Animation', 'Family', 'Adventure', 'Comedy', 'Fantasy', 'Sci-Fi', 'Documentary'
    ];
    const genresList = computed(() => store.profile?.is_kids ? kidsGenresList : allGenresList);

    let debounceTimer = null;

    const typeOptions = [
      { label: 'All', value: 'all', icon: 'ph ph-squares-four' },
      { label: 'Movies', value: 'movie', icon: 'ph ph-film-strip' },
      { label: 'Series', value: 'series', icon: 'ph ph-television' },
      { label: 'Anime', value: 'anime', icon: 'ph ph-sparkle' },
    ];

    async function performSearch() {
      loading.value = true;
      searched.value = true;
      currentPage.value = 1;
      if (query.value && query.value.trim()) unlockAchievement("search_master");
      try {
        const res = await API.get(`/api/search?q=${encodeURIComponent(query.value)}&type=${selectedType.value}&genre=${selectedGenre.value}&sort=${selectedSort.value}`);
        results.value = kidsFilter(res || []);
      } catch (e) {
        results.value = [];
      } finally {
        loading.value = false;
      }
    }

    const totalPages = computed(() => {
      return Math.ceil(results.value.length / pageSize.value) || 1;
    });

    const paginatedResults = computed(() => {
      const start = (currentPage.value - 1) * pageSize.value;
      return results.value.slice(start, start + pageSize.value);
    });

    const visiblePageNumbers = computed(() => {
      const total = totalPages.value;
      const current = currentPage.value;
      const pages = [];
      const delta = 2;
      const start = Math.max(1, current - delta);
      const end = Math.min(total, current + delta);
      for (let i = start; i <= end; i++) {
        pages.push(i);
      }
      return pages;
    });

    function setPage(page) {
      if (page < 1 || page > totalPages.value) return;
      currentPage.value = page;
      window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function onQueryInput() {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        performSearch();
      }, 300);
    }

    function clearSearch() {
      query.value = '';
      performSearch();
      if (searchInputRef.value) searchInputRef.value.focus();
    }

    function selectType(type) {
      selectedType.value = type;
      performSearch();
    }

    function quickSearch(tag) {
      query.value = tag;
      performSearch();
    }

    function handleGlobalHotkeys(e) {
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
        e.preventDefault();
        if (searchInputRef.value) searchInputRef.value.focus();
      }
    }

    onMounted(() => {
      window.addEventListener('keydown', handleGlobalHotkeys);
      if (route.query.q) {
        query.value = route.query.q;
      }
      performSearch();
    });

    // React to external navigations into /search?q=... (e.g., cast member
    // clicks) while this page is already mounted.
    watch(
      () => route.query.q,
      (q) => {
        const newQ = typeof q === "string" ? q : "";
        if (newQ && newQ !== query.value) {
          query.value = newQ;
          performSearch();
        }
      }
    );

    onUnmounted(() => {
      window.removeEventListener('keydown', handleGlobalHotkeys);
      clearTimeout(debounceTimer);
    });

    function handleClick(item) {
      if (!item) return;
      if (item.is_mounted === false) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      if (item.type === "movie") {
        router.push(`/title/movie/${item.id}`);
      } else {
        router.push(`/title/${item.type}/${item.tmdb_id || item.id}`);
      }
    }

    return {
      store, searchInputRef, query, selectedType, selectedGenre, selectedSort,
      results, paginatedResults, currentPage, pageSize, totalPages, visiblePageNumbers, setPage, loading, searched, genresList, typeOptions,
      performSearch, onQueryInput, clearSearch, selectType, quickSearch, handleClick
    };
  }
};

// ─── Profile Watch Stats & Insights Page ──────────────────────

const StatsPage = {
  template: `
    <div class="stats-page" style="max-width:1100px;margin:calc(var(--nav-height) + 2rem) auto 4rem;padding:0 var(--space-lg)">
      <div style="margin-bottom:2rem;display:flex;align-items:center;justify-content:space-between">
        <div>
          <h1 style="font-size:2rem;font-weight:800;display:flex;align-items:center;gap:10px">
            <i :class="store.profile?.is_kids ? 'ph ph-star' : 'ph ph-chart-bar'" :style="{ color: store.profile?.is_kids ? '#fdcb6e' : 'var(--accent)' }"></i>
            <span>{{ store.profile?.is_kids ? '🌟 Kids Stats & Trophy Case' : 'Watch Stats & Insights' }}</span>
          </h1>
          <p style="color:var(--text-secondary);margin-top:4px">{{ store.profile?.is_kids ? 'Viewing badges and cartoon adventures for ' : 'Viewing analytics and watch activity for ' }}<strong>{{ store.profile?.name }}</strong></p>
        </div>
      </div>

      <div v-if="loading" class="loading-spinner" style="margin:4rem auto"></div>

      <template v-else-if="stats">
        <!-- Overview Stat Cards Grid -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:1.25rem;margin-bottom:2rem">
          <div class="card-inner" style="padding:1.5rem;background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;gap:1rem">
            <div style="width:52px;height:52px;border-radius:12px;background:rgba(229,9,20,0.15);display:flex;align-items:center;justify-content:center;font-size:1.6rem;color:var(--accent)">
              <i class="ph ph-clock"></i>
            </div>
            <div>
              <div style="font-size:0.8rem;color:var(--text-muted);font-weight:600;text-transform:uppercase">{{ store.profile?.is_kids ? 'Total Cartoon Time' : 'Total Watch Time' }}</div>
              <div style="font-size:1.4rem;font-weight:800;color:#fff">{{ formatTimeSpent(stats.total_seconds) }}</div>
            </div>
          </div>

          <div class="card-inner" style="padding:1.5rem;background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;gap:1rem">
            <div style="width:52px;height:52px;border-radius:12px;background:rgba(56,189,248,0.15);display:flex;align-items:center;justify-content:center;font-size:1.6rem;color:#38bdf8">
              <i class="ph ph-check-circle"></i>
            </div>
            <div>
              <div style="font-size:0.8rem;color:var(--text-muted);font-weight:600;text-transform:uppercase">{{ store.profile?.is_kids ? 'Cartoons Finished' : 'Completion Rate' }}</div>
              <div style="font-size:1.4rem;font-weight:800;color:#fff">{{ stats.completion_rate }}% <span style="font-size:0.75rem;color:var(--text-muted);font-weight:500">({{ stats.completed_items }}/{{ stats.total_items }})</span></div>
            </div>
          </div>

          <div class="card-inner" style="padding:1.5rem;background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;gap:1rem">
            <div style="width:52px;height:52px;border-radius:12px;background:rgba(245,158,11,0.15);display:flex;align-items:center;justify-content:center;font-size:1.6rem;color:#f59e0b">
              <i class="ph ph-sun-dim"></i>
            </div>
            <div>
              <div style="font-size:0.8rem;color:var(--text-muted);font-weight:600;text-transform:uppercase">{{ store.profile?.is_kids ? 'Favorite Watch Time' : 'Peak Watch Hour' }}</div>
              <div style="font-size:1.2rem;font-weight:800;color:#fff">{{ stats.peak_hour }}</div>
            </div>
          </div>

          <div v-if="!store.profile?.is_kids" class="card-inner" style="padding:1.5rem;background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;display:flex;align-items:center;gap:1rem">
            <div style="width:52px;height:52px;border-radius:12px;background:rgba(168,85,247,0.15);display:flex;align-items:center;justify-content:center;font-size:1.6rem;color:#a855f7">
              <i class="ph ph-hard-drives"></i>
            </div>
            <div>
              <div style="font-size:0.8rem;color:var(--text-muted);font-weight:600;text-transform:uppercase">Mounted Storage</div>
              <div style="font-size:1.4rem;font-weight:800;color:#fff">{{ stats.technical_stats?.total_storage_formatted || (stats.technical_stats?.total_storage_gb ? stats.technical_stats.total_storage_gb + ' GB' : '0 GB') }}</div>
            </div>
          </div>
        </div>

        <!-- 7-Day Watch Activity & Technical Metrics Row -->
        <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:1.5rem;margin-bottom:2.5rem">
          <!-- 7-Day Watch Activity Chart -->
          <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;padding:1.75rem">
            <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;display:flex;align-items:center;gap:8px">
              <i :class="store.profile?.is_kids ? 'ph ph-calendar' : 'ph ph-chart-line-up'" :style="{ color: store.profile?.is_kids ? '#fdcb6e' : 'var(--accent)' }"></i>
              <span>{{ store.profile?.is_kids ? '📅 7-Day Cartoon Time' : '7-Day Watch Activity (Minutes)' }}</span>
            </h3>
            <div class="stats-activity-chart">
              <div
                v-for="d in stats.weekly_activity"
                :key="d.date"
                class="chart-bar-col"
                :class="{ 'active-day': d.minutes > 0 }"
              >
                <div class="chart-bar-track">
                  <div
                    class="chart-bar-fill"
                    :style="{ height: Math.min(100, Math.max(12, (d.minutes / (maxWeeklyMinutes || 1)) * 100)) + '%' }"
                  ></div>
                </div>
                <div class="chart-bar-val" v-if="d.minutes > 0">{{ d.minutes }}m</div>
                <div class="chart-bar-label">{{ d.day }}</div>
              </div>
            </div>
          </div>

          <!-- Technical Library & Resolution Breakdown -->
          <div v-if="!store.profile?.is_kids" style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;padding:1.75rem">
            <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;display:flex;align-items:center;gap:8px">
              <i class="ph ph-film-strip" style="color:#38bdf8"></i> Library Resolution & Quality
            </h3>
            <div class="tech-res-grid">
              <div class="tech-res-card" :class="{ 'has-items': stats.technical_stats?.resolutions?.['4K'] > 0 }">
                <div class="tech-res-val" style="color:#a855f7">💎 {{ stats.technical_stats?.resolutions?.['4K'] || 0 }}</div>
                <div class="tech-res-label">4K Ultra HD</div>
              </div>
              <div class="tech-res-card" :class="{ 'has-items': stats.technical_stats?.resolutions?.['1080p'] > 0 }">
                <div class="tech-res-val" style="color:#38bdf8">🎬 {{ stats.technical_stats?.resolutions?.['1080p'] || 0 }}</div>
                <div class="tech-res-label">1080p Full HD</div>
              </div>
              <div class="tech-res-card" :class="{ 'has-items': stats.technical_stats?.resolutions?.['720p'] > 0 }">
                <div class="tech-res-val" style="color:#f59e0b">📺 {{ stats.technical_stats?.resolutions?.['720p'] || 0 }}</div>
                <div class="tech-res-label">720p HD</div>
              </div>
              <div class="tech-res-card" :class="{ 'has-items': stats.technical_stats?.resolutions?.['SD'] > 0 }">
                <div class="tech-res-val" style="color:var(--text-muted)">📼 {{ stats.technical_stats?.resolutions?.['SD'] || 0 }}</div>
                <div class="tech-res-label">Standard (SD)</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Genre Distribution Progress Section -->
        <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;padding:1.75rem;margin-bottom:2.5rem">
          <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;display:flex;align-items:center;gap:8px">
            <i :class="store.profile?.is_kids ? 'ph ph-balloon' : 'ph ph-tag'" :style="{ color: store.profile?.is_kids ? '#fdcb6e' : 'var(--accent)' }"></i>
            <span>{{ store.profile?.is_kids ? '🎈 Favorite Cartoon Categories' : 'Favorite Genres Distribution' }}</span>
          </h3>
          <div v-if="stats.top_genres && stats.top_genres.length" style="display:flex;flex-direction:column;gap:1rem">
            <div v-for="g in stats.top_genres" :key="g.genre">
              <div style="display:flex;justify-content:space-between;font-size:0.9rem;font-weight:600;margin-bottom:4px">
                <span>{{ g.genre }}</span>
                <span style="color:var(--text-muted)">{{ g.count }} title{{ g.count > 1 ? 's' : '' }}</span>
              </div>
              <div style="height:10px;background:rgba(255,255,255,0.08);border-radius:6px;overflow:hidden">
                <div :style="{ width: calcGenrePercent(g.count) + '%' }" style="height:100%;background:linear-gradient(90deg, var(--accent), #ff758c);border-radius:6px;transition:width 0.6s ease"></div>
              </div>
            </div>
          </div>
          <div v-else style="color:var(--text-muted);text-align:center;padding:1.5rem">
            Watch titles in your library to unlock genre analytics!
          </div>
        </div>

        <!-- Achievements & Badges Trophy Case Section -->
        <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;padding:1.75rem;margin-bottom:2.5rem" class="trophy-case-header">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem;flex-wrap:wrap;gap:10px">
            <h3 style="font-size:1.15rem;font-weight:800;display:flex;align-items:center;gap:10px">
              <i class="ph ph-trophy" style="color:#f59e0b;font-size:1.35rem"></i>
              <span>{{ store.profile?.is_kids ? '🌟 Kids Badges & Trophy Case' : 'Achievements & Badges Trophy Case' }}</span>
            </h3>
            <span style="font-size:0.9rem;font-weight:700;color:var(--accent)" v-if="stats.achievements">
              {{ unlockedCount }} / {{ totalCount }} Unlocked ({{ completionPercent }}%)
            </span>
          </div>

          <!-- Completion Progress Bar -->
          <div class="trophy-progress-container" v-if="stats.achievements">
            <div class="trophy-progress-bar">
              <div class="trophy-progress-fill" :style="{ width: completionPercent + '%' }"></div>
            </div>
          </div>

          <!-- Category Filter Tabs -->
          <div class="trophy-category-tabs" style="margin-top:1.25rem" v-if="stats.achievements">
            <button
              v-for="cat in categories"
              :key="cat"
              class="trophy-category-tab"
              :class="{ active: activeCategory === cat }"
              @click="activeCategory = cat"
            >
              {{ cat }}
            </button>
          </div>

          <!-- Achievements Grid -->
          <div v-if="filteredAchievements && filteredAchievements.length" class="achievements-grid">
            <div
              v-for="ach in filteredAchievements"
              :key="ach.id"
              class="achievement-card"
              :class="['rarity-' + (ach.rarity || 'bronze').toLowerCase(), { unlocked: ach.unlocked }]"
            >
              <div class="achievement-icon-wrapper">
                {{ ach.unlocked ? ach.icon : '🔒' }}
              </div>
              <div class="achievement-info">
                <div class="achievement-header">
                  <span class="achievement-title">{{ ach.title }}</span>
                  <div class="achievement-badge-group">
                    <span class="rarity-badge" :class="(ach.rarity || 'bronze').toLowerCase()">{{ ach.rarity || 'Bronze' }}</span>
                    <span v-if="ach.unlocked" class="achievement-badge">UNLOCKED</span>
                    <span v-else class="achievement-badge locked">LOCKED</span>
                  </div>
                </div>
                <div class="achievement-desc">{{ ach.description }}</div>
                <div v-if="ach.unlocked && ach.unlocked_at" class="achievement-unlocked-date">
                  <i class="ph ph-check-circle" style="color:#10b981"></i> {{ ach.unlocked_at }}
                </div>
              </div>
            </div>
          </div>
          <div v-else style="color:var(--text-muted);text-align:center;padding:1.5rem">
            No achievements found in this category.
          </div>
        </div>

        <!-- Recently Watched History -->
        <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:16px;padding:1.75rem">
          <h3 style="font-size:1.1rem;font-weight:700;margin-bottom:1.25rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <span style="display:flex;align-items:center;gap:8px">
              <i class="ph ph-history" style="color:var(--accent)"></i>
              <span>{{ store.profile?.is_kids ? '🎬 Recent Cartoons & Movies' : 'Recent Watch History' }}</span>
            </span>
            <span style="font-size:0.75rem;font-weight:600;color:var(--text-muted)">Consolidated Titles</span>
          </h3>
          <div v-if="stats.recent_history && stats.recent_history.length" style="display:flex;flex-direction:column;gap:10px">
            <div
              v-for="item in stats.recent_history"
              :key="item.id"
              style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:rgba(255,255,255,0.03);border-radius:12px;cursor:pointer;transition:background 0.2s ease"
              class="history-row-item"
              @click="openMedia(item)"
            >
              <div style="display:flex;align-items:center;gap:14px;min-width:0">
                <img
                  v-if="item.poster_path"
                  :src="imgUrl(item.poster_path)"
                  style="width:42px;height:58px;object-fit:cover;border-radius:6px;flex-shrink:0"
                />
                <div style="min-width:0">
                  <div style="font-weight:700;font-size:0.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" :title="item.title">
                    {{ item.title }}
                  </div>
                  <div style="font-size:0.8rem;color:var(--text-muted);margin-top:3px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    <span style="color:var(--text-secondary);font-weight:600">
                      {{ item.type === 'anime' ? 'Anime' : item.type === 'series' ? 'Series' : 'Movie' }}
                    </span>
                    <span v-if="item.season && item.episode" style="color:var(--text-primary);font-weight:600">
                      · Latest: S{{ (item.season||'').toString().padStart(2,'0') }}E{{ (item.episode||'').toString().padStart(2,'0') }}
                      <span v-if="item.ep_title" style="color:var(--text-muted);font-weight:500"> ("{{ item.ep_title }}")</span>
                    </span>
                  </div>
                </div>
              </div>

              <div style="text-align:right;flex-shrink:0;margin-left:12px">
                <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px">
                  <span v-if="item.ep_count && item.ep_count > 1" style="font-size:0.72rem;font-weight:700;background:rgba(229,9,20,0.18);color:var(--accent);border:1px solid rgba(229,9,20,0.35);padding:2px 8px;border-radius:99px">
                    {{ item.ep_count }} eps watched
                  </span>
                  <span style="font-size:0.85rem;font-weight:700;color:var(--accent)">
                    {{ item.completed ? 'Completed ✓' : formatTimeSpent(item.position) }}
                  </span>
                </div>
                <div style="font-size:0.75rem;color:var(--text-muted);margin-top:3px">
                  {{ formatDate(item.last_watched) }}
                </div>
              </div>
            </div>
          </div>
          <div v-else style="color:var(--text-muted);text-align:center;padding:1.5rem">
            No watch history recorded yet. Start watching a title!
          </div>
        </div>
      </template>
    </div>
  `,
  setup() {
    const router = VueRouter.useRouter();
    const stats = ref(null);
    const loading = ref(true);
    const activeCategory = ref("All");
    const categories = computed(() => {
      if (!stats.value?.achievements?.length) {
        return ["All", "Milestones", "Viewing Habits", "Player Master", "Discovery", "Collector"];
      }
      const uniqueCats = Array.from(new Set(stats.value.achievements.map(a => a.category).filter(Boolean)));
      return ["All", ...uniqueCats];
    });

    const unlockedCount = computed(() => {
      if (!stats.value?.achievements) return 0;
      return stats.value.achievements.filter(a => a.unlocked).length;
    });

    const totalCount = computed(() => stats.value?.achievements?.length || 0);

    const completionPercent = computed(() => {
      if (!totalCount.value) return 0;
      return Math.round((unlockedCount.value / totalCount.value) * 100);
    });

    const filteredAchievements = computed(() => {
      if (!stats.value?.achievements) return [];
      if (activeCategory.value === "All") return stats.value.achievements;
      return stats.value.achievements.filter(a => a.category === activeCategory.value);
    });

    const maxWeeklyMinutes = computed(() => {
      if (!stats.value?.weekly_activity?.length) return 60;
      const maxVal = Math.max(...stats.value.weekly_activity.map(d => d.minutes || 0));
      return maxVal > 0 ? maxVal : 60;
    });

    async function loadStats() {
      loading.value = true;
      try {
        stats.value = await API.get("/api/stats");
      } catch (e) {
        addToast("Failed to load watch stats", "error");
      } finally {
        loading.value = false;
      }
    }

    onMounted(loadStats);

    function formatTimeSpent(seconds) {
      if (!seconds || isNaN(seconds)) return "0m";
      const s = Math.floor(seconds);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      if (h > 0) {
        return `${h}h ${m}m`;
      }
      return `${m}m`;
    }

    function calcGenrePercent(count) {
      if (!stats.value?.top_genres?.length) return 0;
      const maxCount = Math.max(...stats.value.top_genres.map(g => g.count));
      return Math.min(100, Math.round((count / (maxCount || 1)) * 100));
    }

    function formatDate(dateStr) {
      if (!dateStr) return "";
      try {
        return new Date(dateStr).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      } catch (e) {
        return dateStr;
      }
    }

    function openMedia(item) {
      if (item.type === "movie" && item.id) {
        router.push(`/title/movie/${item.id}`);
      } else if (item.tmdb_id) {
        router.push(`/title/${item.type || "series"}/${item.tmdb_id}`);
      }
    }

    return {
      store,
      stats,
      loading,
      activeCategory,
      categories,
      unlockedCount,
      totalCount,
      completionPercent,
      filteredAchievements,
      maxWeeklyMinutes,
      formatTimeSpent,
      calcGenrePercent,
      formatDate,
      openMedia,
      imgUrl,
    };
  },
};

// ─── About Page ───────────────────────────────────────────────

const AboutPage = {
  template: `
    <div class="about-page-wrapper">
      <div class="about-glow-orb-1"></div>
      <div class="about-glow-orb-2"></div>

      <div class="about-page">
      <!-- Hero Banner -->
      <div class="about-hero">
        <div class="about-hero-badge">
          <img src="/static/img/favicon.png" alt="CapsStream" class="about-hero-logo">
          <span>CapsStream v{{ sysInfo?.version || '2.0.0.0' }}</span>
          <span v-if="sysInfo?.is_dev" class="about-dev-badge" title="Local DEV flag active">🛠️ DEV BUILD</span>
        </div>
        <h1 class="about-hero-title">Stream Everything You Own.</h1>
        <p class="about-hero-subtitle">
          CapsStream is your personal streaming platform for movies and TV shows. Built for self-hosting, it delivers a clean, Netflix-inspired experience with fast browsing, rich metadata, watch history, continue watching, and seamless playback.
        </p>
        <div class="about-hero-tags">
          <span class="about-tag">🎬 4K HEVC Ready</span>
          <span class="about-tag">⚡ AniSkip & FFprobe</span>
          <span class="about-tag">🔒 Kids & Multi-Profile</span>
          <span class="about-tag">🏆 Trophy Case</span>
          <span class="about-tag">📁 Multi-Drive Scanner</span>
        </div>
      </div>

      <!-- Feature Bento Grid -->
      <div class="about-section">
        <div class="about-section-header">
          <i class="ph ph-sparkle" style="color:var(--accent);font-size:1.5rem"></i>
          <span>Key Platform Highlights</span>
        </div>

        <div class="about-bento-grid">
          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(229,9,20,0.15);color:var(--accent)">
              <i class="ph ph-film-strip"></i>
            </div>
            <div class="bento-title">High-Perf 4K & Multi-Audio Engine</div>
            <div class="bento-desc">Direct playback & hardware acceleration for HEVC, H.264, and Dolby AC-3 / AAC multi-track audio.</div>
          </div>

          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(56,189,248,0.15);color:#38bdf8">
              <i class="ph ph-timer"></i>
            </div>
            <div class="bento-title">Smart & Manual Skip Markers</div>
            <div class="bento-desc">Manual 1-click frame stamping for Recaps, Intros, and Outros — with automatic AniSkip lookup for anime and FFprobe chapter detection as fallbacks.</div>
          </div>

          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(16,185,129,0.15);color:#10b981">
              <i class="ph ph-user-focus"></i>
            </div>
            <div class="bento-title">Multi-Profile & Kids PIN Lock</div>
            <div class="bento-desc">Personalized watch history, favorites, and watchlist per profile with optional 4-digit PIN protection and Kids Mode filters.</div>
          </div>

          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(245,158,11,0.15);color:#f59e0b">
              <i class="ph ph-trophy"></i>
            </div>
            <div class="bento-title">Trophy Case & Analytics</div>
            <div class="bento-desc">Unlockable achievement badges, detailed viewing statistics, milestones, and category habit analysis.</div>
          </div>

          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(168,85,247,0.15);color:#a855f7">
              <i class="ph ph-folder-notch-open"></i>
            </div>
            <div class="bento-title">Multi-Drive Media Scanner</div>
            <div class="bento-desc">Scans local directories and external drives (E:\\, D:\\) with native OS folder browser dialogs and live connected/unmounted status badges.</div>
          </div>

          <div class="bento-card">
            <div class="bento-icon-wrap" style="background:rgba(236,72,153,0.15);color:#ec4899">
              <i class="ph ph-paint-brush"></i>
            </div>
            <div class="bento-title">Single-Layer Glass Aesthetics</div>
            <div class="bento-desc">Ultra-premium glassmorphic theme featuring smooth micro-animations, single-layer cards, and animated sliding pill navbar indicators.</div>
          </div>
        </div>
      </div>

      <!-- Live Server & Diagnostics Status (3-Section Glass Cards) -->
      <div v-if="!store.profile?.is_kids" class="about-section" style="margin-top:2.5rem">
        <div class="about-section-header" style="justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div style="display:flex;align-items:center;gap:8px">
            <i class="ph ph-cpu" style="color:var(--accent);font-size:1.5rem"></i>
            <span>Live Server & Enterprise Diagnostics Suite</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <button class="btn btn-secondary btn-sm" @click="$router.push('/logs')" title="View live server log">
              <i class="ph ph-scroll" style="margin-right:4px"></i> Live Logs
            </button>
            <div :class="['server-status-pill', store.serverOnline ? 'online' : 'offline']">
              <span class="status-dot"></span>
              <span>{{ store.serverOnline ? 'Server Online' : 'Server Offline / Disconnected' }}</span>
            </div>
          </div>
        </div>

        <div v-if="!store.serverOnline" class="server-offline-banner">
          <i class="ph ph-warning-octagon" style="font-size:1.5rem;flex-shrink:0"></i>
          <div>
            <strong>Backend Server Disconnected!</strong>
            <div>The CapsStream Flask backend is unreachable or stopped. Please launch <code>start.bat</code> to resume server connectivity.</div>
          </div>
        </div>

        <div v-if="loadingSysInfo" style="display:flex;justify-content:center;padding:2.5rem">
          <div class="loading-spinner"></div>
        </div>

        <div v-else-if="sysInfo" class="diag-sections-container">
          <!-- Card 1: System & Memory Health -->
          <div class="diag-section-card">
            <div class="diag-section-header">
              <i class="ph ph-heartbeat" style="color:#10b981"></i>
              <span>Server Health</span>
            </div>

            <div class="diagnostics-grid">
              <div class="diag-item">
                <div class="diag-label">APP VERSION</div>
                <div class="diag-val" style="color:var(--accent);font-weight:700">v{{ sysInfo.version }}</div>
                <div class="diag-sub">Python {{ sysInfo.python_version }}</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">SERVER UPTIME</div>
                <div class="diag-val" style="color:#10b981">{{ sysInfo.server_uptime || 'Active' }}</div>
                <div class="diag-sub">Serving at {{ sysInfo.server_addr || '127.0.0.1:8000' }}</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">HOST OS</div>
                <div class="diag-val">{{ sysInfo.os_name === 'nt' ? 'Windows' : sysInfo.os_name }}</div>
                <div class="diag-sub" :title="sysInfo.platform">{{ sysInfo.platform }}</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">ENVIRONMENT</div>
                <div class="diag-val" :style="{ color: sysInfo.is_dev ? '#fbbf24' : '#10b981' }">
                  {{ sysInfo.is_dev ? '🛠️ Development' : '🚀 Production' }}
                </div>
                <div class="diag-sub">{{ sysInfo.is_dev ? 'Local DEV flag active' : 'Standard release build' }}</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">FFMPEG / FFPROBE</div>
                <div class="diag-val" :style="{ color: sysInfo.has_ffmpeg ? '#10b981' : '#ef4444' }">
                  {{ sysInfo.has_ffmpeg && sysInfo.has_ffprobe ? 'Ready' : !sysInfo.has_ffmpeg ? 'ffmpeg missing' : 'ffprobe missing' }}
                </div>
                <div class="diag-sub">Transcoding & remux pipeline</div>
              </div>
              <div class="diag-item" style="grid-column:1 / -1" v-if="sysInfo.ram_info && sysInfo.ram_info.total_gb">
                <div class="diag-label" style="display:flex;justify-content:space-between">
                  <span>SYSTEM MEMORY</span>
                  <span style="color:var(--text-primary)">{{ sysInfo.ram_info.used_gb }} GB / {{ sysInfo.ram_info.total_gb }} GB ({{ sysInfo.ram_info.load_pct }}%)</span>
                </div>
                <div class="ram-meter-track">
                  <div class="ram-meter-fill" :style="{ width: sysInfo.ram_info.load_pct + '%' }"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Card 2: External Service Health (live probes) -->
          <div class="diag-section-card">
            <div class="diag-section-header">
              <i class="ph ph-globe-hemisphere-west" style="color:#38bdf8"></i>
              <span>External Services</span>
            </div>

            <div class="diagnostics-grid" v-if="sysInfo.api_health">
              <div class="diag-item" v-for="svc in serviceList" :key="svc.key">
                <div class="diag-label">{{ svc.label }}</div>
                <div class="diag-val" :style="{ color: serviceColor(sysInfo.api_health[svc.key]?.status) }">
                  {{ serviceText(svc, sysInfo.api_health[svc.key]) }}
                </div>
                <div class="diag-sub">{{ svc.sub }}</div>
              </div>
            </div>
          </div>

          <!-- Card 3: Library & Database -->
          <div class="diag-section-card">
            <div class="diag-section-header">
              <i class="ph ph-database" style="color:#a855f7"></i>
              <span>Library & Database</span>
            </div>

            <div class="diagnostics-grid">
              <div class="diag-item">
                <div class="diag-label">LIBRARY ITEMS</div>
                <div class="diag-val">{{ sysInfo.media_counts?.total ?? 0 }}</div>
                <div class="diag-sub">{{ sysInfo.media_counts?.movies || 0 }} movies • {{ sysInfo.media_counts?.series || 0 }} series • {{ sysInfo.media_counts?.anime || 0 }} anime</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">DATABASE SIZE</div>
                <div class="diag-val">{{ sysInfo.database_size }}</div>
                <div class="diag-sub">SQLite DB file</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">WATCH HISTORY</div>
                <div class="diag-val">{{ sysInfo.db_metrics?.progress_count ?? 0 }}</div>
                <div class="diag-sub">Tracked positions</div>
              </div>
              <div class="diag-item">
                <div class="diag-label">SKIP MARKERS</div>
                <div class="diag-val">{{ sysInfo.db_metrics?.skip_markers_count ?? 0 }}</div>
                <div class="diag-sub">Detected / manual timestamps</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Media Storage Breakdown -->
        <div class="storage-panel" v-if="sysInfo?.storage_info && sysInfo.storage_info.total_bytes > 0" style="margin-top:1.5rem">
          <div class="storage-panel-head">
            <div class="storage-panel-title">
              <i class="ph ph-hard-drives"></i>
              <span>Media Storage</span>
            </div>
            <div class="storage-panel-total">
              {{ sysInfo.storage_info.total_size }}
              <span>on disk</span>
            </div>
          </div>

          <div class="storage-tiles">
            <div class="storage-tile" v-for="seg in [
              { name: 'Movies', size: sysInfo.storage_info.movies_size, pct: sysInfo.storage_info.movies_pct, count: sysInfo.media_counts?.movies },
              { name: 'Series', size: sysInfo.storage_info.series_size, pct: sysInfo.storage_info.series_pct, count: sysInfo.media_counts?.series },
              { name: 'Anime',  size: sysInfo.storage_info.anime_size,  pct: sysInfo.storage_info.anime_pct,  count: sysInfo.media_counts?.anime },
            ]" :key="seg.name">
              <i class="ph ph-hard-drive storage-tile-icon"></i>
              <div class="storage-tile-info">
                <div class="storage-tile-name">{{ seg.name }}<template v-if="seg.count != null"> ({{ seg.count }})</template></div>
                <div class="storage-tile-bar">
                  <div class="storage-tile-fill" :style="{ width: seg.pct + '%' }"></div>
                </div>
                <div class="storage-tile-cap">{{ seg.size }} of {{ sysInfo.storage_info.total_size }} — {{ seg.pct }}%</div>
              </div>
            </div>
          </div>

          <!-- Drive health (free space per library drive) -->
          <div v-if="sysInfo.disk_info && sysInfo.disk_info.length" class="drive-health" style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border-subtle)">
            <div class="storage-panel-title" style="margin-bottom:10px">
              <i class="ph ph-hard-drive"></i>
              <span>Drive Health</span>
            </div>
            <div class="drive-health-grid">
              <div class="drive-health-item" v-for="d in sysInfo.disk_info" :key="d.drive">
                <div class="drive-health-name">{{ d.drive }}</div>
                <div class="storage-tile-bar" style="margin:4px 0 5px">
                  <div
                    class="storage-tile-fill"
                    :style="{ width: d.used_pct + '%', background: d.used_pct >= 90 ? '#ef4444' : d.used_pct >= 75 ? '#f59e0b' : '#4cc2ff' }"
                  ></div>
                </div>
                <div class="storage-tile-cap">{{ d.free_gb }} GB free of {{ d.total_gb }} GB</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Keyboard Shortcuts Quick-Reference -->
      <div class="about-section" style="margin-top:2.5rem">
        <div class="about-section-header">
          <i class="ph ph-keyboard" style="color:var(--accent);font-size:1.5rem"></i>
          <span>Player Keyboard Controls Quick-Reference</span>
        </div>

        <div class="hotkey-card-grid">
          <div class="hotkey-item">
            <kbd class="about-kbd">Space</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Play / Pause</div>
              <div class="hotkey-desc">Toggle video playback</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">F</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Fullscreen</div>
              <div class="hotkey-desc">Toggle fullscreen mode</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">M</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Mute</div>
              <div class="hotkey-desc">Toggle audio mute</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">J / L</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Seek ±10s</div>
              <div class="hotkey-desc">Rewind or skip 10 seconds</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">N</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Next Episode</div>
              <div class="hotkey-desc">Advance to next episode</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">[ / ]</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Subtitle Sync</div>
              <div class="hotkey-desc">Adjust delay (±250ms / ±1s)</div>
            </div>
          </div>

          <div class="hotkey-item">
            <kbd class="about-kbd">?</kbd>
            <div class="hotkey-label-wrap">
              <div class="hotkey-title">Shortcuts Modal</div>
              <div class="hotkey-desc">View full hotkeys overlay</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Tech Stack & Credits -->
      <div class="about-section" style="margin-top:2.5rem">
        <div class="about-section-header">
          <i class="ph ph-code" style="color:var(--accent);font-size:1.5rem"></i>
          <span>Built With Modern Open Technologies</span>
        </div>
        <div class="tech-stack-row">
          <div class="tech-badge"><span>⚡ Vue.js 3</span></div>
          <div class="tech-badge"><span>🐍 Python Flask</span></div>
          <div class="tech-badge"><span>🗄️ SQLite3</span></div>
          <div class="tech-badge"><span>🎞️ FFmpeg & FFprobe</span></div>
          <div class="tech-badge"><span>✨ Phosphor Icons</span></div>
          <div class="tech-badge"><span>🎬 TMDb API</span></div>
          <a href="https://github.com/Unknownplanet40/" target="_blank" rel="noopener noreferrer" class="tech-badge" style="text-decoration:none;color:var(--text-primary)">
            <i class="ph ph-github-logo" style="margin-right:4px"></i><span>GitHub @Unknownplanet40</span>
          </a>
        </div>
      </div>

      <!-- Creator & Engineering Credit Card -->
      <div class="about-section" style="margin-top:2.5rem;margin-bottom:3rem">
        <div class="about-section-header">
          <i class="ph ph-crown" style="color:var(--gold);font-size:1.5rem"></i>
          <span>Creator & Engineering</span>
        </div>

        <div class="creator-card">
          <div class="creator-avatar-wrap">
            <img
              v-if="sysInfo?.github_profile?.avatar_url"
              :src="sysInfo.github_profile.avatar_url"
              :alt="sysInfo?.github_profile?.name || 'Creator Avatar'"
              class="creator-avatar-img"
            />
            <span v-else>👨‍💻</span>
          </div>
          <div class="creator-info">
            <div class="creator-name-row">
              <span class="creator-name">{{ sysInfo?.github_profile?.name || '<Caps />' }}</span>
              <span v-if="sysInfo?.github_profile?.location" class="creator-location-badge">
                <i class="ph ph-map-pin"></i> {{ sysInfo.github_profile.location }}
              </span>
              <a
                :href="sysInfo?.github_profile?.html_url || 'https://github.com/Unknownplanet40/'"
                target="_blank"
                rel="noopener noreferrer"
                class="creator-github-link"
                title="Visit GitHub Profile"
              >
                <i class="ph ph-github-logo" style="font-size:1.1rem"></i>
                <span>@{{ sysInfo?.github_profile?.login || 'Unknownplanet40' }}</span>
              </a>
            </div>

            <div class="creator-bio-quote" v-if="sysInfo?.github_profile?.bio">
              "{{ sysInfo.github_profile.bio }}"
            </div>

            <div class="creator-badges-row">
              <span class="creator-stat-pill">📦 <strong>{{ sysInfo?.github_profile?.public_repos || 20 }}</strong> Public Repos</span>
              <span class="creator-stat-pill">👥 <strong>{{ sysInfo?.github_profile?.followers || 13 }}</strong> Followers</span>
              <span class="creator-stat-pill">👤 <strong>{{ sysInfo?.github_profile?.following || 8 }}</strong> Following</span>
              <span class="creator-stat-pill">📅 Member since <strong>{{ sysInfo?.github_profile?.created_year || '2019' }}</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  `,
  setup() {
    const sysInfo = ref(null);
    const loadingSysInfo = ref(true);
    let pollTimer = null;

    const serviceList = [
      { key: "tmdb", label: "TMDB METADATA", sub: "Movie & TV details, posters, cast" },
      { key: "aniskip", label: "ANISKIP", sub: "Intro/outro skip markers" },
      { key: "poster_cache", label: "METADATA CACHE", sub: "Local image & JSON cache" },
    ];

    function serviceColor(status) {
      return { ok: "#10b981", error: "#ef4444", unconfigured: "#f59e0b", disabled: "var(--text-muted)" }[status] || "var(--text-muted)";
    }

    function serviceText(svc, h) {
      if (!h || !h.status) return "Checking…";
      if (h.status === "ok") return h.latency_ms != null ? `${h.latency_ms} ms` : "Operational";
      if (h.status === "error") return "Unreachable";
      if (h.status === "unconfigured") return "Not configured";
      if (h.status === "disabled") return "Disabled";
      return h.status;
    }

    async function fetchSystemInfo() {
      try {
        const data = await API.get("/api/system/info");
        sysInfo.value = data;
        store.serverOnline = true;
      } catch (e) {
        if (store.serverOnline !== false) {
          store.serverOnline = false;
          addToast("⚠️ Server Disconnected — CapsStream backend is unreachable or offline.", "error", 6000);
        }
      } finally {
        loadingSysInfo.value = false;
      }
    }

    onMounted(() => {
      fetchSystemInfo();
      if (!store.profile?.is_kids) {
        pollTimer = setInterval(fetchSystemInfo, 3000);
      }
    });

    onUnmounted(() => {
      if (pollTimer) clearInterval(pollTimer);
    });

    return { sysInfo, loadingSysInfo, store, serviceList, serviceColor, serviceText };
  }
};

// ─── Live Log Viewer Page ─────────────────────────────────────

const LogViewerPage = {
  template: `
    <div class="logs-page">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-secondary btn-sm" @click="$router.back()" title="Go back">
            <i class="ph ph-arrow-left"></i>
          </button>
          <h1 class="page-title" style="margin:0"><i class="ph ph-scroll" style="margin-right:8px"></i>Live Server Log</h1>
        </div>
        <div class="logs-toolbar">
          <select v-model="selectedFile" @change="onFileChange" class="form-input logs-file-select" id="logs-file-select">
            <option v-for="f in files" :key="f.name" :value="f.name">{{ f.name }} ({{ formatSize(f.size) }})</option>
          </select>
          <button class="btn btn-sm" :class="autoRefresh ? 'btn-primary' : 'btn-secondary'" @click="toggleRefresh" id="logs-refresh-toggle" :title="autoRefresh ? 'Pause live tailing' : 'Resume live tailing'">
            <i :class="autoRefresh ? 'ph ph-pause' : 'ph ph-play'" style="margin-right:4px"></i>
            {{ autoRefresh ? 'Live' : 'Paused' }}
          </button>
          <button class="btn btn-secondary btn-sm" @click="clearView" title="Clear the view (log file is untouched)">
            <i class="ph ph-eraser" style="margin-right:4px"></i> Clear View
          </button>
          <a class="btn btn-secondary btn-sm" :href="'/api/system/logs/download?file=' + encodeURIComponent(selectedFile)" v-if="selectedFile">
            <i class="ph ph-download-simple" style="margin-right:4px"></i> Download
          </a>
          <button class="btn btn-sm" style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);color:#fca5a5" @click="stopServer" :disabled="stopping" id="logs-stop-server" title="Stop the CapsStream server">
            <i :class="stopping ? 'ph ph-circle-notch' : 'ph ph-stop'" :style="stopping ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
            {{ stopping ? 'Stopping…' : 'Stop Server' }}
          </button>
        </div>
      </div>

      <div v-if="lastError" class="logs-error-banner">
        <i class="ph ph-warning"></i> {{ lastError }}
      </div>

      <div class="logs-body" ref="logBody" @scroll="onScroll">
        <div v-if="!lines.length" class="logs-empty">
          <i class="ph ph-scroll"></i>
          <div class="logs-empty-title">No log content yet</div>
          <div class="logs-empty-sub">Log files appear under <code>logs/</code> once the server writes output. Launch with the silent launcher or start.bat to populate them.</div>
        </div>
        <div v-else>
          <div v-for="(l, i) in lines" :key="i" class="log-line" :class="lineClass(l)">{{ l || '\u00A0' }}</div>
        </div>
      </div>

      <transition name="fade">
        <button v-if="!atBottom && lines.length" class="logs-jump" @click="scrollToBottom(true)">
          <i class="ph ph-arrow-down"></i> Jump to latest
        </button>
      </transition>
    </div>
  `,
  setup() {
    const files = ref([]);
    const selectedFile = ref("");
    const lines = ref([]);
    const autoRefresh = ref(true);
    const atBottom = ref(true);
    const lastError = ref("");
    const logBody = ref(null);
    let offset = 0;
    let pollTimer = null;

    function formatSize(bytes) {
      if (!bytes) return "0 KB";
      if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
      return Math.max(1, Math.round(bytes / 1024)) + " KB";
    }

    function lineClass(l) {
      const up = l.toUpperCase();
      if (up.includes("ERROR") || up.includes("TRACEBACK") || up.includes("EXCEPTION")) return "log-error";
      if (up.includes("WARNING") || up.includes("WARN")) return "log-warn";
      if (up.includes("[LAUNCHER]") || up.includes("[UPDATER]") || up.includes("[SETTINGS]")) return "log-launcher";
      return "";
    }

    function scrollToBottom(smooth) {
      const el = logBody.value;
      if (!el) return;
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    }

    function isScrolledToBottom() {
      const el = logBody.value;
      if (!el) return true;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    }

    function onScroll() {
      atBottom.value = isScrolledToBottom();
    }

    function clearView() {
      lines.value = [];
      offset = 0;
      pollOnce();
    }

    function onFileChange() {
      lines.value = [];
      offset = 0;
      lastError.value = "";
      pollOnce();
    }

    function toggleRefresh() {
      autoRefresh.value = !autoRefresh.value;
      if (autoRefresh.value) pollOnce();
    }

    const stopping = ref(false);
    async function stopServer() {
      if (stopping.value) return;
      const ok = await customConfirm({
        title: "Stop CapsStream Server",
        message: "Shut down the CapsStream server? The interface will go offline until you launch it again.",
        icon: "ph ph-stop-circle",
        danger: true,
        okText: "Stop Server",
      });
      if (!ok) return;
      stopping.value = true;
      try {
        await API.post("/api/system/shutdown", {});
        addToast("Server shutting down…", "info");
      } catch (e) {
        addToast("Server is stopping…", "info");
      }
    }

    async function pollOnce() {
      if (!selectedFile.value) return;
      try {
        const r = await API.get(`/api/system/logs/tail?file=${encodeURIComponent(selectedFile.value)}&offset=${offset}`);
        lastError.value = "";
        if (r.reset) {
          lines.value = [];
          offset = 0;
        }
        if (r.data) {
          // Measure stickiness fresh from the DOM — never trust stale state
          const stick = isScrolledToBottom();
          const newLines = r.data.split("\n");
          // Drop trailing empty piece from the final newline
          while (newLines.length && newLines[newLines.length - 1] === "") newLines.pop();
          lines.value.push(...newLines);
          offset = r.offset;
          // Keep the log from growing unbounded in memory
          if (lines.value.length > 5000) lines.value.splice(0, lines.value.length - 5000);
          if (stick) {
            await nextTick();
            const el = logBody.value;
            if (el) el.scrollTop = el.scrollHeight;
          }
        }
      } catch (e) {
        lastError.value = "Failed to fetch log: " + (e.message || "unknown error");
      }
    }

    async function loadFiles(pick = true) {
      try {
        const list = await API.get("/api/system/logs");
        files.value = Array.isArray(list) ? list : [];
        if (pick) {
          const currentStillExists = files.value.some((f) => f.name === selectedFile.value);
          if (!currentStillExists) {
            selectedFile.value = files.value[0]?.name || "";
            lines.value = [];
            offset = 0;
          }
        }
      } catch (e) {
        lastError.value = "Failed to list log files: " + (e.message || "unknown error");
      }
    }

    onMounted(async () => {
      if (store.profile?.is_kids) {
        addToast("Server logs are locked in Kids Mode", "warning");
        router.push("/");
        return;
      }
      await loadFiles();
      if (selectedFile.value) await pollOnce();
      pollTimer = setInterval(async () => {
        if (!autoRefresh.value) return;
        await pollOnce();
        // Pick up newly created log files without disturbing the selection
        loadFiles(false);
      }, 2000);
    });

    onUnmounted(() => {
      if (pollTimer) clearInterval(pollTimer);
    });

    return {
      files, selectedFile, lines, autoRefresh, atBottom, lastError, logBody,
      formatSize, lineClass, onScroll, scrollToBottom, clearView, onFileChange, toggleRefresh,
      stopping, stopServer,
    };
  }
};

// ─── Router ───────────────────────────────────────────────────

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", component: HomePage },
    { path: "/setup", component: SetupPage },
    { path: "/profiles", component: ProfilesPage },
    { path: "/browse", component: BrowsePage },
    { path: "/search", component: SearchPage },
    { path: "/title/:type/:id", component: DetailPage },
    { path: "/watch/:id", component: PlayerPage },
    { path: "/collections", component: CollectionsPage },
    { path: "/collection/:id", component: CollectionDetailPage },
    { path: "/favorites", component: FavoritesPage },
    { path: "/stats", component: StatsPage },
    { path: "/settings", component: SettingsPage },
    { path: "/logs", component: LogViewerPage },
    { path: "/about", component: AboutPage },
  ],
  scrollBehavior(to, from, saved) {
    if (to.path === from.path) return null;
    return { top: 0 };
  },
});

// ─── Floating Scan Progress Widget ───────────────────────────

const ScanProgressWidget = {
  template: `
    <div class="scan-floating-widget" v-if="store.scanRunning || showCompleted">
      <!-- Minimized Pill View -->
      <div v-if="isMinimized" class="scan-widget-pill" @click="isMinimized = false" id="scan-widget-pill">
        <div class="scan-widget-pill-text">
          <i :class="phaseIcon" :style="{ animation: store.scanRunning ? 'spin 1s linear infinite' : 'none' }"></i>
          <span v-if="store.scanRunning">{{ phaseLabel }} · {{ store.scanPercent }}% ({{ store.scanCount || 0 }}{{ store.scanTotal ? '/' + store.scanTotal : '' }})</span>
          <span v-else style="color:var(--success)">✅ Scan Complete!</span>
        </div>
        <button class="scan-widget-btn" title="Expand Widget" id="scan-widget-expand-btn">
          <i class="ph ph-caret-up"></i>
        </button>
      </div>

      <!-- Expanded Card View -->
      <div v-else class="scan-widget-card" id="scan-widget-card">
        <div class="scan-widget-header">
          <div class="scan-widget-title">
            <i class="ph ph-popcorn"></i>
            <span>{{ store.scanRunning ? 'Library Scan' : 'Scan Complete!' }}</span>
            <span v-if="store.scanRunning" class="scan-phase-badge" :class="store.scanPhase">
              <i :class="phaseIcon"></i>{{ phaseLabel }}
            </span>
          </div>
          <div class="scan-widget-actions">
            <button class="scan-widget-btn" @click="isMinimized = true" title="Minimize Widget" id="scan-widget-minimize-btn">
              <i class="ph ph-minus"></i>
            </button>
            <button class="scan-widget-btn" @click="dismiss" title="Close" id="scan-widget-close-btn">
              <i class="ph ph-x"></i>
            </button>
          </div>
        </div>

        <div class="scan-widget-progress-row">
          <div class="scan-widget-progress-bg">
            <div
              class="scan-widget-progress-fill"
              :class="{ indeterminate: store.scanRunning && !store.scanPercent }"
              :style="{ width: store.scanRunning ? store.scanPercent + '%' : '100%' }"
            ></div>
          </div>
          <span class="scan-widget-percent" v-if="store.scanRunning">{{ store.scanPercent }}%</span>
        </div>

        <!-- Running: current item details -->
        <template v-if="store.scanRunning">
          <div class="scan-widget-item" v-if="store.scanItem && store.scanItem.file_name">
            <div class="scan-item-top">
              <span class="scan-item-type"><i :class="typeIcon"></i>{{ typeLabel }}</span>
              <span class="scan-item-se" v-if="isEpisode">S{{ pad2(store.scanItem.season) }}E{{ pad2(store.scanItem.episode) }}</span>
            </div>
            <div class="scan-item-title" :title="store.scanItem.title">{{ store.scanItem.title }}</div>
            <div class="scan-item-file" :title="store.scanItem.file_name">
              {{ store.scanItem.file_name }}<span v-if="itemSize"> · {{ itemSize }}</span>
            </div>
            <div class="scan-item-match" v-if="store.scanItem.matched_title">
              <i class="ph ph-check-circle"></i>
              Matched: {{ store.scanItem.matched_title }}<template v-if="store.scanItem.year"> ({{ store.scanItem.year }})</template><template v-if="store.scanItem.rating"> · ★ {{ Number(store.scanItem.rating).toFixed(1) }}</template>
            </div>
            <div class="scan-item-match pending" v-else>
              <i class="ph ph-circle-notch" style="animation:spin 1s linear infinite"></i> Searching TMDb...
            </div>
          </div>

          <div class="scan-widget-status" v-else style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            {{ store.scanProgress || 'Preparing scan...' }}
          </div>

          <div class="scan-widget-footer">
            <span><i class="ph ph-files"></i> {{ store.scanCount || 0 }}/{{ store.scanTotal || '?' }} processed</span>
            <span v-if="store.scanMatched"><i class="ph ph-checks"></i> {{ store.scanMatched }} matched</span>
            <span v-if="store.scanElapsed"><i class="ph ph-timer"></i> {{ fmtElapsed(store.scanElapsed) }}</span>
          </div>
        </template>

        <!-- Completed -->
        <template v-else>
          <div class="scan-widget-status" style="color:var(--text-muted)">
            Processed {{ store.scanCount || 0 }} new media files<template v-if="store.scanMatched"> · {{ store.scanMatched }} matched to TMDb</template>.
          </div>
        </template>
      </div>
    </div>
  `,
  setup() {
    const isMinimized = ref(false);
    const showCompleted = ref(false);

    const phaseLabel = computed(() => {
      if (store.scanPhase === "matching") return "Matching";
      if (store.scanPhase === "scanning") return "Scanning";
      return "Scanning";
    });

    const phaseIcon = computed(() => {
      if (store.scanPhase === "matching") return "ph ph-target";
      return "ph ph-magnifying-glass";
    });

    const typeLabel = computed(() => {
      const t = store.scanItem?.type;
      if (t === "movie") return "Movie";
      if (t === "anime") return "Anime";
      if (t === "series") return "Series";
      return "File";
    });

    const typeIcon = computed(() => {
      const t = store.scanItem?.type;
      if (t === "movie") return "ph ph-film-strip";
      if (t === "anime") return "ph ph-sparkle";
      if (t === "series") return "ph ph-television";
      return "ph ph-file-video";
    });

    const isEpisode = computed(() => {
      const it = store.scanItem;
      return !!it && it.type !== "movie" && it.season != null;
    });

    const itemSize = computed(() => fmtFileSize(store.scanItem?.file_size));

    function pad2(n) {
      return String(n ?? 0).padStart(2, "0");
    }

    function fmtElapsed(sec) {
      sec = Number(sec) || 0;
      if (sec < 60) return `${sec}s`;
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return `${m}m ${pad2(s)}s`;
    }

    watch(
      () => store.scanRunning,
      (running, prev) => {
        if (!running && prev === true) {
          showCompleted.value = true;
          setTimeout(() => {
            showCompleted.value = false;
          }, 4000);
        }
      },
    );

    function dismiss() {
      showCompleted.value = false;
      isMinimized.value = true;
    }

    function fmtFileSize(bytes) {
      bytes = Number(bytes);
      if (!bytes || bytes <= 0) return null;
      const units = ["B", "KB", "MB", "GB", "TB"];
      let i = 0;
      while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
      }
      return `${bytes.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
    }

    return { store, isMinimized, showCompleted, dismiss, phaseLabel, phaseIcon, typeLabel, typeIcon, isEpisode, itemSize, pad2, fmtElapsed };
  },
};



// ─── Root App ─────────────────────────────────────────────────

const App = {
  components: { MediaCard, ScanProgressWidget, ShortcutsModal },
  template: `
    <!-- Loading screen -->
    <div class="loading-screen" v-if="appLoading">
      <div class="loading-logo">
        <img src="/static/img/favicon.png" alt="CapsStream" style="height:48px;width:48px;margin-bottom:12px;display:block;margin-left:auto;margin-right:auto">
        <span>CapsStream</span>
      </div>
      <div class="loading-spinner"></div>
    </div>

    <template v-else>
      <!-- Navbar (hidden on player/profile pages) -->
      <nav class="navbar" :class="{ scrolled: navScrolled }" v-if="showNav" id="navbar">
        <div class="navbar-island">
          <div class="nav-logo" @click="router.push('/')" id="nav-logo">
            <img src="/static/img/favicon.png" alt="CapsStream Logo" class="app-logo-img">
            <span>CapsStream</span>
          </div>

          <div class="nav-links" ref="navLinksRef" @mouseleave="hoveredLinkIndex = null">
            <div
              class="nav-pill-indicator"
              :style="pillStyle"
            ></div>
            <div
              v-for="(item, idx) in navItems"
              :key="item.id"
              class="nav-link"
              :class="{ active: isNavActive(item) }"
              @mouseenter="hoveredLinkIndex = idx"
              @click="router.push(item.path)"
              :id="item.id"
              :ref="el => { if (el) linkRefs[idx] = el }"
            >
              {{ item.name }}
            </div>
          </div>

          <div class="nav-spacer"></div>

          <div class="nav-actions">
            <div class="nav-search-btn" @click="router.push('/search')" id="nav-search" data-tooltip="Search">
              <i class="ph ph-magnifying-glass" style="font-size:1.1rem"></i>
            </div>

            <!-- Shortcuts button -->
            <div class="nav-search-btn" @click="showShortcuts = true" id="nav-shortcuts" data-tooltip="Keyboard Shortcuts (?)">
              <i class="ph ph-keyboard" style="font-size:1.1rem"></i>
            </div>

            <!-- Scan button (hidden for Kids profiles) -->
            <div v-if="!store.profile?.is_kids" class="nav-search-btn" @click="triggerScan" id="nav-scan" data-tooltip="Refresh Library" style="position:relative">
              <i class="ph ph-arrows-clockwise" style="font-size:1.1rem" :style="{ animation: store.scanRunning ? 'spin 1s linear infinite' : 'none' }"></i>
              <div class="scan-badge" v-if="store.scanRunning"></div>
            </div>

            <!-- Settings button (hidden for Kids profiles) -->
            <div v-if="!store.profile?.is_kids" class="nav-search-btn" @click="router.push('/settings')" id="nav-settings" data-tooltip="Settings">
              <i class="ph ph-gear" style="font-size:1.1rem"></i>
            </div>

            <!-- Kids Mode Badge -->
            <div v-if="store.profile?.is_kids" class="kids-mode-nav-badge" id="nav-kids-badge">
              🧒 Kids
            </div>

            <!-- Profile -->
            <div class="nav-profile" @click.stop="toggleProfileMenu" id="nav-profile" data-tooltip="Profile Menu"
              :style="{ background: store.profile?.color + '33' || 'var(--bg-card)' }">
              {{ store.profile?.avatar || '👤' }}
              <div class="profile-dropdown" v-if="showProfileMenu" @click.stop>
                <div v-if="store?.profile" class="profile-dropdown-item" style="font-weight:600;color:var(--text-primary);cursor:default" @click.stop>
                  {{ store.profile?.avatar }} {{ store.profile?.name }}
                  <span v-if="store.profile?.is_kids" style="font-size:0.75rem;color:#fdcb6e;margin-left:4px;">🧒 Kids</span>
                </div>
                <div class="profile-dropdown-divider" v-if="store?.profile"></div>
                <div class="profile-dropdown-item" @click.stop="goFavorites" id="dd-watchlist">❤️ Watchlist</div>
                <div class="profile-dropdown-item" @click.stop="goCollections" id="dd-collections">📚 Collections</div>
                <div class="profile-dropdown-item" @click.stop="goStats" id="dd-stats">📊 Watch Stats</div>
                <div v-if="!store.profile?.is_kids" class="profile-dropdown-item" @click.stop="goSettings" id="dd-settings">⚙️ Settings</div>
                <div class="profile-dropdown-item" @click.stop="goAbout" id="dd-about">ℹ️ About CapsStream</div>
                <div v-if="!store.profile?.is_kids" class="profile-dropdown-item" @click.stop="editCurrentProfile" id="dd-edit-profile">✏️ Edit Profile</div>
                <div v-if="!store.profile?.is_kids" class="profile-dropdown-item" @click.stop="switchProfile" id="dd-switch">👤 Switch Profile</div>
                <div class="profile-dropdown-divider"></div>
                <div class="profile-dropdown-item danger" @click.stop="logout" v-if="store.profile" id="dd-logout">🚪 Sign Out</div>
              </div>
            </div>
          </div>
        </div>
      </nav>

      <!-- Update-available banner -->
      <transition name="fade">
        <div
          class="update-banner"
          v-if="store.updateInfo?.status === 'available' && !updateBannerDismissed && showNav && !store.profile?.is_kids"
        >
          <i class="ph ph-arrow-circle-up"></i>
          <span>
            Update available (v{{ store.updateInfo.latest }}) —
            <a href="#" @click.prevent="store.pendingUpdateCheck = true; router.push('/settings'); updateBannerDismissed = true">go to Settings to install</a>
          </span>
          <button class="update-banner-dismiss" @click="updateBannerDismissed = true" title="Dismiss">
            <i class="ph ph-x"></i>
          </button>
        </div>
      </transition>

      <!-- Main content -->
      <main :style="{ paddingTop: showNav && isPlayerRoute && isDetailRoute ? 'var(--nav-height)' : '0' }">
        <router-view />
      </main>

      <!-- Toast container (Clean Single-Layer Glass Card) -->
      <div class="toast-container" id="toast-container">
        <div
          v-for="toast in store.toasts"
          :key="toast.id"
          class="toast-card"
          :class="toast.type || 'info'"
        >
          <div class="toast-card-header">
            <div class="toast-card-title">
              <i :class="getToastIcon(toast.type)" class="toast-card-icon"></i>
              <span class="toast-card-tag">{{ (toast.type || 'INFO').toUpperCase() }}</span>
            </div>
            <button class="toast-card-dismiss-btn" @click="dismissToast(toast.id)" title="Dismiss">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <div class="toast-progress-track">
            <div class="toast-progress-fill" :class="toast.type || 'info'"></div>
          </div>

          <div class="toast-card-body">
            {{ toast.message }}
          </div>
        </div>
      </div>

      <!-- Trophy Case Achievement Unlocked Popup Banner -->
      <div class="achievement-toast-container" id="achievement-toast-container">
        <div
          v-for="ach in store.achievementQueue"
          :key="ach.id"
          class="achievement-toast-card"
          :class="(ach.rarity || 'gold').toLowerCase()"
        >
          <div class="achievement-toast-inner">
            <div class="achievement-toast-icon-wrap">
              <span class="achievement-toast-icon">{{ ach.icon || '🏆' }}</span>
            </div>
            <div class="achievement-toast-body">
              <div class="achievement-toast-tag">
                <i class="ph-fill ph-trophy" style="color:var(--gold)"></i> ACHIEVEMENT UNLOCKED
              </div>
              <div class="achievement-toast-title" :title="ach.title">{{ ach.title }}</div>
              <div class="achievement-toast-desc">{{ ach.description }}</div>
            </div>
            <div class="achievement-rarity-pill" :class="(ach.rarity || 'gold').toLowerCase()">
              {{ ach.rarity || 'Gold' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Shortcuts Modal -->
      <shortcuts-modal v-if="showShortcuts" @close="showShortcuts = false" />

      <!-- Bottom-Left Floating Scan Progress Widget -->
      <scan-progress-widget />

      <!-- Bedtime Celebration Overlay -->
      <div v-if="store.bedtimeActive" class="bedtime-overlay" @click.stop>
        <div class="bedtime-card" @click.stop>
          <div class="bedtime-moon">🌙 ✨ 💤</div>
          <h2 style="font-size:1.8rem;font-weight:900;color:#fed330;margin-bottom:0.75rem">
            {{ store.bedtimeReason === 'daily_limit' ? 'Daily Cartoon Time Limit Reached!' : 'Bedtime for Tonight!' }}
          </h2>
          <p style="color:var(--text-secondary);font-size:1rem;line-height:1.6;margin-bottom:1.5rem">
            Great job watching today, <strong>{{ store.profile?.name }}</strong>! It's time to rest and recharge for tomorrow's fun adventures.
          </p>
          <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
            <button class="btn btn-primary" style="border-radius:16px;padding:12px 28px;font-size:0.95rem;font-weight:800;background:linear-gradient(135deg,#ff4757,#ff6b81)" @click="handleBedtimeGoodnight">
              Goodnight! 🌟
            </button>
            <button class="btn btn-secondary" style="border-radius:16px;padding:12px 24px;font-size:0.95rem;font-weight:700" @click="handleBedtimeUnlock">
              🛡️ Parent Unlock (+30m)
            </button>
          </div>
        </div>
      </div>

      <!-- Parental Math Challenge Exit Gate Modal (Global from Kids Mode) -->
      <div class="modal-backdrop" v-if="appMathGateShow" @click.self="appMathGateShow = false" style="z-index:9999999;background:rgba(0,0,0,0.88)">
        <div class="modal parental-gate-modal" style="text-align:center;max-width:380px;border-radius:22px;padding:2rem 1.5rem">
          <div class="parental-gate-icon">🛡️</div>
          <h3 style="font-size:1.35rem;font-weight:700;margin:0.5rem 0">Parental Exit Gate</h3>
          <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1.2rem">
            Please solve the math puzzle to exit Kids Mode:
          </p>
          <div class="math-question-badge">
            {{ appMathProblem.num1 }} + {{ appMathProblem.num2 }} = ?
          </div>
          <div class="pin-display" style="justify-content:center;margin:1rem 0">
            <div class="math-answer-display">{{ appMathAnswer || '?' }}</div>
          </div>
          <div class="pin-pad">
            <button v-for="n in [1,2,3,4,5,6,7,8,9,'',0,'⌫']" :key="n"
              class="pin-key"
              :class="{ backspace: n === '⌫' }"
              @click="handleAppMathKey(n)"
              :id="'app-math-key-' + n"
              :disabled="n === ''"
            >{{ n }}</button>
          </div>
          <div class="modal-error" v-if="appMathError" style="margin-top:10px">{{ appMathError }}</div>
          <button class="btn btn-ghost btn-full" style="margin-top:1.25rem;border-radius:12px" @click="appMathGateShow = false">Cancel</button>
        </div>
      </div>

      <!-- Global Custom Confirm Modal -->
      <div v-if="confirmState.show" class="modal-backdrop" style="z-index:999999;background:rgba(0,0,0,0.85);backdrop-filter:blur(20px);" @click.self="handleConfirmCancel">
        <div class="shortcuts-modal-card" style="max-width:460px;border-radius:var(--radius-outer);border:1px solid rgba(255,255,255,0.16);box-shadow:0 24px 60px rgba(0,0,0,0.95)" @click.stop>
          <div class="shortcuts-modal-inner" style="text-align:left">
            <div class="shortcuts-modal-header" style="margin-bottom:1rem;border-bottom:1px solid rgba(255,255,255,0.1)">
              <div class="shortcuts-header-title" style="color:var(--text-primary);display:flex;align-items:center;gap:10px;font-size:1.15rem;font-weight:800">
                <i :class="confirmState.icon || 'ph ph-question'" style="color:var(--accent);font-size:1.4rem"></i>
                <span>{{ confirmState.title || 'Confirmation Required' }}</span>
              </div>
              <button class="shortcuts-close-btn" @click="handleConfirmCancel">
                <i class="ph ph-x"></i>
              </button>
            </div>

            <div style="font-size:0.92rem;color:var(--text-secondary);line-height:1.5;margin-bottom:1.5rem">
              {{ confirmState.message }}
            </div>

            <div style="display:flex;gap:0.75rem;justify-content:flex-end">
              <button class="btn btn-ghost" @click="handleConfirmCancel" id="confirm-modal-cancel-btn">
                {{ confirmState.cancelText || 'Cancel' }}
              </button>
              <button class="btn" :class="confirmState.danger ? 'btn-primary danger' : 'btn-primary'" @click="handleConfirmOk" id="confirm-modal-ok-btn">
                {{ confirmState.okText || 'Confirm' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Global Fix Match Modal -->
      <fix-match-modal
        v-if="fixMatchState.show"
        :target="fixMatchState.target"
        @close="handleGlobalFixMatchClose"
        @matched="handleGlobalFixMatchDone"
      />

      <!-- Floating Global Context Menu -->
      <div
        v-if="contextMenuState.show && contextMenuState.item"
        class="floating-context-menu"
        :style="{ top: contextMenuState.y + 'px', left: contextMenuState.x + 'px' }"
        @click.stop
      >
        <div class="context-menu-header">
          <div class="context-menu-thumb" v-if="contextMenuPoster">
            <img :src="contextMenuPoster" :alt="contextMenuState.item.title" loading="lazy" />
          </div>
          <div v-else class="context-menu-thumb placeholder">
            <i class="ph-fill ph-film-strip"></i>
          </div>
          <div class="context-menu-header-info">
            <div class="context-menu-title" :title="contextMenuState.item.title">
              {{ contextMenuState.item.title }}
            </div>
            <div v-if="contextMenuState.item.season || contextMenuState.item.episode || contextMenuState.item.ep_title" class="context-menu-ep-info">
              <span v-if="contextMenuState.item.season || contextMenuState.item.episode" class="context-menu-ep-code">
                S{{ String(contextMenuState.item.season || 1).padStart(2, '0') }}E{{ String(contextMenuState.item.episode || 1).padStart(2, '0') }}
              </span>
              <span v-if="contextMenuState.item.ep_title" class="context-menu-ep-title" :title="contextMenuState.item.ep_title">
                {{ contextMenuState.item.ep_title }}
              </span>
            </div>
            <div class="context-menu-meta">
              <span v-if="contextMenuState.item.year" class="context-menu-meta-tag">{{ contextMenuState.item.year }}</span>
              <span v-if="contextMenuState.item.type" class="badge" style="text-transform:capitalize;font-size:0.65rem">{{ contextMenuState.item.type }}</span>
              <span v-if="contextMenuState.item.duration" class="context-menu-meta-tag">{{ formatDuration(contextMenuState.item.duration) }}</span>
              <span v-if="contextMenuState.item.rating" class="context-menu-rating" style="color:var(--gold);font-weight:700">★ {{ formatRating(contextMenuState.item.rating) }}</span>
            </div>
            <div v-if="contextMenuState.item.genres" class="context-menu-genres" :title="contextMenuState.item.genres">
              {{ formatGenres(contextMenuState.item.genres, 3) }}
            </div>
          </div>
        </div>

        <div v-if="calcProgressPercent(contextMenuState.item) > 0" class="context-menu-progress-wrap">
          <div class="context-menu-progress-bar">
            <div class="context-menu-progress-fill" :style="{ width: calcProgressPercent(contextMenuState.item) + '%' }"></div>
          </div>
          <div class="context-menu-progress-labels">
            <span>{{ calcProgressPercent(contextMenuState.item) }}% watched</span>
            <span v-if="calcTimeLeft(contextMenuState.item)">{{ calcTimeLeft(contextMenuState.item) }}</span>
          </div>
        </div>

        <div class="context-menu-item" @click="handleContextMenuPlay">
          <i class="ph-fill ph-play"></i>
          <span>{{ contextMenuState.item.position > 0 ? 'Resume Playback' : 'Play Title' }}</span>
        </div>

        <div class="context-menu-item" @click="handleContextMenuDetails">
          <i class="ph ph-info"></i>
          <span>View Details</span>
        </div>

        <div class="context-menu-item" @click="handleContextMenuTrailer">
          <i class="ph ph-film-strip"></i>
          <span>Watch Trailer</span>
        </div>

        <div class="context-menu-divider"></div>

        <div class="context-menu-item" @click="handleContextMenuFav">
          <i :class="contextMenuState.isFavorite ? 'ph-fill ph-heart' : 'ph ph-heart'"></i>
          <span>{{ contextMenuState.isFavorite ? 'Remove from Watchlist' : 'Add to Watchlist' }}</span>
        </div>

        <div v-if="!store.profile?.is_kids" class="context-menu-item" @click="handleContextMenuCollection">
          <i class="ph ph-plus-circle"></i>
          <span>Add to Collection</span>
        </div>

        <div v-if="!store.profile?.is_kids" class="context-menu-item" @click="handleContextMenuFixMatch">
          <i class="ph ph-magic-wand"></i>
          <span>Fix Match</span>
        </div>

        <div v-if="!store.profile?.is_kids && contextMenuState.item.tmdb_id" class="context-menu-item" @click="handleContextKidsOverride('allow')">
          <i class="ph ph-shield-check" style="color:#2ecc71"></i>
          <span>Kids Mode: Always Allow</span>
        </div>

        <div v-if="!store.profile?.is_kids && contextMenuState.item.tmdb_id" class="context-menu-item danger" @click="handleContextKidsOverride('block')">
          <i class="ph ph-shield-warning"></i>
          <span>Kids Mode: Block Title</span>
        </div>

        <template v-if="contextMenuState.item.position > 0">
          <div class="context-menu-divider"></div>
          <div class="context-menu-item danger" @click="handleContextMenuResetProgress">
            <i class="ph ph-x-circle"></i>
            <span>Remove from Continue</span>
          </div>
        </template>

        <template v-if="contextMenuState.item.type !== 'series'">
          <div class="context-menu-item" @click="handleContextMenuMarkWatched">
            <i class="ph ph-check-circle" style="color:#2ecc71"></i>
            <span>Mark as Watched</span>
          </div>
        </template>

        <div v-if="!store.profile?.is_kids" class="context-menu-item danger" @click="handleContextMenuDelete">
          <i class="ph ph-trash"></i>
          <span>Delete from Library</span>
        </div>
      </div>

      <!-- Global Collection Picker Modal -->
      <div
        class="modal-backdrop"
        v-if="collectionPickerState.show"
        style="z-index:999995;background:rgba(0,0,0,0.85);backdrop-filter:blur(20px);"
        @click.self="collectionPickerState.show = false"
      >
        <div class="shortcuts-modal-card" style="max-width:440px" @click.stop>
          <div class="shortcuts-modal-inner" style="text-align:left">
            <div class="shortcuts-modal-header" style="margin-bottom:1rem">
              <div class="shortcuts-header-title" style="color:var(--text-primary);display:flex;align-items:center;gap:10px">
                <i class="ph ph-stack" style="color:var(--accent);font-size:1.4rem"></i>
                <span>Add to Collection</span>
              </div>
              <button class="shortcuts-close-btn" @click="collectionPickerState.show = false">
                <i class="ph ph-x"></i>
              </button>
            </div>

            <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1rem">
              Select a collection for <strong>{{ collectionPickerState.item?.title }}</strong>:
            </div>

            <!-- Create new collection inline -->
            <div style="display:flex;gap:8px;margin-bottom:1.25rem">
              <input
                type="text"
                v-model="collectionPickerState.inlineName"
                class="form-input"
                placeholder="New collection name..."
                @keyup.enter="createAndAddToCollection"
              />
              <button class="btn btn-primary btn-sm" @click="createAndAddToCollection">
                Create
              </button>
            </div>

            <div v-if="collectionPickerState.collections.length === 0" style="text-align:center;padding:1.5rem;color:var(--text-muted);font-size:0.85rem">
              No custom collections yet. Type a name above to create one!
            </div>

            <div v-else style="max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:8px">
              <div
                v-for="col in userCustomCollections"
                :key="col.id"
                class="collection-select-item"
                style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:rgba(255,255,255,0.04);border-radius:10px;cursor:pointer;transition:background 0.2s"
                @click="toggleItemInCollection(col)"
              >
                <div>
                  <div style="font-weight:700;font-size:0.9rem">{{ col.name }}</div>
                  <div style="font-size:0.75rem;color:var(--text-muted)">{{ (col.items || []).length }} titles</div>
                </div>
                <i :class="isItemInCol(col) ? 'ph-fill ph-check-circle' : 'ph ph-circle'" :style="{ color: isItemInCol(col) ? 'var(--accent)' : 'var(--text-muted)', fontSize: '1.3rem' }"></i>
              </div>
            </div>

            <button class="btn btn-ghost btn-full" style="margin-top:1.25rem" @click="collectionPickerState.show = false">
              Done
            </button>
          </div>
        </div>
      </div>

      <!-- Global Trailer Modal -->
      <div
        class="modal-backdrop"
        v-if="globalTrailerState.show"
        style="z-index:999998;background:rgba(0,0,0,0.92);backdrop-filter:blur(24px);"
        @click.self="globalTrailerState.show = false"
      >
        <div class="trailer-modal-content" @click.stop style="width:90vw;max-width:960px;aspect-ratio:16/9;background:#000;border-radius:16px;overflow:hidden;border:1px solid rgba(255,255,255,0.15);box-shadow:0 24px 70px rgba(0,0,0,0.95);position:relative">
          <button class="shortcuts-close-btn" style="position:absolute;top:12px;right:12px;z-index:10;background:rgba(0,0,0,0.7);color:#fff;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center" @click="globalTrailerState.show = false">
            <i class="ph ph-x"></i>
          </button>
          <iframe
            v-if="globalTrailerState.url"
            :src="globalTrailerState.url"
            style="width:100%;height:100%;border:none"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowfullscreen
          ></iframe>
        </div>
      </div>
    </template>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    const navScrolled = ref(false);
    const showProfileMenu = ref(false);
    const showShortcuts = ref(false);
    const appLoading = ref(true);

    watch(
      () => store.profile,
      (prof) => {
        document.body.classList.toggle("kids-mode-theme", !!prof?.is_kids);
        const theme = prof?.theme || localStorage.getItem("capsstream_theme") || "crimson";
        applyTheme(theme, false);
      },
      { immediate: true, deep: true }
    );

    const currentTheme = computed(() => store.profile?.theme || localStorage.getItem("capsstream_theme") || "crimson");

    function selectTheme(themeId) {
      applyTheme(themeId, true);
    }

    // ─── Update banner state ─────────────────────────────────────
    const updateBannerDismissed = ref(false);
    let updateQuietChecked = false;
    async function checkUpdateQuiet() {
      if (updateQuietChecked) return;
      updateQuietChecked = true;
      try {
        const cfg = await API.get("/api/settings");
        if (cfg && cfg.updates && cfg.updates.auto_check === false) return;
      } catch (e) {}
      try {
        const r = await API.get("/api/system/check-update");
        if (r && r.status === "available") store.updateInfo = r;
      } catch (e) {}
    }

    watch(
      () => store.profile,
      (p) => {
        if (p) checkUpdateQuiet();
      }
    );

    function handleGlobalShortcutsKey(e) {
      const tag = (e.target && e.target.tagName) || "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;

      if (appMathGateShow.value) {
        if (/^[0-9]$/.test(e.key)) {
          e.preventDefault();
          handleAppMathKey(Number(e.key));
        } else if (e.key === "Backspace") {
          e.preventDefault();
          handleAppMathKey("⌫");
        } else if (e.key === "Escape") {
          e.preventDefault();
          appMathGateShow.value = false;
        }
        return;
      }

      if (e.key === "?") {
        e.preventDefault();
        showShortcuts.value = !showShortcuts.value;
      }

      if (e.key === "/" && !route.path.startsWith("/search")) {
        e.preventDefault();
        router.push("/search");
      }
    }

    const showNav = computed(() => {
      return !["profiles", "setup"].some((name) => route.path === "/" + name) && !route.path.startsWith("/watch");
    });

    const isPlayerRoute = computed(() => route.path.startsWith("/watch"));
    const isDetailRoute = computed(() => !route.path.startsWith("/title"));

    function isRoute(path) {
      return route.path === path || route.fullPath === path;
    }

    const navItems = computed(() => {
      if (store.profile?.is_kids) {
        return [
          { name: "Home", path: "/", id: "nav-home", isMatch: (r) => r.path === "/" },
          { name: "Shows & Cartoons", path: "/browse?type=series", id: "nav-series", isMatch: (r) => r.fullPath === "/browse?type=series" },
          { name: "Movies", path: "/browse?type=movie", id: "nav-movies", isMatch: (r) => r.fullPath === "/browse?type=movie" },
          { name: "Anime", path: "/browse?type=anime", id: "nav-anime", isMatch: (r) => r.fullPath === "/browse?type=anime" },
          { name: "Stats", path: "/stats", id: "nav-stats", isMatch: (r) => r.path === "/stats" },
          { name: "About", path: "/about", id: "nav-about", isMatch: (r) => r.path === "/about" },
        ];
      }
      return [
        { name: "Home", path: "/", id: "nav-home", isMatch: (r) => r.path === "/" },
        { name: "Movies", path: "/browse?type=movie", id: "nav-movies", isMatch: (r) => r.fullPath === "/browse?type=movie" },
        { name: "Series", path: "/browse?type=series", id: "nav-series", isMatch: (r) => r.fullPath === "/browse?type=series" },
        { name: "Anime", path: "/browse?type=anime", id: "nav-anime", isMatch: (r) => r.fullPath === "/browse?type=anime" },
        { name: "Stats", path: "/stats", id: "nav-stats", isMatch: (r) => r.path === "/stats" },
        { name: "About", path: "/about", id: "nav-about", isMatch: (r) => r.path === "/about" },
      ];
    });

    const navLinksRef = ref(null);
    const linkRefs = ref([]);
    const hoveredLinkIndex = ref(null);
    const pillStyle = ref({ opacity: 0, transform: "translateX(0px)", width: "0px" });

    function isNavActive(item) {
      return item.isMatch(route);
    }

    function updatePillPosition() {
      nextTick(() => {
        let targetIdx = hoveredLinkIndex.value;
        if (targetIdx === null || targetIdx === undefined) {
          targetIdx = navItems.value.findIndex((item) => isNavActive(item));
        }

        if (targetIdx >= 0 && linkRefs.value[targetIdx]) {
          const el = linkRefs.value[targetIdx];
          pillStyle.value = {
            opacity: 1,
            transform: `translateX(${el.offsetLeft}px)`,
            width: `${el.offsetWidth}px`,
          };
        } else {
          pillStyle.value = { opacity: 0, transform: "translateX(0px)", width: "0px" };
        }
      });
    }

    watch([() => route.fullPath, hoveredLinkIndex, navItems], () => {
      updatePillPosition();
    });

    function toggleProfileMenu() {
      showProfileMenu.value = !showProfileMenu.value;
    }

    function goFavorites() {
      showProfileMenu.value = false;
      router.push("/favorites");
    }

    function goCollections() {
      showProfileMenu.value = false;
      router.push("/collections");
    }

    function goSettings() {
      showProfileMenu.value = false;
      router.push("/settings");
    }

    function goAbout() {
      showProfileMenu.value = false;
      router.push("/about");
    }

    function promptSleepTimer() {
      showProfileMenu.value = false;
      const options = [0, 15, 30, 45, 60, 90];
      const curr = store.sleepTimerMinutes || 0;
      const nextIdx = (options.findIndex((o) => o >= curr && curr > 0) + 1) % options.length;
      const nextVal = options[nextIdx];
      setSleepTimer(nextVal);
    }

    const appMathGateShow = ref(false);
    const appMathAnswer = ref("");
    const appMathError = ref("");
    const appMathProblem = reactive({ num1: 7, num2: 8, answer: 15 });
    let appMathCallback = null;

    function generateAppMathProblem(cb) {
      const n1 = Math.floor(Math.random() * 8) + 4;
      const n2 = Math.floor(Math.random() * 8) + 3;
      appMathProblem.num1 = n1;
      appMathProblem.num2 = n2;
      appMathProblem.answer = n1 + n2;
      appMathAnswer.value = "";
      appMathError.value = "";
      appMathCallback = cb;
      appMathGateShow.value = true;
    }

    function handleAppMathKey(key) {
      appMathError.value = "";
      if (key === "⌫") {
        appMathAnswer.value = appMathAnswer.value.slice(0, -1);
        return;
      }
      if (key === "") return;
      if (appMathAnswer.value.length >= 3) return;
      appMathAnswer.value += key.toString();

      if (Number(appMathAnswer.value) === appMathProblem.answer) {
        appMathGateShow.value = false;
        if (typeof appMathCallback === "function") {
          appMathCallback();
        }
      } else if (appMathAnswer.value.length >= String(appMathProblem.answer).length) {
        appMathError.value = "Incorrect. Try again!";
        setTimeout(() => {
          const n1 = Math.floor(Math.random() * 8) + 4;
          const n2 = Math.floor(Math.random() * 8) + 3;
          appMathProblem.num1 = n1;
          appMathProblem.num2 = n2;
          appMathProblem.answer = n1 + n2;
          appMathAnswer.value = "";
        }, 900);
      }
    }

    function switchProfile() {
      showProfileMenu.value = false;
      if (store.profile?.is_kids) {
        generateAppMathProblem(() => {
          store.profile = null;
          router.push("/profiles");
          API.post("/api/profiles/logout", {}).catch(() => {});
        });
        return;
      }
      store.profile = null;
      router.push("/profiles");
      API.post("/api/profiles/logout", {}).catch(() => {});
    }

    function logout() {
      showProfileMenu.value = false;
      if (store.profile?.is_kids) {
        generateAppMathProblem(() => {
          store.profile = null;
          router.push("/profiles");
          API.post("/api/profiles/logout", {}).catch(() => {});
        });
        return;
      }
      store.profile = null;
      router.push("/profiles");
      API.post("/api/profiles/logout", {}).catch(() => {});
    }

    function handleBedtimeGoodnight() {
      store.bedtimeActive = false;
      store.profile = null;
      router.push("/profiles");
      API.post("/api/profiles/logout", {}).catch(() => {});
    }

    function handleBedtimeUnlock() {
      generateAppMathProblem(() => {
        store.bedtimeActive = false;
        store.dailyLimitExtended = true;
        store.bedtimeDismissedForToday = true;
        addToast("Parent Unlock Verified! +30 minutes of cartoon time granted 🛡️", "success", 5000);
      });
    }

    let screenTimeWatchdog = null;
    function startScreenTimeWatchdog() {
      if (screenTimeWatchdog) clearInterval(screenTimeWatchdog);
      screenTimeWatchdog = setInterval(() => {
        if (!store.profile || !store.profile.is_kids) return;
        const now = new Date();
        const currentMinutes = now.getHours() * 60 + now.getMinutes();

        // 1. Bedtime Curfew Check
        if (store.profile.bedtime_curfew) {
          const [curfH, curfM] = store.profile.bedtime_curfew.split(":").map(Number);
          const curfewMinutes = curfH * 60 + curfM;
          const diff = curfewMinutes - currentMinutes;

          if (diff === 5 && !store.bedtimeWarned) {
            store.bedtimeWarned = true;
            addToast("⏰ 5 minutes of cartoon time left before bedtime! 🌙", "warning", 7000);
          }

          if (currentMinutes >= curfewMinutes && currentMinutes < curfewMinutes + 360) {
            if (!store.bedtimeActive && !store.bedtimeDismissedForToday) {
              store.bedtimeActive = true;
              store.bedtimeReason = "curfew";
              const v = document.querySelector("video");
              if (v) v.pause();
            }
          }
        }

        // 2. Daily Watch Limit Check
        if (store.profile.daily_limit_minutes > 0) {
          const v = document.querySelector("video");
          if (v && !v.paused) {
            store.todayWatchSeconds = (store.todayWatchSeconds || 0) + 10;
          }
          const todayMins = Math.floor((store.todayWatchSeconds || 0) / 60);
          const remainingMins = store.profile.daily_limit_minutes - todayMins;

          if (remainingMins === 5 && !store.dailyLimitWarned) {
            store.dailyLimitWarned = true;
            addToast("⏰ 5 minutes of cartoon time remaining for today! 🌟", "warning", 7000);
          }

          if (todayMins >= store.profile.daily_limit_minutes) {
            if (!store.bedtimeActive && !store.dailyLimitExtended) {
              store.bedtimeActive = true;
              store.bedtimeReason = "daily_limit";
              if (v) v.pause();
            }
          }
        }
      }, 10000);
    }

    async function triggerScan() {
      try {
        unlockAchievement("scan_master");
        await API.post("/api/scan", {});
        store.scanRunning = true;
        pollScanStatus();
      } catch (e) {
        if (e.message.includes("409")) {
          addToast("Scan already in progress", "info");
        }
      }
    }

    // Close profile menu and floating context menu on outside click
    function handleOutsideClick(e) {
      if (!e.target.closest("#nav-profile")) {
        showProfileMenu.value = false;
      }
      if (contextMenuState.show) {
        const menuEl = e.target.closest(".floating-context-menu");
        const menuBtn = e.target.closest(".card-menu-btn");
        if (!menuEl && !menuBtn) {
          closeGlobalContextMenu();
        }
      }
    }

    function handleGlobalKeyDown(e) {
      if (e.key === "Escape") {
        if (contextMenuState.show) closeGlobalContextMenu();
        if (collectionPickerState.show) collectionPickerState.show = false;
        if (globalTrailerState.show) globalTrailerState.show = false;
      }
      handleGlobalShortcutsKey(e);
    }

    // Dynamic tooltip direction & alignment calculator
    function handleTooltipMouseOver(e) {
      const target = e.target.closest("[data-tooltip]");
      if (!target) return;
      const rect = target.getBoundingClientRect();
      if (rect.top < 70) {
        target.setAttribute("data-tooltip-pos", "bottom");
      } else if (window.innerHeight - rect.bottom < 70) {
        target.setAttribute("data-tooltip-pos", "top");
      } else {
        target.setAttribute("data-tooltip-pos", "bottom");
      }

      if (window.innerWidth - rect.right < 110) {
        target.setAttribute("data-tooltip-align", "right");
      } else if (rect.left < 110) {
        target.setAttribute("data-tooltip-align", "left");
      } else {
        target.removeAttribute("data-tooltip-align");
      }
    }

    onMounted(async () => {
      window.addEventListener("mouseover", handleTooltipMouseOver);
      window.addEventListener("keydown", handleGlobalKeyDown);

      try {
        // Restore a persisted session (survives page refresh) before anything else
        const me = await API.get("/api/profiles/me").catch(() => null);
        const profiles = await API.get("/api/profiles");
        if (!profiles || profiles.length === 0) {
          store.profile = null;
          router.push("/setup");
        } else if (me && me.id) {
          // Session still valid — keep the user logged in on their current page
          store.profile = me;
          const path = router.currentRoute.value.path;
          if (path === "/profiles") {
            router.push("/");
          }
        } else {
          // No session — show the "Who's Watching?" screen (never force logout server-side)
          store.profile = null;
          router.push("/profiles");
        }
      } catch (e) {
        router.push("/profiles");
      } finally {
        appLoading.value = false;
      }

      window.addEventListener("scroll", () => {
        navScrolled.value = window.scrollY > 20;
        if (contextMenuState.show) closeGlobalContextMenu();
      }, { passive: true });

      window.addEventListener("resize", () => {
        if (contextMenuState.show) closeGlobalContextMenu();
      }, { passive: true });

      window.addEventListener("click", handleOutsideClick);

      startScreenTimeWatchdog();

      // Poll if scan is running
      try {
        const status = await API.get("/api/scan/status");
        if (status.running) {
          store.scanRunning = true;
          pollScanStatus();
        }
      } catch (e) {
        /* ignore */
      }
    });

    onUnmounted(() => {
      window.removeEventListener("click", handleOutsideClick);
      window.removeEventListener("mouseover", handleTooltipMouseOver);
      window.removeEventListener("keydown", handleGlobalKeyDown);
      clearInterval(scanPollTimer);
    });

    function editCurrentProfile() {
      showProfileMenu.value = false;
      const targetId = store.profile?.id;
      if (targetId) {
        router.push({ path: "/profiles", query: { manage: "true", edit_id: targetId, t: Date.now() } });
      } else {
        router.push({ path: "/profiles", query: { manage: "true", t: Date.now() } });
      }
    }

    function goStats() {
      showProfileMenu.value = false;
      router.push("/stats");
    }

    function dismissToast(id) {
      store.toasts = store.toasts.filter((t) => t.id !== id);
    }

    function getToastIcon(type) {
      if (type === "success") return "ph ph-check-circle";
      if (type === "error") return "ph ph-warning-octagon";
      if (type === "warning") return "ph ph-warning";
      return "ph ph-info";
    }

    // ─── Global Context Menu Action Handlers ──────────────────
    function handleContextMenuPlay() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      if (item.is_mounted === false) {
        addToast("Source drive not mounted. Please connect drive to watch this title.", "error");
        return;
      }
      if (item.type === "movie" && item.id) {
        router.push(`/watch/${item.id}`);
      } else if (item.position > 0 && item.id) {
        router.push(`/watch/${item.id}`);
      } else if (item.type === "movie") {
        router.push(`/title/movie/${item.id || item.tmdb_id}`);
      } else {
        router.push(`/title/${item.type || "series"}/${item.tmdb_id || item.id}`);
      }
    }

    function handleContextMenuDetails() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      if (item.type === "movie" && item.id) {
        router.push(`/title/movie/${item.id}`);
      } else {
        router.push(`/title/${item.type || "series"}/${item.tmdb_id || item.id}`);
      }
    }

    function handleContextMenuTrailer() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      openGlobalTrailer(item);
    }

    async function handleContextMenuFav() {
      const item = contextMenuState.item;
      if (!item) return;
      const idToFav = item.id || item.tmdb_id;
      if (!idToFav) return;
      try {
        const res = await API.post("/api/favorites/toggle", { media_id: idToFav });
        item.is_favorite = res.is_favorite;
        contextMenuState.isFavorite = res.is_favorite;
        addToast(res.is_favorite ? "Added to Watchlist ❤️" : "Removed from Watchlist", "info");
      } catch (e) {
        addToast("Failed to update watchlist", "error");
      }
      closeGlobalContextMenu();
    }

    function handleContextMenuCollection() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      openGlobalCollectionPicker(item);
    }

    function handleContextMenuFixMatch() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      openGlobalFixMatch(item, () => {
        if (route.path === "/") {
          location.reload();
        }
      });
    }

    async function handleContextMenuMarkWatched() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item || !item.id) return;
      try {
        await API.post("/api/progress/mark-watched", { media_id: item.id });
        addToast(`✅ Marked "${item.title}" as watched`, "success");
        if (route.path === "/") {
          location.reload();
        }
      } catch (e) {
        addToast("Failed to mark as watched", "error");
      }
    }

    async function handleContextMenuDelete() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item) return;
      const label = item.title || "this title";
      const scope = (item.type === "movie") ? `"${label}"` : `all ${label} episodes`;
      if (!confirm(
        `Remove ${scope} from the CapsStream library?\n\n` +
        "Your video files on disk are NOT deleted — this only removes the title from the app. " +
        "Watch progress and watchlist entries for it will be lost."
      )) return;
      try {
        const r = await API.post("/api/library/delete", {
          tmdb_id: item.tmdb_id,
          type: item.type,
          media_id: item.id,
        });
        addToast(`🗑️ Removed "${label}" from the library (${r.removed ?? 0} entries)`, "success");
        if (route.path === "/") {
          location.reload();
        }
      } catch (e) {
        addToast(e.message || "Failed to delete", "error");
      }
    }

    async function handleContextKidsOverride(action) {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item || !item.tmdb_id) return;
      try {
        await API.post("/api/kids-overrides", { tmdb_id: item.tmdb_id, action });
        addToast(
          action === "allow"
            ? `Kids Mode: "${item.title}" will always be shown`
            : `Kids Mode: "${item.title}" is now blocked`,
          "success"
        );
      } catch (e) {
        addToast("Failed to save Kids Mode override", "error");
      }
    }

    async function handleContextMenuResetProgress() {
      const item = contextMenuState.item;
      closeGlobalContextMenu();
      if (!item || !item.id) return;
      try {
        await API.del(`/api/progress/${item.id}`);
        item.position = 0;
        item.duration = 0;
        addToast("Progress reset for " + item.title, "info");
        if (route.path === "/") {
          location.reload();
        }
      } catch (e) {
        addToast("Failed to reset progress", "error");
      }
    }

    // ─── Global Collection Picker Helpers ──────────────────────
    const userCustomCollections = computed(() => {
      return (collectionPickerState.collections || []).filter((c) => !c.smart && !c.universe);
    });

    function isItemInCol(col) {
      if (!collectionPickerState.item) return false;
      const mediaId = collectionPickerState.item.id || collectionPickerState.item.tmdb_id;
      return (col.items || []).some((i) => i.id === mediaId || i.tmdb_id === mediaId);
    }

    async function toggleItemInCollection(col) {
      if (!collectionPickerState.item) return;
      const mediaId = collectionPickerState.item.id || collectionPickerState.item.tmdb_id;
      if (!mediaId) return;
      const alreadyIn = isItemInCol(col);
      try {
        if (alreadyIn) {
          await API.del(`/api/collections/${col.id}/items/${mediaId}`);
          col.items = (col.items || []).filter((i) => i.id !== mediaId && i.tmdb_id !== mediaId);
          addToast(`Removed from "${col.name}"`, "info");
        } else {
          await API.post(`/api/collections/${col.id}/items`, { media_id: mediaId });
          if (!col.items) col.items = [];
          col.items.push({ id: mediaId, tmdb_id: collectionPickerState.item.tmdb_id });
          addToast(`Added to "${col.name}" ✓`, "success");
        }
      } catch (e) {
        addToast("Failed to update collection", "error");
      }
    }

    async function createAndAddToCollection() {
      const name = collectionPickerState.inlineName.trim();
      if (!name) return;
      try {
        const col = await API.post("/api/collections", { name });
        col.items = [];
        collectionPickerState.collections.unshift(col);
        collectionPickerState.inlineName = "";
        await toggleItemInCollection(col);
      } catch (e) {
        addToast("Failed to create collection", "error");
      }
    }

    function handleGlobalFixMatchClose() {
      fixMatchState.show = false;
    }

    function handleGlobalFixMatchDone(result) {
      fixMatchState.show = false;
      if (typeof fixMatchState.onMatched === "function") {
        fixMatchState.onMatched(result);
      }
    }

    const contextMenuPoster = computed(() => {
      const item = contextMenuState.item;
      if (!item) return null;
      if (item.poster_path) return imgUrl(item.poster_path);
      if (item.backdrop_path) return imgUrl(item.backdrop_path);
      if (item.still_path) return imgUrl(item.still_path);
      return null;
    });

    return {
      store,
      route,
      navScrolled,
      showProfileMenu,
      showShortcuts,
      appLoading,
      showNav,
      updateBannerDismissed,
      isPlayerRoute,
      isDetailRoute,
      isRoute,
      router,
      toggleProfileMenu,
      goFavorites,
      goCollections,
      goStats,
      goSettings,
      goAbout,
      editCurrentProfile,
      switchProfile,
      logout,
      handleBedtimeGoodnight,
      handleBedtimeUnlock,
      triggerScan,
      appMathGateShow,
      appMathProblem,
      appMathAnswer,
      appMathError,
      handleAppMathKey,
      confirmState,
      handleConfirmOk,
      handleConfirmCancel,
      fixMatchState,
      handleGlobalFixMatchClose,
      handleGlobalFixMatchDone,
      contextMenuState,
      contextMenuPoster,
      handleContextMenuPlay,
      handleContextMenuDetails,
      handleContextMenuTrailer,
      handleContextMenuFav,
      handleContextMenuCollection,
      handleContextMenuFixMatch,
      handleContextKidsOverride,
      handleContextMenuMarkWatched,
      handleContextMenuDelete,
      handleContextMenuResetProgress,
      collectionPickerState,
      globalTrailerState,
      userCustomCollections,
      isItemInCol,
      toggleItemInCollection,
      createAndAddToCollection,
      formatRating,
      formatDuration,
      formatGenres,
      calcProgressPercent,
      calcTimeLeft,
      imgUrl,
      dismissToast,
      getToastIcon,
      navItems,
      navLinksRef,
      linkRefs,
      hoveredLinkIndex,
      pillStyle,
      isNavActive,
      THEME_PRESETS,
      currentTheme,
      selectTheme,
    };
  },
};

// ─── Fix Match Modal Component ─────────────────────────────────

const FixMatchModal = {
  props: ["target"],
  emits: ["close", "matched"],
  template: `
    <div class="modal-backdrop" style="z-index:999950;background:rgba(0,0,0,0.85);backdrop-filter:blur(20px);" @click.self="$emit('close')">
      <div class="fixmatch-modal" @click.stop>
        <div class="fixmatch-header">
          <div class="fixmatch-header-title">
            <i class="ph ph-magic-wand" style="color:var(--accent);font-size:1.4rem"></i>
            <span>Fix Match & Metadata Scraper</span>
          </div>
          <button class="shortcuts-close-btn" @click="$emit('close')">
            <i class="ph ph-x"></i>
          </button>
        </div>

        <div class="fixmatch-body">
          <div class="fixmatch-target-banner">
            <div style="font-size:0.75rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px">TARGET ITEM</div>
            <div style="font-weight:700;font-size:1rem;color:var(--text-primary)">
              {{ target?.title || 'Unknown Media' }}
              <span v-if="target?.year" style="color:var(--text-muted);font-weight:normal"> ({{ target.year }})</span>
              <span v-if="target?.type" class="badge" style="margin-left:6px;text-transform:capitalize;font-size:0.72rem">{{ target.type }}</span>
            </div>
            <div v-if="target?.file_path" class="unmatched-path-cell" style="display:block;margin-top:4px;max-width:100%;font-size:0.78rem">
              {{ target.file_path }}
            </div>
          </div>

          <!-- Search controls -->
          <div class="fixmatch-search-controls">
            <input
              type="text"
              v-model="searchQuery"
              class="form-input"
              placeholder="Search title on TMDb..."
              @keyup.enter="search"
              id="fixmatch-query-input"
              autofocus
            />
            <select v-model="selectedType" class="fixmatch-type-select" @change="search" id="fixmatch-type-select">
              <option value="movie">Movie</option>
              <option value="series">Series</option>
              <option value="anime">Anime</option>
            </select>
            <input
              type="text"
              v-model="searchYear"
              class="fixmatch-year-input"
              placeholder="Year (opt)"
              maxlength="4"
              @keyup.enter="search"
              id="fixmatch-year-input"
            />
            <button class="btn btn-primary" @click="search" :disabled="searching" id="fixmatch-search-btn">
              <i :class="searching ? 'ph ph-circle-notch' : 'ph ph-magnifying-glass'" :style="searching ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
              {{ searching ? 'Searching...' : 'Search' }}
            </button>
          </div>

          <!-- Direct TMDB ID Quick Override -->
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 14px;background:rgba(255,255,255,0.03);border-radius:10px;border:1px solid var(--border);flex-wrap:wrap">
            <span style="font-size:0.8rem;color:var(--text-muted);font-weight:600">Already know the TMDb ID?</span>
            <div style="display:flex;gap:8px;align-items:center">
              <input
                type="number"
                v-model.number="directTmdbId"
                class="form-input"
                placeholder="e.g. 299536"
                style="width:140px;padding:4px 8px;height:32px;font-size:0.85rem"
                @keyup.enter="applyDirectId"
              />
              <button
                class="btn btn-secondary btn-sm"
                @click="applyDirectId"
                :disabled="!directTmdbId || applying"
              >
                Apply ID
              </button>
            </div>
          </div>

          <!-- Loading state -->
          <div v-if="searching" style="display:flex;justify-content:center;padding:2.5rem">
            <div class="loading-spinner"></div>
          </div>

          <!-- Results List -->
          <div v-else-if="results.length > 0" class="fixmatch-results-list">
            <div
              v-for="item in results"
              :key="item.tmdb_id"
              class="fixmatch-card"
            >
              <img
                v-if="item.poster_path"
                :src="item.poster_path"
                class="fixmatch-card-poster"
                :alt="item.title"
                loading="lazy"
                @error="e => e.target.style.display='none'"
              />
              <div v-else class="fixmatch-card-poster" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);background:rgba(255,255,255,0.04)">
                <i class="ph ph-film-strip" style="font-size:1.5rem"></i>
              </div>

              <div class="fixmatch-card-info">
                <div class="fixmatch-card-title">
                  <span>{{ item.title }}</span>
                  <span class="fixmatch-card-year" v-if="item.year">({{ item.year }})</span>
                  <span class="fixmatch-id-badge">TMDb {{ item.tmdb_id }}</span>
                  <span v-if="item.vote_average" class="fixmatch-card-rating">
                    <i class="ph-fill ph-star"></i> {{ Number(item.vote_average).toFixed(1) }}
                  </span>
                </div>
                <div v-if="item.original_title && item.original_title !== item.title" style="font-size:0.75rem;color:var(--text-muted);font-style:italic">
                  Original: {{ item.original_title }}
                </div>
                <div class="fixmatch-card-overview" :title="item.overview">{{ item.overview || 'No overview available.' }}</div>
              </div>

              <button
                class="btn btn-primary btn-sm"
                @click="applyMatch(item)"
                :disabled="applying"
                :id="'btn-apply-match-' + item.tmdb_id"
              >
                <i :class="applyingId === item.tmdb_id ? 'ph ph-circle-notch' : 'ph ph-check'" :style="applyingId === item.tmdb_id ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
                {{ applyingId === item.tmdb_id ? 'Matching…' : 'Match' }}
              </button>
            </div>
          </div>

          <!-- Empty search results -->
          <div v-else-if="searched" style="text-align:center;padding:2.5rem 1rem;color:var(--text-muted)">
            <i class="ph ph-magnifying-glass" style="font-size:2.5rem;margin-bottom:8px"></i>
            <div style="font-weight:700;font-size:1.05rem;color:var(--text-secondary)">No TMDb results found</div>
            <div style="font-size:0.85rem;margin-top:4px">Try adjusting the query keywords, year, or media type.</div>
          </div>
        </div>
      </div>
    </div>
  `,
  setup(props, { emit }) {
    const searchQuery = ref("");
    const selectedType = ref("movie");
    const searchYear = ref("");
    const directTmdbId = ref(null);
    const results = ref([]);
    const searching = ref(false);
    const searched = ref(false);
    const applying = ref(false);
    const applyingId = ref(null);

    onMounted(() => {
      if (props.target) {
        let cleanTitle = props.target.title || "";
        if (!cleanTitle && props.target.file_path) {
          const parts = props.target.file_path.replace(/\\\\/g, "/").split("/");
          cleanTitle = parts[parts.length - 1].replace(/\\.[^/.]+$/, "");
        }
        searchQuery.value = cleanTitle;
        selectedType.value = props.target.type || "movie";
        searchYear.value = props.target.year ? String(props.target.year) : "";
        if (searchQuery.value.trim()) {
          search();
        }
      }
    });

    async function search() {
      if (!searchQuery.value.trim()) return;
      searching.value = true;
      searched.value = true;
      try {
        const queryParams = new URLSearchParams({
          query: searchQuery.value.trim(),
          type: selectedType.value,
          year: searchYear.value.trim()
        });
        const res = await API.get(`/api/tmdb/search?${queryParams.toString()}`);
        results.value = res || [];
      } catch (e) {
        addToast("Failed to search TMDb", "error");
      } finally {
        searching.value = false;
      }
    }

    function applyDirectId() {
      if (!directTmdbId.value) return;
      applyMatch({
        tmdb_id: directTmdbId.value,
        title: `Direct TMDb #${directTmdbId.value}`
      });
    }

    async function applyMatch(item) {
      if (!item.tmdb_id) return;
      applying.value = true;
      applyingId.value = item.tmdb_id;
      try {
        const payload = {
          media_id: props.target?.id,
          old_tmdb_id: props.target?.tmdb_id,
          tmdb_id: item.tmdb_id,
          type: selectedType.value
        };
        const res = await API.post("/api/override", payload);
        addToast(`Matched "${item.title}" successfully! Updated ${res.updated || 1} entries.`, "success");
        emit("matched", { ...item, type: selectedType.value });
        emit("close");
      } catch (e) {
        addToast(e.message || "Failed to apply match", "error");
      } finally {
        applying.value = false;
        applyingId.value = null;
      }
    }

    return {
      searchQuery,
      selectedType,
      searchYear,
      directTmdbId,
      results,
      searching,
      searched,
      applying,
      applyingId,
      search,
      applyDirectId,
      applyMatch
    };
  }
};

// ─── Skip Timestamps Modal Component ───────────────────────────

function formatSecToTime(seconds) {
  if (!seconds || isNaN(seconds) || seconds < 0) return "00:00";
  const s = Math.floor(seconds);
  const m = Math.floor(s / 60);
  const rs = s % 60;
  return `${m.toString().padStart(2, '0')}:${rs.toString().padStart(2, '0')}`;
}

function parseTimeToSec(timeStr) {
  if (!timeStr) return 0;
  if (typeof timeStr === "number") return Math.floor(timeStr);
  const str = String(timeStr).trim();
  if (str.includes(":")) {
    const parts = str.split(":");
    if (parts.length === 2) {
      return (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
    } else if (parts.length === 3) {
      return (parseInt(parts[0], 10) || 0) * 3600 + (parseInt(parts[1], 10) || 0) * 60 + (parseInt(parts[2], 10) || 0);
    }
  }
  return parseInt(str, 10) || 0;
}

const SkipTimestampsModal = {
  props: ["media", "currentTime", "inPlayer"],
  emits: ["close", "saved"],
  template: `
    <div class="modal-backdrop" style="z-index:999900;background:rgba(0,0,0,0.85);backdrop-filter:blur(20px);" @click.self="$emit('close')">
      <div class="shortcuts-modal-card" style="max-width:520px" @click.stop>
        <div class="shortcuts-modal-inner" style="text-align:left">
          <div class="shortcuts-modal-header" style="margin-bottom:1.25rem">
            <div class="shortcuts-header-title" style="color:var(--text-primary);display:flex;align-items:center;gap:10px">
              <i class="ph ph-timer" style="color:var(--accent);font-size:1.5rem"></i>
              <span>Edit Skip Timestamps</span>
            </div>
            <button class="shortcuts-close-btn" @click="$emit('close')">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:1.25rem;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">
            <span>Configure manual skip ranges for <strong>{{ media?.title }}</strong>. Timestamps can be entered as <code>MM:SS</code> or seconds.</span>
            <button
              class="btn btn-secondary btn-sm"
              @click="refreshMarkers(true)"
              :disabled="loadingMarkers"
              id="btn-check-online-markers"
              title="Re-query AniSkip and re-run detection for this episode"
            >
              <i :class="loadingMarkers ? 'ph ph-circle-notch' : 'ph ph-cloud-arrow-down'" :style="loadingMarkers ? 'animation:spin 1s linear infinite' : ''" style="margin-right:4px"></i>
              {{ loadingMarkers ? 'Checking…' : 'Check Online' }}
            </button>
          </div>

          <div style="display:flex;flex-direction:column;gap:1.25rem;margin-bottom:1.5rem">
            <!-- 1. Recap Section -->
            <div class="skip-timestamp-group">
                <div style="font-size:0.88rem;font-weight:700;color:var(--accent);margin-bottom:2px;display:flex;align-items:center;gap:6px">
                  <i class="ph ph-rewind"></i> Recap
                  <span style="font-weight:600;color:var(--text-muted);font-size:0.65rem;text-transform:none">max 5 min</span>
                  <span v-if="sourceInfo.recap" class="skip-src-badge" title="Auto-detected values prefilled below — saving adopts them as manual markers">{{ sourceInfo.recap }}</span>
                </div>
              <div class="skip-seg-desc">"Previously on…" catch-up before the episode proper starts.</div>
              <label style="display:flex;align-items:center;gap:7px;margin:4px 0 6px;font-size:0.72rem;color:var(--text-muted);cursor:pointer">
                <input type="checkbox" v-model="noneChecked.recap" @change="onNoneToggle('recap')" />
                No recap this week — save as confirmed none
              </label>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <div>
                  <label class="form-label" style="font-size:0.75rem">Start Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.recap_start" class="form-input" placeholder="00:00" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('recap_start')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
                <div>
                  <label class="form-label" style="font-size:0.75rem">End Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.recap_end" class="form-input" placeholder="01:30" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('recap_end')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 2. Intro Section -->
            <div class="skip-timestamp-group">
                <div style="font-size:0.88rem;font-weight:700;color:#38bdf8;margin-bottom:2px;display:flex;align-items:center;gap:6px">
                  <i class="ph ph-fast-forward"></i> Intro
                  <span style="font-weight:600;color:var(--text-muted);font-size:0.65rem;text-transform:none">max 5 min</span>
                  <span v-if="sourceInfo.intro" class="skip-src-badge" title="Auto-detected values prefilled below — saving adopts them as manual markers">{{ sourceInfo.intro }}</span>
                </div>
              <div class="skip-seg-desc">Opening titles / theme song.</div>
              <label style="display:flex;align-items:center;gap:7px;margin:4px 0 6px;font-size:0.72rem;color:var(--text-muted);cursor:pointer">
                <input type="checkbox" v-model="noneChecked.intro" @change="onNoneToggle('intro')" />
                No intro this week — save as confirmed none
              </label>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <div>
                  <label class="form-label" style="font-size:0.75rem">Start Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.intro_start" class="form-input" placeholder="01:30" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('intro_start')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
                <div>
                  <label class="form-label" style="font-size:0.75rem">End Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.intro_end" class="form-input" placeholder="03:00" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('intro_end')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 3. Outro Section -->
            <div class="skip-timestamp-group">
              <div style="font-size:0.88rem;font-weight:700;color:#10b981;margin-bottom:2px;display:flex;align-items:center;gap:6px">
                <i class="ph ph-flag"></i> Outro
                <span style="font-weight:600;color:var(--text-muted);font-size:0.65rem;text-transform:none">max 15 min</span>
                <span v-if="sourceInfo.outro" class="skip-src-badge" title="Auto-detected values prefilled below — saving adopts them as manual markers">{{ sourceInfo.outro }}</span>
              </div>
              <div class="skip-seg-desc">End credits.</div>
              <label style="display:flex;align-items:center;gap:7px;margin:4px 0 6px;font-size:0.72rem;color:var(--text-muted);cursor:pointer">
                <input type="checkbox" v-model="noneChecked.outro" @change="onNoneToggle('outro')" />
                No outro this week — save as confirmed none
              </label>
              <label style="display:flex;align-items:center;gap:7px;margin:0 0 6px;font-size:0.72rem;color:var(--text-secondary);cursor:pointer">
                <input type="checkbox" v-model="toEnd.outro" @change="onToEndToggle" />
                Runs to the end of the video
              </label>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <div>
                  <label class="form-label" style="font-size:0.75rem">Start Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.outro_start" class="form-input" placeholder="22:00" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('outro_start')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
                <div>
                  <label class="form-label" style="font-size:0.75rem">End Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.outro_end" class="form-input" placeholder="24:00" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('outro_end')" title="Set to active frame time">⏱️ Stamp</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 4. Preview Section -->
            <div class="skip-timestamp-group">
              <div style="font-size:0.88rem;font-weight:700;color:#c084fc;margin-bottom:2px;display:flex;align-items:center;gap:6px">
                <i class="ph ph-telescope"></i> Preview
                <span style="font-weight:600;color:var(--text-muted);font-size:0.65rem;text-transform:none">max 15 min</span>
                <span v-if="sourceInfo.preview" class="skip-src-badge" title="Auto-detected values prefilled below — saving adopts them as manual markers">{{ sourceInfo.preview }}</span>
              </div>
              <div class="skip-seg-desc">"Next time on…" teaser for the following episode.</div>
              <label style="display:flex;align-items:center;gap:7px;margin:4px 0 6px;font-size:0.72rem;color:var(--text-muted);cursor:pointer">
                <input type="checkbox" v-model="noneChecked.preview" @change="onNoneToggle('preview')" />
                No preview this week — save as confirmed none
              </label>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                <div>
                  <label class="form-label" style="font-size:0.75rem">Start Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.preview_start" class="form-input" placeholder="23:40" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('preview_start')" title="Set to active frame time">⏱ Stamp</button>
                  </div>
                </div>
                <div>
                  <label class="form-label" style="font-size:0.75rem">End Time</label>
                  <div style="display:flex;gap:4px">
                    <input type="text" v-model="form.preview_end" class="form-input" placeholder="24:10" />
                    <button v-if="inPlayer" class="btn btn-secondary btn-sm" @click="stampCurrent('preview_end')" title="Set to active frame time">⏱ Stamp</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div style="display:flex;gap:0.75rem;justify-content:flex-end">
            <button class="btn btn-ghost" @click="$emit('close')">Cancel</button>
            <button class="btn btn-primary" @click="save" :disabled="saving" id="btn-save-skip-stamps">
              <i class="ph ph-floppy-disk" style="margin-right:6px"></i>
              {{ saving ? 'Saving...' : 'Save Timestamps' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup(props, { emit }) {
    const saving = ref(false);

    // Segment validation limits (minutes)
    const SEGMENTS = [
      { key: "recap",   label: "Recap",   max: 5 },
      { key: "intro",   label: "Intro",   max: 5 },
      { key: "outro",   label: "Outro",   max: 15 },
      { key: "preview", label: "Preview", max: 15 },
    ];
    const videoDuration = Number(props.media?.duration) || 0;

    const form = ref({
      recap_start: formatSecToTime(props.media?.recap_start),
      recap_end: formatSecToTime(props.media?.recap_end),
      intro_start: formatSecToTime(props.media?.intro_start),
      intro_end: formatSecToTime(props.media?.intro_end),
      outro_start: formatSecToTime(props.media?.outro_start),
      outro_end: formatSecToTime(props.media?.outro_end),
      preview_start: formatSecToTime(props.media?.preview_start),
      preview_end: formatSecToTime(props.media?.preview_end),
    });

    // Sentinel state: a stored 0/0 pair means the user CONFIRMED this
    // episode has no such segment. Defaults to UNCHECKED — the boxes only
    // get checked after resolution confirms there's genuinely no marker
    // (0/0 is also the default of untouched episodes, so checking it
    // unconditionally made every episode claim "no recap/intro/…").
    const noneChecked = reactive({
      recap:   false,
      intro:   false,
      outro:   false,
      preview: false,
    });

    // Outro convenience: end auto-fills to the video duration on save
    const toEnd = reactive({ outro: false });

    // Where prefilled values came from ("" = manual/empty). Resolved skip
    // data (manual DB → AniSkip → ffprobe chapters) is fetched so the modal
    // shows the same markers the player uses — not just the DB columns.
    const sourceInfo = reactive({ recap: "", intro: "", outro: "", preview: "" });
    const loadingMarkers = ref(false);
    const SEG_TO_RESOLVED = { recap: "recap", intro: "op", outro: "ed", preview: "preview" };
    const SOURCE_LABELS = { manual: "Manual", aniskip: "AniSkip", chapters: "Chapters", audio: "Audio Detect" };

    onMounted(() => refreshMarkers(false));

    // Resolves skip data (manual DB → AniSkip → audio → chapters) and
    // prefills the form. force=true bypasses the server-side cache to
    // re-query AniSkip and re-run detection.
    async function refreshMarkers(force = false) {
      loadingMarkers.value = true;
      try {
        const resolved = await API.get(`/api/skip-times/${props.media.id}${force ? "?refresh=1" : ""}`);
        if (!resolved) return;
        for (const [seg, key] of Object.entries(SEG_TO_RESOLVED)) {
          const s = resolved[key];
          const start = Number(s?.start), end = Number(s?.end);
          const hasMarker = s && end > start;
          const dbStart = Number(props.media?.[seg + "_start"]) || 0;
          const dbEnd = Number(props.media?.[seg + "_end"]) || 0;

          if (hasMarker && s.source !== "manual") {
            // Auto-detected marker (AniSkip / audio / chapters) — prefill it
            // and clear any "confirmed none" sentinel: the player is actively
            // using this marker, so claiming "no intro" would be wrong.
            if (dbStart <= 0 && dbEnd <= 0) {
              noneChecked[seg] = false;
              form.value[seg + "_start"] = formatSecToTime(start);
              form.value[seg + "_end"] = formatSecToTime(end);
              sourceInfo[seg] = SOURCE_LABELS[s.source] || s.source;
            } else {
              // Manual DB values win — show them without a source badge
              noneChecked[seg] = false;
            }
          } else if (!hasMarker) {
            // No marker from any source — "no recap/intro/…" is accurate.
            // On a forced re-check also clear stale prefills.
            if (dbStart === 0 && dbEnd === 0) {
              noneChecked[seg] = true;
              if (force && sourceInfo[seg]) {
                form.value[seg + "_start"] = "";
                form.value[seg + "_end"] = "";
                sourceInfo[seg] = "";
              }
            }
          }
        }
      } catch (e) { /* resolved data unavailable — manual-only view */ }
      finally { loadingMarkers.value = false; }
    }

    function onNoneToggle(key) {
      if (noneChecked[key]) {
        form.value[key + "_start"] = "00:00";
        form.value[key + "_end"] = "00:00";
        if (key === "outro") toEnd.outro = false;
      }
    }

    function stampCurrent(field) {
      if (props.currentTime !== undefined && props.currentTime !== null) {
        form.value[field] = formatSecToTime(props.currentTime);
      }
    }

    async function save() {
      if (!props.media?.id) return;
      saving.value = true;

      const payload = {};
      for (const seg of SEGMENTS) {
        const key = seg.key;
        const rawStart = parseTimeToSec(form.value[key + "_start"]);
        let rawEnd = parseTimeToSec(form.value[key + "_end"]);

        // Sentinel - confirmed none
        if (noneChecked[key]) {
          payload[key + "_start"] = 0;
          payload[key + "_end"] = 0;
          continue;
        }

        const s = Number(rawStart) || 0;

        // Outro: missing/to-end end ALWAYS resolves to the media's end.
        // Client fills it when the duration is known; otherwise sends null
        // and the SERVER measures the file via ffprobe. The saved record
        // therefore always ends up with a concrete outro_end value.
        if (key === "outro") {
          if (toEnd.outro || !rawEnd || rawEnd === null) {
            rawEnd = videoDuration > 0 ? Math.round(videoDuration) : null;
          } else if (videoDuration > 0 && Math.abs(rawEnd - videoDuration) <= 10) {
            rawEnd = Math.round(videoDuration);
          }
        }

        // Untouched empty segment -> send nothing; server keeps old values.
        // (For outro with a start but no end we DO send, end resolved above.)
        if (!s && !rawEnd) continue;

        if (!s) {
          addToast(seg.label + ": start time is required", "error", 5000);
          saving.value = false;
          return;
        }

        if (rawEnd === null && key !== "outro") {
          addToast(seg.label + ": end time is required", "error", 5000);
          saving.value = false;
          return;
        }

        const len = rawEnd - s;
        if (len <= 0) {
          addToast(seg.label + ": end must come after start", "error", 5000);
          saving.value = false;
          return;
        }
        if (len < 5) {
          addToast(seg.label + ": segments must be at least 5 seconds long", "error", 5000);
          saving.value = false;
          return;
        }
        if (len > seg.max * 60) {
          addToast(seg.label + ": cannot exceed " + seg.max + " minutes", "error", 5000);
          saving.value = false;
          return;
        }

        payload[key + "_start"] = s;
        payload[key + "_end"] = rawEnd;
      }

      try {
        await API.post(`/api/media/${props.media.id}/skip-timestamps`, payload);
        emit("saved", payload);
        emit("close");
      } catch (e) {
        addToast(e.message || "Failed to save skip timestamps", "error");
      } finally {
        saving.value = false;
      }
    }

    return { form, saving, stampCurrent, save, noneChecked, toEnd, onNoneToggle, sourceInfo, loadingMarkers, refreshMarkers };
  }
};

// ─── Mount App ────────────────────────────────────────────────

const app = createApp(App);
// Expose to ALL component templates — module-level helpers aren't visible
// in template scope otherwise (this is why IMDb-link clicks did nothing).
app.config.globalProperties.unlockAchievement = unlockAchievement;
app.component("skip-timestamps-modal", SkipTimestampsModal);
app.component("fix-match-modal", FixMatchModal);
app.use(router);
app.mount("#app");
