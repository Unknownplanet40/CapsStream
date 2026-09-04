/* ============================================================
   CapsStream — Global Music Player & State Manager
   HTML5 Audio + MediaSession API + Synced LRC Parser + Persistence
   ============================================================ */

(function () {
  const { reactive } = Vue;

  const STORAGE_KEY_SETTINGS = "cs_music_settings";
  const STORAGE_KEY_QUEUE = "cs_music_queue";

  function loadSavedSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_SETTINGS);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return { volume: 0.8, isMuted: false, shuffle: false, repeat: "off" };
  }

  function loadSavedQueue() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_QUEUE);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.queue)) {
          return { queue: parsed.queue, index: parsed.index || 0 };
        }
      }
    } catch (e) {}
    return { queue: [], index: -1 };
  }

  const savedSettings = loadSavedSettings();
  const savedQueue = loadSavedQueue();

  const state = reactive({
    queue: savedQueue.queue,
    currentIndex: savedQueue.index,
    currentTrack: savedQueue.queue[savedQueue.index] || null,
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: typeof savedSettings.volume === "number" ? savedSettings.volume : 0.8,
    isMuted: !!savedSettings.isMuted,
    shuffle: !!savedSettings.shuffle,
    repeat: savedSettings.repeat || "off", // 'off' | 'all' | 'one'
    lyrics: [],
    rawLyrics: "",
    isSyncedLyrics: false,
    activeLyricIndex: -1,
    showModal: false,
    modalTab: "lyrics", // 'lyrics' | 'queue'
    isLoading: false,
    rightPanelOpen: window.innerWidth > 960,
    rightPanelTab: "lyrics", // 'lyrics' | 'queue'
    fullscreenKaraoke: false,
    dominantColor: "#1ed760",
    accentGlow: "rgba(30, 215, 96, 0.4)",
  });

  const audio = new Audio();
  audio.preload = "auto";
  audio.volume = state.isMuted ? 0 : state.volume;

  let hasScrobbled = false;
  let playSessionSeconds = 0;
  let lastTimeUpdate = 0;

  function persistSettings() {
    try {
      localStorage.setItem(
        STORAGE_KEY_SETTINGS,
        JSON.stringify({
          volume: state.volume,
          isMuted: state.isMuted,
          shuffle: state.shuffle,
          repeat: state.repeat,
        })
      );
    } catch (e) {}
  }

  function persistQueue() {
    try {
      localStorage.setItem(
        STORAGE_KEY_QUEUE,
        JSON.stringify({
          queue: state.queue.slice(0, 500),
          index: state.currentIndex,
        })
      );
    } catch (e) {}
  }

  function parseLRC(text) {
    if (!text || typeof text !== "string") return [];
    const lines = text.split(/\r?\n/);
    const parsed = [];
    const timeReg = /\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]/g;

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;
      timeReg.lastIndex = 0;
      let match;
      const times = [];
      let lastMatchEnd = 0;

      while ((match = timeReg.exec(line)) !== null) {
        const mins = parseInt(match[1], 10);
        const secs = parseInt(match[2], 10);
        const msRaw = match[3] || "0";
        const ms = parseFloat("0." + msRaw);
        times.push(mins * 60 + secs + ms);
        lastMatchEnd = timeReg.lastIndex;
      }

      const content = line.slice(lastMatchEnd).trim();
      if (times.length > 0) {
        for (const t of times) {
          parsed.push({ time: t, text: content || "♪" });
        }
      }
    }

    parsed.sort((a, b) => a.time - b.time);
    return parsed;
  }

  function updateMediaSession(track) {
    if (!("mediaSession" in navigator)) return;
    if (!track) {
      navigator.mediaSession.metadata = null;
      return;
    }

    const artwork = [];
    if (track.cover_path) {
      const src = `/api/music/covers/${track.cover_path.replace("music_covers/", "")}`;
      artwork.push({ src, sizes: "512x512", type: "image/jpeg" });
    }

    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title || "Unknown Title",
      artist: track.artist_name || "Unknown Artist",
      album: track.album_title || "Unknown Album",
      artwork,
    });

    try {
      navigator.mediaSession.setActionHandler("play", () => MusicPlayer.togglePlay());
      navigator.mediaSession.setActionHandler("pause", () => MusicPlayer.togglePlay());
      navigator.mediaSession.setActionHandler("previoustrack", () => MusicPlayer.prev());
      navigator.mediaSession.setActionHandler("nexttrack", () => MusicPlayer.next());
      navigator.mediaSession.setActionHandler("seekto", (details) => {
        if (details.seekTime != null) MusicPlayer.seek(details.seekTime);
      });
    } catch (e) {}
  }

  function applyColor([r, g, b]) {
    state.dominantColor = `rgb(${r}, ${g}, ${b})`;
    state.accentGlow = `rgba(${r}, ${g}, ${b}, 0.38)`;
    document.documentElement.style.setProperty("--spotify-accent", `rgb(${r}, ${g}, ${b})`);
    document.documentElement.style.setProperty("--spotify-accent-glow", `rgba(${r}, ${g}, ${b}, 0.35)`);
    document.documentElement.style.setProperty(
      "--spotify-header-gradient",
      `linear-gradient(180deg, rgba(${r}, ${g}, ${b}, 0.75) 0%, rgba(18, 18, 18, 0.95) 100%)`
    );
  }

  function extractDominantColor(imgUrl) {
    if (!imgUrl) {
      applyColor([30, 215, 96]);
      return;
    }
    const img = new Image();
    img.crossOrigin = "Anonymous";
    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d");
        canvas.width = 40;
        canvas.height = 40;
        ctx.drawImage(img, 0, 0, 40, 40);
        const data = ctx.getImageData(0, 0, 40, 40).data;
        let rSum = 0, gSum = 0, bSum = 0, count = 0;
        for (let i = 0; i < data.length; i += 16) {
          const r = data[i], g = data[i + 1], b = data[i + 2], a = data[i + 3];
          if (a > 128) {
            const brightness = (r * 299 + g * 587 + b * 114) / 1000;
            if (brightness > 35 && brightness < 225) {
              rSum += r; gSum += g; bSum += b; count++;
            }
          }
        }
        if (count > 0) {
          applyColor([Math.round(rSum / count), Math.round(gSum / count), Math.round(bSum / count)]);
        } else {
          applyColor([30, 215, 96]);
        }
      } catch (e) {
        applyColor([30, 215, 96]);
      }
    };
    img.onerror = () => applyColor([30, 215, 96]);
    img.src = imgUrl;
  }

  // Audio Event Listeners
  audio.addEventListener("loadedmetadata", () => {
    state.duration = audio.duration || state.currentTrack?.duration || 0;
    state.isLoading = false;
  });

  audio.addEventListener("timeupdate", () => {
    state.currentTime = audio.currentTime;
    if (!state.duration && audio.duration) {
      state.duration = audio.duration;
    }

    // Scrobble tracking
    const now = Date.now();
    if (lastTimeUpdate > 0 && !audio.paused) {
      playSessionSeconds += (now - lastTimeUpdate) / 1000;
    }
    lastTimeUpdate = now;

    if (!hasScrobbled && state.currentTrack) {
      const dur = state.duration || state.currentTrack.duration || 0;
      if ((dur > 0 && audio.currentTime >= dur * 0.5) || playSessionSeconds >= 30) {
        hasScrobbled = true;
        fetch("/api/music/history", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            track_id: state.currentTrack.id,
            duration_played: Math.round(audio.currentTime),
          }),
        }).catch(() => {});
      }
    }

    // Synced lyrics highlight
    if (state.isSyncedLyrics && state.lyrics.length > 0) {
      const cur = audio.currentTime;
      let activeIdx = -1;
      for (let i = 0; i < state.lyrics.length; i++) {
        if (state.lyrics[i].time <= cur) {
          activeIdx = i;
        } else {
          break;
        }
      }
      state.activeLyricIndex = activeIdx;
    }
  });

  audio.addEventListener("play", () => {
    state.isPlaying = true;
    lastTimeUpdate = Date.now();
  });

  audio.addEventListener("pause", () => {
    state.isPlaying = false;
    lastTimeUpdate = 0;
  });

  audio.addEventListener("ended", () => {
    if (state.repeat === "one") {
      audio.currentTime = 0;
      audio.play().catch(() => {});
      return;
    }
    MusicPlayer.next(true);
  });

  audio.addEventListener("waiting", () => {
    state.isLoading = true;
  });

  audio.addEventListener("canplay", () => {
    state.isLoading = false;
  });

  audio.addEventListener("error", (e) => {
    state.isLoading = false;
    state.isPlaying = false;
    console.error("[MusicPlayer] Playback error:", e);
  });

  // Global Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) {
      return;
    }

    if (e.code === "Space" && state.currentTrack) {
      // Don't intercept if video player is active
      if (document.querySelector(".video-player-container, #player-view.active")) return;
      e.preventDefault();
      MusicPlayer.togglePlay();
    } else if ((e.code === "ArrowUp" || e.key === "ArrowUp") && state.fullscreenKaraoke) {
      e.preventDefault();
      const currentVol = state.isMuted ? 0 : state.volume;
      MusicPlayer.setVolume(Math.min(1, Math.round((currentVol + 0.05) * 100) / 100));
    } else if ((e.code === "ArrowDown" || e.key === "ArrowDown") && state.fullscreenKaraoke) {
      e.preventDefault();
      const currentVol = state.isMuted ? 0 : state.volume;
      MusicPlayer.setVolume(Math.max(0, Math.round((currentVol - 0.05) * 100) / 100));
    } else if (e.code === "ArrowLeft" && e.altKey && state.currentTrack) {
      e.preventDefault();
      MusicPlayer.seek(Math.max(0, audio.currentTime - 5));
    } else if (e.code === "ArrowRight" && e.altKey && state.currentTrack) {
      e.preventDefault();
      MusicPlayer.seek(Math.min(state.duration || 0, audio.currentTime + 5));
    }
  });

  const MusicPlayer = {
    state,

    playTrack(track, newQueue = null, index = 0) {
      if (!track) return;

      if (newQueue && Array.isArray(newQueue)) {
        state.queue = [...newQueue];
        state.currentIndex = index >= 0 && index < newQueue.length ? index : 0;
      } else {
        const existingIdx = state.queue.findIndex((t) => t.id === track.id);
        if (existingIdx !== -1) {
          state.currentIndex = existingIdx;
        } else {
          state.queue.push(track);
          state.currentIndex = state.queue.length - 1;
        }
      }

      state.currentTrack = track;
      state.currentTime = 0;
      state.duration = track.duration || 0;
      hasScrobbled = false;
      playSessionSeconds = 0;
      lastTimeUpdate = 0;

      audio.src = `/api/music/stream/${track.id}`;
      state.isLoading = true;
      audio.play().catch((err) => {
        console.warn("[MusicPlayer] Autoplay prevented or stream error:", err);
      });

      updateMediaSession(track);
      persistQueue();
      this.loadLyrics(track.id);

      if (track.cover_path) {
        extractDominantColor(`/api/music/covers/${track.cover_path.replace('music_covers/', '')}`);
      } else {
        applyColor([30, 215, 96]);
      }
    },

    togglePlay() {
      if (!state.currentTrack) {
        if (state.queue.length > 0) {
          const idx = state.currentIndex >= 0 ? state.currentIndex : 0;
          this.playTrack(state.queue[idx], null, idx);
        }
        return;
      }

      if (audio.paused) {
        audio.play().catch(() => {});
      } else {
        audio.pause();
      }
    },

    next(isAuto = false) {
      if (state.queue.length === 0) return;

      if (state.shuffle && state.queue.length > 1) {
        let randIdx;
        do {
          randIdx = Math.floor(Math.random() * state.queue.length);
        } while (randIdx === state.currentIndex && state.queue.length > 1);
        this.playTrack(state.queue[randIdx], null, randIdx);
        return;
      }

      if (state.currentIndex + 1 < state.queue.length) {
        const nextIdx = state.currentIndex + 1;
        this.playTrack(state.queue[nextIdx], null, nextIdx);
      } else if (state.repeat === "all") {
        this.playTrack(state.queue[0], null, 0);
      } else if (!isAuto) {
        // manual next on last track loops back
        this.playTrack(state.queue[0], null, 0);
      } else {
        state.isPlaying = false;
      }
    },

    prev() {
      if (audio.currentTime > 3) {
        audio.currentTime = 0;
        return;
      }
      if (state.queue.length === 0) return;

      if (state.currentIndex > 0) {
        const prevIdx = state.currentIndex - 1;
        this.playTrack(state.queue[prevIdx], null, prevIdx);
      } else if (state.repeat === "all") {
        const lastIdx = state.queue.length - 1;
        this.playTrack(state.queue[lastIdx], null, lastIdx);
      } else {
        audio.currentTime = 0;
      }
    },

    seek(seconds) {
      if (!isFinite(seconds)) return;
      audio.currentTime = Math.max(0, Math.min(seconds, state.duration || 999999));
      state.currentTime = audio.currentTime;
    },

    setVolume(val) {
      const clamped = Math.max(0, Math.min(1, val));
      state.volume = clamped;
      state.isMuted = false;
      audio.volume = clamped;
      persistSettings();
    },

    toggleMute() {
      state.isMuted = !state.isMuted;
      audio.volume = state.isMuted ? 0 : state.volume;
      persistSettings();
    },

    toggleShuffle() {
      state.shuffle = !state.shuffle;
      persistSettings();
    },

    toggleRepeat() {
      const order = ["off", "all", "one"];
      const nextIdx = (order.indexOf(state.repeat) + 1) % order.length;
      state.repeat = order[nextIdx];
      persistSettings();
    },

    async toggleFavorite(track) {
      if (!track) return;
      try {
        const r = await fetch("/api/music/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ track_id: track.id }),
        });
        const data = await r.json();
        if (data.ok) {
          track.is_favorite = data.is_favorite ? 1 : 0;
          if (state.currentTrack && state.currentTrack.id === track.id) {
            state.currentTrack.is_favorite = track.is_favorite;
          }
          // Also sync any duplicates in current queue
          for (const item of state.queue) {
            if (item.id === track.id) {
              item.is_favorite = track.is_favorite;
            }
          }
        }
      } catch (e) {
        console.error("[MusicPlayer] Failed to toggle favorite:", e);
      }
    },

    addToQueue(track) {
      if (!track) return;
      state.queue.push(track);
      persistQueue();
      if (!state.currentTrack) {
        this.playTrack(track, null, state.queue.length - 1);
      }
    },

    playNextTrack(track) {
      if (!track) return;
      if (state.queue.length === 0 || state.currentIndex === -1) {
        this.playTrack(track, [track], 0);
        return;
      }
      state.queue.splice(state.currentIndex + 1, 0, track);
      persistQueue();
    },

    removeFromQueue(index) {
      if (index < 0 || index >= state.queue.length) return;
      state.queue.splice(index, 1);
      if (index < state.currentIndex) {
        state.currentIndex--;
      } else if (index === state.currentIndex) {
        if (state.queue.length > 0) {
          const nextIdx = Math.min(index, state.queue.length - 1);
          this.playTrack(state.queue[nextIdx], null, nextIdx);
        } else {
          audio.pause();
          audio.src = "";
          state.currentTrack = null;
          state.currentIndex = -1;
          state.isPlaying = false;
        }
      }
      persistQueue();
    },

    clearQueue() {
      audio.pause();
      audio.src = "";
      state.queue = [];
      state.currentTrack = null;
      state.currentIndex = -1;
      state.isPlaying = false;
      state.lyrics = [];
      state.rawLyrics = "";
      state.isSyncedLyrics = false;
      state.showModal = false;
      persistQueue();
    },

    async loadLyrics(trackId) {
      state.lyrics = [];
      state.rawLyrics = "";
      state.isSyncedLyrics = false;
      state.activeLyricIndex = -1;

      try {
        const r = await fetch(`/api/music/lyrics/${trackId}`);
        if (!r.ok) return;
        const data = await r.json();
        if (data && data.lyrics) {
          state.rawLyrics = data.lyrics;
          state.isSyncedLyrics = !!data.synced;
          if (state.isSyncedLyrics) {
            state.lyrics = parseLRC(data.lyrics);
          }
        }
      } catch (e) {
        console.warn("[MusicPlayer] Could not fetch lyrics:", e);
      }
    },

    openModal(tab = "lyrics") {
      state.modalTab = tab;
      state.showModal = true;
    },

    closeModal() {
      state.showModal = false;
    },

    toggleRightPanel(tab = null) {
      if (tab) {
        if (state.rightPanelOpen && state.rightPanelTab === tab) {
          state.rightPanelOpen = false;
        } else {
          state.rightPanelTab = tab;
          state.rightPanelOpen = true;
        }
      } else {
        state.rightPanelOpen = !state.rightPanelOpen;
      }
    },

    toggleKaraoke() {
      state.fullscreenKaraoke = !state.fullscreenKaraoke;
    },
  };

  // Initial color extraction if saved track exists
  if (state.currentTrack && state.currentTrack.cover_path) {
    extractDominantColor(`/api/music/covers/${state.currentTrack.cover_path.replace('music_covers/', '')}`);
  } else {
    applyColor([30, 215, 96]);
  }

  window.MusicPlayer = MusicPlayer;
})();
