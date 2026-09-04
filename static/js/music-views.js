/* ============================================================
   CapsStream — Spotify-Inspired Music Interface & Components
   3-Panel Desktop Architecture + Dynamic Adaptive Hero + Live Synced Lyrics
   ============================================================ */

(function () {
  const { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

  // ─── Global Bottom Player Dock (Spotify Style) ───────────────
  const GlobalMusicDock = {
    template: `
      <div class="music-dock spotify-dock" v-if="player && player.state.currentTrack && isMusicRoute" id="global-music-dock">
        <!-- Left: Track Info & Favorite -->
        <div class="music-dock-info" @click="player.toggleRightPanel('lyrics')">
          <div class="music-dock-thumb-wrap">
            <img v-if="player.state.currentTrack.cover_path" :src="'/api/music/covers/' + player.state.currentTrack.cover_path.replace('music_covers/', '')" class="music-dock-thumb" />
            <div v-else class="music-dock-thumb-placeholder">
              <i class="ph-fill ph-music-notes"></i>
            </div>
            <button class="music-dock-expand-hover" @click.stop="player.toggleKaraoke()" title="Open Fullscreen Karaoke">
              <i class="ph-bold ph-arrows-out-simple"></i>
            </button>
          </div>
          <div class="music-dock-meta">
            <div class="music-dock-title" :title="player.state.currentTrack.title">{{ player.state.currentTrack.title }}</div>
            <div class="music-dock-artist spotify-artist-link" @click.stop="goToArtist(player.state.currentTrack.artist_name)" :title="'View ' + player.state.currentTrack.artist_name">{{ player.state.currentTrack.artist_name || 'Unknown Artist' }}</div>
          </div>
          <button class="music-dock-fav-btn" :class="{ active: player.state.currentTrack.is_favorite }" @click.stop="player.toggleFavorite(player.state.currentTrack)" title="Save to Your Library">
            <i :class="player.state.currentTrack.is_favorite ? 'ph-fill ph-heart' : 'ph-bold ph-heart'"></i>
          </button>
        </div>

        <!-- Center: Controls & Scrubber -->
        <div class="music-dock-center">
          <div class="music-dock-controls">
            <button class="music-ctrl-btn" :class="{ active: player.state.shuffle }" @click="player.toggleShuffle()" title="Enable Shuffle">
              <i class="ph-bold ph-shuffle"></i>
            </button>
            <button class="music-ctrl-btn" @click="player.prev()" title="Previous Track">
              <i class="ph-fill ph-skip-back"></i>
            </button>
            <button class="music-play-btn spotify-green-play" @click="player.togglePlay()" :title="player.state.isPlaying ? 'Pause' : 'Play'">
              <i :class="player.state.isPlaying ? 'ph-fill ph-pause' : 'ph-fill ph-play'"></i>
            </button>
            <button class="music-ctrl-btn" @click="player.next()" title="Next Track">
              <i class="ph-fill ph-skip-forward"></i>
            </button>
            <button class="music-ctrl-btn" :class="{ active: player.state.repeat !== 'off' }" @click="player.toggleRepeat()" :title="'Repeat: ' + player.state.repeat">
              <i :class="player.state.repeat === 'one' ? 'ph-bold ph-repeat-once' : 'ph-bold ph-repeat'"></i>
            </button>
          </div>

          <div class="music-dock-scrubber">
            <span class="music-dock-time">{{ formatTime(player.state.currentTime) }}</span>
            <div class="music-progress-bar-wrap" @click="onSeekClick" ref="progressRef">
              <div class="music-progress-track">
                <div class="music-progress-fill spotify-progress-fill" :style="{ width: progressPercent + '%' }"></div>
              </div>
            </div>
            <span class="music-dock-time">{{ formatTime(player.state.duration) }}</span>
          </div>
        </div>

        <!-- Right: Extras & Volume -->
        <div class="music-dock-right">
          <button
            class="music-dock-action-btn"
            :class="{ active: player.state.rightPanelOpen && player.state.rightPanelTab === 'lyrics' }"
            @click="player.toggleRightPanel('lyrics')"
            title="Lyrics"
          >
            <i class="ph-bold ph-microphone-stage"></i>
          </button>

          <button
            class="music-dock-action-btn"
            :class="{ active: player.state.rightPanelOpen && player.state.rightPanelTab === 'queue' }"
            @click="player.toggleRightPanel('queue')"
            title="Queue"
          >
            <i class="ph-bold ph-queue"></i>
          </button>

          <div class="music-dock-volume">
            <button class="music-dock-vol-btn" @click="player.toggleMute()" title="Mute/Unmute">
              <i :class="volIcon"></i>
            </button>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              :value="player.state.isMuted ? 0 : player.state.volume"
              @input="onVolumeChange"
              class="music-vol-slider spotify-slider"
              :style="{ '--vol-pct': ((player.state.isMuted ? 0 : player.state.volume) * 100) + '%' }"
            />
          </div>

          <button class="music-dock-action-btn" @click="player.toggleKaraoke()" title="Full Screen Karaoke">
            <i class="ph-bold ph-arrows-out-simple"></i>
          </button>
        </div>
      </div>
    `,
    setup() {
      const route = VueRouter.useRoute();
      const player = window.MusicPlayer;
      const progressRef = ref(null);

      const isMusicRoute = computed(() => route.path.startsWith("/music"));

      watch(
        () => route.path,
        (newPath) => {
          if (newPath.startsWith("/watch") && player && player.state.isPlaying) {
            player.pause();
          }
        }
      );

      function formatTime(s) {
        if (!s || isNaN(s)) return "0:00";
        const mins = Math.floor(s / 60);
        const secs = Math.floor(s % 60);
        return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
      }

      const progressPercent = computed(() => {
        if (!player.state.duration) return 0;
        return Math.min(100, (player.state.currentTime / player.state.duration) * 100);
      });

      const volIcon = computed(() => {
        if (player.state.isMuted || player.state.volume === 0) return "ph-fill ph-speaker-simple-x";
        if (player.state.volume < 0.5) return "ph-fill ph-speaker-simple-low";
        return "ph-fill ph-speaker-simple-high";
      });

      function onSeekClick(e) {
        if (!progressRef.value || !player.state.duration) return;
        const rect = progressRef.value.getBoundingClientRect();
        const pos = (e.clientX - rect.left) / rect.width;
        player.seek(pos * player.state.duration);
      }

      function onVolumeChange(e) {
        player.setVolume(parseFloat(e.target.value));
      }

      function goToArtist(artistName) {
        if (!artistName) return;
        if (route.path !== "/music") {
          VueRouter.useRouter().push("/music").then(() => {
            setTimeout(() => {
              if (window.MusicViewDispatcher && window.MusicViewDispatcher.openArtistByName) {
                window.MusicViewDispatcher.openArtistByName(artistName);
              }
            }, 100);
          });
        } else {
          if (window.MusicViewDispatcher && window.MusicViewDispatcher.openArtistByName) {
            window.MusicViewDispatcher.openArtistByName(artistName);
          }
        }
      }

      return {
        player,
        progressRef,
        isMusicRoute,
        formatTime,
        progressPercent,
        volIcon,
        onSeekClick,
        onVolumeChange,
        goToArtist,
      };
    },
  };

  // ─── Fullscreen Cinema Spotify Experience Overlay ─────────────
  const NowPlayingModal = {
    template: `
      <div class="spotify-fullscreen-modal" v-if="player && player.state.fullscreenKaraoke && isMusicRoute">
        <!-- Ambient Blurred Backdrop -->
        <div class="spot-fs-ambient-bg" :style="ambientStyle"></div>
        <div class="spot-fs-backdrop-overlay"></div>

        <!-- Top Navigation Bar -->
        <div class="spot-fs-topbar">
          <div class="spot-fs-album-context">
            <div class="spot-fs-disc-icon">
              <i class="ph-bold ph-vinyl-record"></i>
            </div>
            <div class="spot-fs-context-meta">
              <div class="spot-fs-context-label">PLAYING FROM ALBUM</div>
              <div class="spot-fs-context-title">{{ player.state.currentTrack?.album_title || player.state.currentTrack?.title || 'Unknown Album' }}</div>
            </div>
          </div>

          <button class="spot-fs-exit-btn" @click="player.toggleKaraoke()" title="Exit Fullscreen (Esc)">
            <i class="ph-bold ph-arrows-in-simple"></i>
          </button>
        </div>

        <!-- Main Content: Left Volume Rail + Center Player Card + Right Synced Lyrics -->
        <div class="spot-fs-body">
          <!-- 1. Left Vertical Volume Rail -->
          <div class="spot-fs-volume-rail">
            <span class="spot-fs-vol-pct">{{ Math.round((player.state.isMuted ? 0 : player.state.volume) * 100) }}%</span>
            <div class="spot-fs-vol-track" @mousedown="onVolMouseDown" @touchstart.passive="onVolTouchStart" ref="volTrackRef">
              <div class="spot-fs-vol-fill" :style="{ height: (player.state.isMuted ? 0 : player.state.volume * 100) + '%' }"></div>
              <div class="spot-fs-vol-thumb" :style="{ bottom: (player.state.isMuted ? 0 : player.state.volume * 100) + '%' }"></div>
            </div>
            <button class="spot-fs-vol-btn" @click="player.toggleMute()" title="Mute/Unmute">
              <i :class="volIcon"></i>
            </button>
          </div>

          <!-- 2. Player Left-Center Card -->
          <div class="spot-fs-player-pane">
            <div class="spot-fs-cover-box">
              <img v-if="player.state.currentTrack?.cover_path" :src="'/api/music/covers/' + player.state.currentTrack.cover_path.replace('music_covers/', '')" class="spot-fs-cover-img" />
              <div v-else class="spot-fs-cover-placeholder">
                <i class="ph-fill ph-music-notes"></i>
              </div>
            </div>

            <div class="spot-fs-meta">
              <h2 class="spot-fs-track-title" :title="player.state.currentTrack?.title">{{ player.state.currentTrack?.title }}</h2>
              <div class="spot-fs-track-artist spotify-artist-link" :title="'View ' + player.state.currentTrack?.artist_name" @click="goToArtist(player.state.currentTrack?.artist_name)">{{ player.state.currentTrack?.artist_name || 'Unknown Artist' }}</div>
              <div class="spot-fs-track-album" :title="player.state.currentTrack?.album_title">{{ player.state.currentTrack?.album_title }}</div>
            </div>

            <!-- Controls Row -->
            <div class="spot-fs-controls-row">
              <button class="spot-fs-ctrl-btn" :class="{ active: player.state.currentTrack?.is_favorite }" @click="player.toggleFavorite(player.state.currentTrack)" title="Save to Library">
                <i :class="player.state.currentTrack?.is_favorite ? 'ph-fill ph-heart heart-green' : 'ph-bold ph-heart'"></i>
              </button>

              <button class="spot-fs-ctrl-btn" :class="{ active: player.state.shuffle }" @click="player.toggleShuffle()" title="Shuffle">
                <i class="ph-bold ph-shuffle"></i>
              </button>

              <button class="spot-fs-ctrl-btn" @click="player.prev()" title="Previous">
                <i class="ph-fill ph-skip-back"></i>
              </button>

              <button class="spot-fs-play-btn" @click="player.togglePlay()" :title="player.state.isPlaying ? 'Pause' : 'Play'">
                <i :class="player.state.isPlaying ? 'ph-fill ph-pause' : 'ph-fill ph-play'"></i>
              </button>

              <button class="spot-fs-ctrl-btn" @click="player.next()" title="Next">
                <i class="ph-fill ph-skip-forward"></i>
              </button>

              <button class="spot-fs-ctrl-btn" :class="{ active: player.state.repeat !== 'off' }" @click="player.toggleRepeat()" :title="'Repeat: ' + player.state.repeat">
                <i :class="player.state.repeat === 'one' ? 'ph-bold ph-repeat-once' : 'ph-bold ph-repeat'"></i>
              </button>

              <button class="spot-fs-ctrl-btn" :class="{ active: fsTab === 'queue' }" @click="toggleFsTab('queue')" title="Toggle Queue">
                <i class="ph-bold ph-queue"></i>
              </button>
            </div>

            <!-- Scrubber Row -->
            <div class="spot-fs-scrubber-row">
              <span class="spot-fs-time">{{ formatTime(player.state.currentTime) }}</span>
              <div class="spot-fs-progress-track" @mousedown="onSeekMouseDown" ref="progressRef">
                <div class="spot-fs-progress-fill" :style="{ width: progressPercent + '%' }"></div>
                <div class="spot-fs-progress-thumb" :style="{ left: progressPercent + '%' }"></div>
              </div>
              <span class="spot-fs-time">{{ formatTime(player.state.duration) }}</span>
            </div>
          </div>

          <!-- 3. Right Pane: Synced Lyrics OR Queue Stream -->
          <!-- 3A. Synced Lyrics Stream -->
          <div v-if="fsTab === 'lyrics'" class="spot-fs-lyrics-pane" ref="lyricsScrollRef">
            <div v-if="player.state.isSyncedLyrics && player.state.lyrics.length > 0" class="spot-fs-lyrics-stream">
              <div
                v-for="(line, idx) in player.state.lyrics"
                :key="'fs-lyric-' + idx"
                class="spot-fs-lyric-line"
                :class="{ active: idx === player.state.activeLyricIndex, past: idx < player.state.activeLyricIndex }"
                :ref="el => { if (idx === player.state.activeLyricIndex) activeLyricEl = el; }"
                @click="player.seek(line.time)"
              >
                {{ line.text }}
              </div>
            </div>
            <div v-else-if="player.state.rawLyrics" class="spot-fs-plain-lyrics">
              {{ player.state.rawLyrics }}
            </div>
            <div v-else class="spot-fs-empty-lyrics">
              <i class="ph-fill ph-microphone-slash"></i>
              <p>No synced lyrics found for this track.</p>
            </div>
          </div>

          <!-- 3B. Up Next Queue Stream -->
          <div v-else class="spot-fs-queue-pane">
            <div class="spot-fs-queue-header">
              <div class="spot-fs-queue-title">Queue</div>
              <div class="spot-fs-queue-actions">
                <button class="spot-fs-queue-switch-btn" @click="fsTab = 'lyrics'" title="Show Lyrics">
                  <i class="ph-bold ph-microphone-stage"></i> Lyrics
                </button>
                <button v-if="upcomingTracks.length > 0" class="spot-fs-queue-clear-btn" @click="player.clearQueue()">Clear</button>
              </div>
            </div>

            <!-- Now Playing section -->
            <div class="spot-fs-queue-section-title">Now Playing</div>
            <div class="spot-fs-queue-item current">
              <div class="spot-fs-qi-left">
                <div class="spot-fs-qi-anim">
                  <i class="ph-fill ph-speaker-simple-high"></i>
                </div>
                <div class="spot-fs-qi-info">
                  <div class="spot-fs-qi-title">{{ player.state.currentTrack?.title }}</div>
                  <div class="spot-fs-qi-artist">{{ player.state.currentTrack?.artist_name }}</div>
                </div>
              </div>
              <div class="spot-fs-qi-dur">{{ formatTime(player.state.duration) }}</div>
            </div>

            <!-- Next Up section -->
            <div class="spot-fs-queue-section-title" v-if="upcomingTracks.length > 0">Next In Queue</div>
            <div class="spot-fs-queue-list" v-if="upcomingTracks.length > 0">
              <div
                v-for="item in upcomingTracks"
                :key="'fs-q-' + item.index"
                class="spot-fs-queue-item"
                @click="player.playTrack(item.track, null, item.index)"
              >
                <div class="spot-fs-qi-left">
                  <span class="spot-fs-qi-num">{{ item.displayNum }}</span>
                  <img v-if="item.track.cover_path" :src="'/api/music/covers/' + item.track.cover_path.replace('music_covers/', '')" class="spot-fs-qi-thumb" />
                  <div v-else class="spot-fs-qi-thumb-ph">
                    <i class="ph-fill ph-music-note"></i>
                  </div>
                  <div class="spot-fs-qi-info">
                    <div class="spot-fs-qi-title">{{ item.track.title }}</div>
                    <div class="spot-fs-qi-artist spotify-artist-link" :title="'View ' + item.track.artist_name" @click.stop="goToArtist(item.track.artist_name)">{{ item.track.artist_name }}</div>
                  </div>
                </div>
                <div class="spot-fs-qi-right">
                  <span class="spot-fs-qi-dur">{{ formatTime(item.track.duration) }}</span>
                  <button class="spot-fs-qi-del" @click.stop="player.removeFromQueue(item.index)" title="Remove from Queue">
                    <i class="ph-bold ph-x"></i>
                  </button>
                </div>
              </div>
            </div>

            <div v-else class="spot-fs-empty-queue">
              <i class="ph-fill ph-queue"></i>
              <p>No more songs in queue</p>
            </div>
          </div>
        </div>
      </div>
    `,
    setup() {
      const route = VueRouter.useRoute();
      const isMusicRoute = computed(() => route.path.startsWith("/music"));
      const player = window.MusicPlayer;
      const lyricsScrollRef = ref(null);
      const activeLyricEl = ref(null);
      const progressRef = ref(null);
      const volTrackRef = ref(null);
      const fsTab = ref("lyrics"); // 'lyrics' | 'queue'

      function toggleFsTab(tab) {
        fsTab.value = fsTab.value === tab ? "lyrics" : tab;
      }

      const upcomingTracks = computed(() => {
        if (!player.state.queue || player.state.queue.length === 0) return [];
        const curr = player.state.currentIndex;
        return player.state.queue.slice(curr + 1).map((track, i) => ({
          track,
          index: curr + 1 + i,
          displayNum: i + 1,
        }));
      });

      function formatTime(s) {
        if (!s || isNaN(s)) return "0:00";
        const mins = Math.floor(s / 60);
        const secs = Math.floor(s % 60);
        return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
      }

      const progressPercent = computed(() => {
        if (!player.state.duration) return 0;
        return Math.min(100, (player.state.currentTime / player.state.duration) * 100);
      });

      const volIcon = computed(() => {
        if (player.state.isMuted || player.state.volume === 0) return "ph-fill ph-speaker-simple-x";
        if (player.state.volume < 0.5) return "ph-fill ph-speaker-simple-low";
        return "ph-fill ph-speaker-simple-high";
      });

      let isDraggingVol = false;
      let isDraggingSeek = false;

      function updateVolFromY(clientY) {
        if (!volTrackRef.value) return;
        const rect = volTrackRef.value.getBoundingClientRect();
        const bottom = rect.bottom;
        const height = rect.height;
        const pct = Math.max(0, Math.min(1, (bottom - clientY) / height));
        player.setVolume(pct);
      }

      function onVolMouseDown(e) {
        isDraggingVol = true;
        updateVolFromY(e.clientY);
        window.addEventListener("mousemove", onVolMouseMove);
        window.addEventListener("mouseup", onVolMouseUp);
      }

      function onVolMouseMove(e) {
        if (!isDraggingVol) return;
        updateVolFromY(e.clientY);
      }

      function onVolMouseUp() {
        if (isDraggingVol) {
          isDraggingVol = false;
          window.removeEventListener("mousemove", onVolMouseMove);
          window.removeEventListener("mouseup", onVolMouseUp);
        }
      }

      function onVolTouchStart(e) {
        if (e.touches && e.touches.length > 0) {
          isDraggingVol = true;
          updateVolFromY(e.touches[0].clientY);
          window.addEventListener("touchmove", onVolTouchMove, { passive: false });
          window.addEventListener("touchend", onVolTouchEnd);
        }
      }

      function onVolTouchMove(e) {
        if (!isDraggingVol || !e.touches || e.touches.length === 0) return;
        e.preventDefault();
        updateVolFromY(e.touches[0].clientY);
      }

      function onVolTouchEnd() {
        if (isDraggingVol) {
          isDraggingVol = false;
          window.removeEventListener("touchmove", onVolTouchMove);
          window.removeEventListener("touchend", onVolTouchEnd);
        }
      }

      function updateSeekFromX(clientX) {
        if (!progressRef.value || !player.state.duration) return;
        const rect = progressRef.value.getBoundingClientRect();
        const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        player.seek(pos * player.state.duration);
      }

      function onSeekMouseDown(e) {
        isDraggingSeek = true;
        updateSeekFromX(e.clientX);
        window.addEventListener("mousemove", onSeekMouseMove);
        window.addEventListener("mouseup", onSeekMouseUp);
      }

      function onSeekMouseMove(e) {
        if (!isDraggingSeek) return;
        updateSeekFromX(e.clientX);
      }

      function onSeekMouseUp() {
        if (isDraggingSeek) {
          isDraggingSeek = false;
          window.removeEventListener("mousemove", onSeekMouseMove);
          window.removeEventListener("mouseup", onSeekMouseUp);
        }
      }

      const ambientStyle = computed(() => {
        if (player.state.currentTrack?.cover_path) {
          const url = `/api/music/covers/${player.state.currentTrack.cover_path.replace("music_covers/", "")}`;
          return {
            backgroundImage: `url('${url}')`,
          };
        }
        return { background: "radial-gradient(circle at center, #2e3a4e 0%, #121216 80%)" };
      });

      watch(
        () => player.state.activeLyricIndex,
        () => {
          nextTick(() => {
            if (activeLyricEl.value && lyricsScrollRef.value) {
              const container = lyricsScrollRef.value;
              const el = activeLyricEl.value;
              const target = el.offsetTop - container.offsetHeight / 2 + el.offsetHeight / 2;
              container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
            }
          });
        }
      );

      function onKeyDown(e) {
        if (!player.state.fullscreenKaraoke) return;

        const tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) {
          return;
        }

        if (e.key === "Escape") {
          player.toggleKaraoke();
        } else if (e.key === "ArrowUp" || e.code === "ArrowUp") {
          e.preventDefault();
          const currentVol = player.state.isMuted ? 0 : player.state.volume;
          player.setVolume(Math.min(1, Math.round((currentVol + 0.05) * 100) / 100));
        } else if (e.key === "ArrowDown" || e.code === "ArrowDown") {
          e.preventDefault();
          const currentVol = player.state.isMuted ? 0 : player.state.volume;
          player.setVolume(Math.max(0, Math.round((currentVol - 0.05) * 100) / 100));
        } else if (e.key === "ArrowLeft" || e.code === "ArrowLeft") {
          e.preventDefault();
          player.seek(Math.max(0, player.state.currentTime - 5));
        } else if (e.key === "ArrowRight" || e.code === "ArrowRight") {
          e.preventDefault();
          player.seek(Math.min(player.state.duration || 99999, player.state.currentTime + 5));
        } else if (e.code === "Space" || e.key === " ") {
          e.preventDefault();
          player.togglePlay();
        } else if (e.key === "m" || e.key === "M") {
          e.preventDefault();
          player.toggleMute();
        }
      }

      onMounted(() => window.addEventListener("keydown", onKeyDown));
      onUnmounted(() => {
        window.removeEventListener("keydown", onKeyDown);
        window.removeEventListener("mousemove", onVolMouseMove);
        window.removeEventListener("mouseup", onVolMouseUp);
        window.removeEventListener("touchmove", onVolTouchMove);
        window.removeEventListener("touchend", onVolTouchEnd);
        window.removeEventListener("mousemove", onSeekMouseMove);
        window.removeEventListener("mouseup", onSeekMouseUp);
      });

      function goToArtist(artistName) {
        if (!artistName) return;
        if (player.state.fullscreenKaraoke) {
          player.toggleKaraoke();
        }
        if (window.MusicViewDispatcher && window.MusicViewDispatcher.openArtistByName) {
          window.MusicViewDispatcher.openArtistByName(artistName);
        }
      }

      return {
        player,
        lyricsScrollRef,
        activeLyricEl,
        progressRef,
        volTrackRef,
        volIcon,
        fsTab,
        toggleFsTab,
        upcomingTracks,
        formatTime,
        progressPercent,
        ambientStyle,
        isMusicRoute,
        onVolMouseDown,
        onVolTouchStart,
        onSeekMouseDown,
        goToArtist,
      };
    },
  };

  // ─── Main 3-Panel Spotify Experience Page ──────────────────────
  const MusicPage = {
    template: `
      <div class="spotify-app-layout" :class="{ 'has-dock': player && player.state.currentTrack }" :style="rootStyle">
        <!-- 1. LEFT SIDEBAR: Your Library -->
        <aside class="spotify-sidebar">
          <div class="spotify-sidebar-header">
            <div class="spotify-sidebar-top-row">
              <div class="spotify-lib-heading">
                <i class="ph-bold ph-books"></i>
                <span>Your Library</span>
              </div>
              <div class="spotify-lib-tools">
                <button class="spotify-tool-btn" @click="showCreatePlaylistModal = true" title="Create Playlist">
                  <i class="ph-bold ph-plus"></i>
                </button>
                <button class="spotify-tool-btn" @click="triggerScan" :disabled="scanStatus.running" title="Scan Music">
                  <i class="ph-bold ph-arrows-clockwise" :class="{ 'spin-anim': scanStatus.running }"></i>
                </button>
              </div>
            </div>

            <!-- Quick Filter Pills -->
            <div class="spotify-pill-row">
              <button
                v-for="pill in ['all', 'playlists', 'artists', 'albums']"
                :key="pill"
                class="spotify-filter-pill"
                :class="{ active: libraryFilter === pill }"
                @click="libraryFilter = pill"
              >
                {{ pill.charAt(0).toUpperCase() + pill.slice(1) }}
              </button>
            </div>
          </div>

          <!-- Library Scroll List -->
          <div class="spotify-sidebar-list">
            <!-- Pinned: Liked Songs -->
            <div
              v-if="libraryFilter === 'all' || libraryFilter === 'playlists'"
              class="spotify-sidebar-item"
              :class="{ active: currentView === 'liked' }"
              @click="selectView('liked')"
            >
              <div class="spotify-liked-tile">
                <i class="ph-fill ph-heart"></i>
              </div>
              <div class="spotify-item-meta">
                <div class="spotify-item-title">Liked Songs</div>
                <div class="spotify-item-sub">
                  <i class="ph-fill ph-push-pin pinned-icon"></i> Playlist • {{ favorites.length }} songs
                </div>
              </div>
            </div>

            <!-- Custom Playlists -->
            <div
              v-if="libraryFilter === 'all' || libraryFilter === 'playlists'"
              v-for="pl in playlists"
              :key="'pl-' + pl.id"
              class="spotify-sidebar-item"
              :class="{ active: currentView === 'playlist' && selectedPlaylist?.id === pl.id }"
              @click="openPlaylist(pl)"
            >
              <div class="spotify-item-thumb playlist-thumb">
                <i class="ph-bold ph-playlist"></i>
              </div>
              <div class="spotify-item-meta">
                <div class="spotify-item-title">{{ pl.name }}</div>
                <div class="spotify-item-sub">Playlist • {{ pl.track_count || 0 }} songs</div>
              </div>
              <button class="spotify-item-del" @click.stop="deletePlaylist(pl.id)" title="Delete playlist">
                <i class="ph ph-trash"></i>
              </button>
            </div>

            <!-- Artists -->
            <div
              v-if="libraryFilter === 'all' || libraryFilter === 'artists'"
              v-for="ar in artists"
              :key="'ar-' + ar.id"
              class="spotify-sidebar-item"
              :class="{ active: currentView === 'artist' && selectedArtist?.id === ar.id }"
              @click="openArtist(ar)"
            >
              <div class="spotify-item-thumb circle-thumb">
                <img v-if="ar.cover_path" :src="'/api/music/covers/' + ar.cover_path.replace('music_covers/', '')" />
                <i v-else class="ph-fill ph-user"></i>
              </div>
              <div class="spotify-item-meta">
                <div class="spotify-item-title">{{ ar.name }}</div>
                <div class="spotify-item-sub">Artist • {{ ar.track_count || 0 }} songs</div>
              </div>
            </div>

            <!-- Albums -->
            <div
              v-if="libraryFilter === 'all' || libraryFilter === 'albums'"
              v-for="al in albums"
              :key="'al-' + al.id"
              class="spotify-sidebar-item"
              :class="{ active: currentView === 'album' && selectedAlbum?.id === al.id }"
              @click="openAlbum(al)"
            >
              <div class="spotify-item-thumb">
                <img v-if="al.cover_path" :src="'/api/music/covers/' + al.cover_path.replace('music_covers/', '')" />
                <i v-else class="ph-fill ph-disc"></i>
              </div>
              <div class="spotify-item-meta">
                <div class="spotify-item-title">{{ al.title }}</div>
                <div class="spotify-item-sub">Album • {{ al.artist_name || 'Various' }}</div>
              </div>
            </div>
          </div>
        </aside>

        <!-- 2. CENTER MAIN: Dynamic Ambient Hero & Content Feed -->
        <main class="spotify-main" ref="mainContentRef">
          <!-- Ambient Hero Header -->
          <div class="spotify-hero" :class="{ 'is-artist-hero': currentView === 'artist' }" :style="heroAmbientStyle">
            <div class="spotify-hero-cover-box" :class="{ circle: currentView === 'artist' }">
              <img v-if="heroCoverUrl" :src="heroCoverUrl" class="spotify-hero-cover" />
              <div v-else class="spotify-hero-placeholder" :class="heroPlaceholderClass">
                <i :class="heroPlaceholderIcon"></i>
              </div>
            </div>

            <div class="spotify-hero-text">
              <div v-if="currentView === 'artist'" class="artist-verified-badge">
                <i class="ph-fill ph-seal-check"></i> Verified Artist
              </div>
              <span v-else class="spotify-hero-tag">{{ heroTypeTag }}</span>

              <h1 class="spotify-hero-title">{{ heroMainTitle }}</h1>
              <p v-if="heroDescription && currentView !== 'artist'" class="spotify-hero-desc">{{ heroDescription }}</p>
              
              <div class="spotify-hero-stats">
                <span v-if="heroArtistText" class="hero-artist-link spotify-artist-link" @click.stop="openArtistByName(selectedAlbum?.artist_name)">
                  {{ heroArtistText }} • 
                </span>
                <span v-if="currentView === 'artist' && artistAlbums.length > 0">
                  <strong>{{ artistAlbums.length }}</strong> {{ artistAlbums.length === 1 ? 'album' : 'albums' }} • 
                </span>
                <span><strong>{{ displayedTracks.length }}</strong> {{ displayedTracks.length === 1 ? 'song' : 'songs' }}</span>
                <span v-if="heroTotalDuration">, {{ heroTotalDuration }}</span>
              </div>
            </div>
          </div>

          <!-- Scan Status Notice -->
          <transition name="fade">
            <div v-if="showScanBanner && (scanStatus.running || scanStatus.progress)" class="spotify-scan-banner" :class="{ complete: scanStatus.phase === 'complete' }">
              <i :class="scanStatus.running ? 'ph-bold ph-spinner spin-anim' : 'ph-fill ph-check-circle'"></i>
              <span>{{ scanStatus.progress || 'Scanning music files...' }}</span>
            </div>
          </transition>

          <!-- Action Bar: Green Play, Like, Search, Sub-views -->
          <div class="spotify-action-bar">
            <button class="spotify-hero-play-btn" @click="playCurrentViewTracks" :title="isCurrentViewPlaying ? 'Pause' : 'Play'">
              <i :class="isCurrentViewPlaying ? 'ph-fill ph-pause' : 'ph-fill ph-play'"></i>
            </button>

            <button
              v-if="currentView === 'album' || currentView === 'playlist'"
              class="spotify-sub-action-btn"
              @click="toggleFavoriteCurrentView"
              title="Save to Library"
            >
              <i :class="isCurrentViewFavorited ? 'ph-fill ph-heart heart-green' : 'ph-bold ph-heart'"></i>
            </button>

            <div class="spotify-search-box">
              <i class="ph ph-magnifying-glass"></i>
              <input type="text" v-model="searchQuery" placeholder="Search songs, artists, albums..." />
              <button v-if="searchQuery" @click="searchQuery = ''" class="search-clear"><i class="ph ph-x"></i></button>
            </div>

            <div class="spotify-view-switcher">
              <button
                v-for="v in ['tracks', 'albums', 'artists']"
                :key="v"
                class="spotify-view-btn"
                :class="{ active: currentView === v }"
                @click="selectView(v)"
              >
                {{ v.charAt(0).toUpperCase() + v.slice(1) }}
              </button>
            </div>
          </div>

          <!-- Content Views -->
          <div class="spotify-content-body">
            <!-- Artist View: Discography Section -->
            <div v-if="currentView === 'artist' && artistAlbums.length > 0" class="spotify-artist-section">
              <div class="spotify-section-header">
                <h2>Discography</h2>
              </div>
              <div class="spotify-card-grid">
                <div
                  v-for="al in artistAlbums"
                  :key="'ar-al-' + al.id"
                  class="spotify-card"
                  @click="openAlbum(al)"
                >
                  <div class="card-art-box">
                    <img v-if="al.cover_path" :src="'/api/music/covers/' + al.cover_path.replace('music_covers/', '')" />
                    <div v-else class="card-placeholder"><i class="ph-fill ph-disc"></i></div>
                    <button class="card-floating-play" @click.stop="playAlbumDirectly(al)" title="Play Album">
                      <i class="ph-fill ph-play"></i>
                    </button>
                  </div>
                  <div class="card-details">
                    <div class="card-name">{{ al.title }}</div>
                    <div class="card-sub">{{ al.year || 'Album' }} • {{ al.track_count ? al.track_count + ' songs' : 'Album' }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Artist View: Popular Songs Section Header -->
            <div v-if="currentView === 'artist'" class="spotify-section-header">
              <h2>Popular Songs</h2>
            </div>

            <!-- Tracks Table View -->
            <div v-if="currentView === 'tracks' || currentView === 'liked' || currentView === 'playlist' || currentView === 'album' || currentView === 'artist'" class="spotify-track-table">
              <div class="spotify-table-head">
                <div class="th-num">#</div>
                <div class="th-title">Title</div>
                <div class="th-album">Album</div>
                <div class="th-fmt">Format</div>
                <div class="th-time"><i class="ph ph-clock"></i></div>
                <div class="th-acts"></div>
              </div>

              <div
                v-for="(t, idx) in displayedTracks"
                :key="t.id"
                class="spotify-track-row"
                :class="{ playing: player.state.currentTrack?.id === t.id }"
                @click="player.playTrack(t, displayedTracks, idx)"
              >
                <div class="td-num">
                  <span class="num-text" v-if="player.state.currentTrack?.id !== t.id">{{ idx + 1 }}</span>
                  <i v-else-if="player.state.isPlaying" class="ph-fill ph-speaker-simple-high playing-equalizer"></i>
                  <span v-else class="num-text">{{ idx + 1 }}</span>
                  <button class="row-play-btn" title="Play">
                    <i :class="player.state.currentTrack?.id === t.id && player.state.isPlaying ? 'ph-fill ph-pause' : 'ph-fill ph-play'"></i>
                  </button>
                </div>

                <div class="td-title">
                  <img v-if="t.cover_path" :src="'/api/music/covers/' + t.cover_path.replace('music_covers/', '')" class="row-thumb" />
                  <div v-else class="row-thumb-placeholder"><i class="ph-fill ph-music-notes"></i></div>
                  <div class="row-meta">
                    <div class="row-title" :class="{ 'title-green': player.state.currentTrack?.id === t.id }">{{ t.title }}</div>
                    <div class="row-artist spotify-artist-link" @click.stop="openArtistByName(t.artist_name)">{{ t.artist_name || 'Unknown Artist' }}</div>
                  </div>
                </div>

                <div class="td-album" @click.stop="openAlbumById(t.album_id)">
                  <span>{{ t.album_title || 'Unknown Album' }}</span>
                </div>

                <div class="td-fmt">
                  <span class="spotify-badge" :class="t.format">{{ (t.format || 'audio').toUpperCase() }}</span>
                </div>

                <div class="td-time">
                  {{ formatTime(t.duration) }}
                </div>

                <div class="td-acts">
                  <button class="row-action-btn" :class="{ favorited: isFavorited(t.id) }" @click.stop="toggleFavorite(t)" title="Favorite">
                    <i :class="isFavorited(t.id) ? 'ph-fill ph-heart' : 'ph-bold ph-heart'"></i>
                  </button>
                  <button class="row-action-btn" @click.stop="openAddToPlaylistModal(t)" title="Add to playlist">
                    <i class="ph-bold ph-plus-circle"></i>
                  </button>
                </div>
              </div>

              <div v-if="displayedTracks.length === 0" class="spotify-empty-content">
                <i class="ph-bold ph-music-notes-simple"></i>
                <h3>No songs found</h3>
                <p>Scan your music folder or adjust your search filter.</p>
              </div>
            </div>

            <!-- Artist View: About & Biography Section -->
            <div v-if="currentView === 'artist' && (selectedArtist?.biography || selectedArtist?.country || selectedArtist?.genre)" class="spotify-artist-section">
              <div class="spotify-section-header">
                <h2>About</h2>
              </div>
              <div class="spotify-artist-bio-card" :style="artistBioCardStyle">
                <div class="bio-card-overlay">
                  <div class="bio-card-tags" v-if="selectedArtist?.country || selectedArtist?.genre">
                    <span v-if="selectedArtist?.country" class="bio-tag"><i class="ph-bold ph-globe"></i> {{ selectedArtist.country }}</span>
                    <span v-if="selectedArtist?.genre" class="bio-tag"><i class="ph-bold ph-music-notes"></i> {{ selectedArtist.genre }}</span>
                  </div>
                  <p class="bio-card-text">{{ selectedArtist?.biography }}</p>
                </div>
              </div>
            </div>

            <!-- Albums Grid View -->
            <div v-else-if="currentView === 'albums'" class="spotify-card-grid">
              <div
                v-for="al in filteredAlbums"
                :key="al.id"
                class="spotify-card"
                @click="openAlbum(al)"
              >
                <div class="card-art-box">
                  <img v-if="al.cover_path" :src="'/api/music/covers/' + al.cover_path.replace('music_covers/', '')" />
                  <div v-else class="card-placeholder"><i class="ph-fill ph-disc"></i></div>
                  <button class="card-floating-play" @click.stop="playAlbumDirectly(al)" title="Play Album">
                    <i class="ph-fill ph-play"></i>
                  </button>
                </div>
                <div class="card-details">
                  <div class="card-name">{{ al.title }}</div>
                  <div class="card-sub"><span class="spotify-artist-link" @click.stop="openArtistByName(al.artist_name)">{{ al.artist_name || 'Album' }}</span> • {{ al.year || '' }}</div>
                </div>
              </div>
            </div>

            <!-- Artists Grid View -->
            <div v-else-if="currentView === 'artists'" class="spotify-card-grid">
              <div
                v-for="ar in filteredArtists"
                :key="ar.id"
                class="spotify-card artist-style"
                @click="openArtist(ar)"
              >
                <div class="card-art-box circle">
                  <img v-if="ar.cover_path" :src="'/api/music/covers/' + ar.cover_path.replace('music_covers/', '')" />
                  <div v-else class="card-placeholder"><i class="ph-fill ph-user"></i></div>
                  <button class="card-floating-play" @click.stop="playArtistDirectly(ar)" title="Play Artist">
                    <i class="ph-fill ph-play"></i>
                  </button>
                </div>
                <div class="card-details center">
                  <div class="card-name">{{ ar.name }}</div>
                  <div class="card-sub">Artist • {{ ar.track_count || 0 }} songs</div>
                </div>
              </div>
            </div>
          </div>
        </main>

        <!-- 3. RIGHT PANEL: Collapsible Live Synced Lyrics & Up Next Queue -->
        <aside class="spotify-right-panel" v-if="player.state.rightPanelOpen">
          <div class="spotify-rp-header">
            <div class="spotify-rp-nav">
              <button
                class="spotify-rp-tab"
                :class="{ active: player.state.rightPanelTab === 'lyrics' }"
                @click="player.state.rightPanelTab = 'lyrics'"
              >
                <i class="ph-bold ph-microphone-stage"></i> Lyrics
              </button>
              <button
                class="spotify-rp-tab"
                :class="{ active: player.state.rightPanelTab === 'queue' }"
                @click="player.state.rightPanelTab = 'queue'"
              >
                <i class="ph-bold ph-queue"></i> Queue ({{ player.state.queue.length }})
              </button>
            </div>

            <button class="spotify-rp-close" @click="player.state.rightPanelOpen = false" title="Close Panel">
              <i class="ph-bold ph-x"></i>
            </button>
          </div>

          <!-- Panel Body: Lyrics -->
          <div v-if="player.state.rightPanelTab === 'lyrics'" class="spotify-rp-body lyrics-scroll" ref="panelLyricsRef">
            <div v-if="player.state.isSyncedLyrics && player.state.lyrics.length > 0" class="panel-synced-lyrics">
              <div
                v-for="(line, idx) in player.state.lyrics"
                :key="'rp-' + idx"
                class="panel-lyric-line"
                :class="{ active: idx === player.state.activeLyricIndex, past: idx < player.state.activeLyricIndex }"
                :ref="el => { if (idx === player.state.activeLyricIndex) activePanelLyricEl = el; }"
                @click="player.seek(line.time)"
              >
                {{ line.text }}
              </div>
            </div>
            <div v-else-if="player.state.rawLyrics" class="panel-plain-lyrics">
              {{ player.state.rawLyrics }}
            </div>
            <div v-else class="panel-empty-lyrics">
              <i class="ph-fill ph-microphone-slash"></i>
              <p>No lyrics found for this track (.lrc or embedded tags).</p>
            </div>
          </div>

          <!-- Panel Body: Queue -->
          <div v-else-if="player.state.rightPanelTab === 'queue'" class="spotify-rp-body queue-scroll">
            <div class="panel-queue-header">
              <div class="queue-heading">Now Playing</div>
            </div>
            <div v-if="player.state.currentTrack" class="panel-queue-item current">
              <img v-if="player.state.currentTrack.cover_path" :src="'/api/music/covers/' + player.state.currentTrack.cover_path.replace('music_covers/', '')" class="queue-thumb" />
              <div class="queue-text">
                <div class="queue-title">{{ player.state.currentTrack.title }}</div>
                <div class="queue-artist spotify-artist-link" @click.stop="openArtistByName(player.state.currentTrack.artist_name)">{{ player.state.currentTrack.artist_name }}</div>
              </div>
            </div>

            <div class="panel-queue-header" style="margin-top:18px;">
              <div class="queue-heading">Next in Queue</div>
              <button class="panel-clear-queue-btn" @click="player.clearQueue" v-if="player.state.queue.length > 1">Clear Queue</button>
            </div>

            <div class="panel-queue-list">
              <div
                v-for="(qt, qidx) in player.state.queue.slice(player.state.currentIndex + 1)"
                :key="qt.id + '-' + qidx"
                class="panel-queue-item"
                @click="player.playTrack(qt, null, player.state.currentIndex + 1 + qidx)"
              >
                <span class="queue-idx-text">{{ qidx + 1 }}</span>
                <img v-if="qt.cover_path" :src="'/api/music/covers/' + qt.cover_path.replace('music_covers/', '')" class="queue-thumb" />
                <div class="queue-text">
                  <div class="queue-title">{{ qt.title }}</div>
                  <div class="queue-artist spotify-artist-link" @click.stop="openArtistByName(qt.artist_name)">{{ qt.artist_name }}</div>
                </div>
                <button class="queue-remove-btn" @click.stop="player.removeFromQueue(player.state.currentIndex + 1 + qidx)">
                  <i class="ph ph-x"></i>
                </button>
              </div>
            </div>
          </div>
        </aside>

        <!-- Create Playlist Modal -->
        <div class="modal-backdrop" v-if="showCreatePlaylistModal" @click.self="showCreatePlaylistModal = false">
          <div class="modal-card">
            <div class="modal-header">
              <h3>Create Playlist</h3>
              <button class="modal-close-btn" @click="showCreatePlaylistModal = false"><i class="ph ph-x"></i></button>
            </div>
            <div class="modal-body">
              <label class="form-label">Playlist Name</label>
              <input type="text" v-model="newPlaylistName" class="form-input" placeholder="e.g. Synthwave Favorites" />
              <label class="form-label" style="margin-top:12px;">Description (Optional)</label>
              <textarea v-model="newPlaylistDesc" class="form-input" placeholder="Give your playlist a description..."></textarea>
            </div>
            <div class="modal-footer">
              <button class="btn btn-outline" @click="showCreatePlaylistModal = false">Cancel</button>
              <button class="btn btn-primary" @click="createPlaylist" :disabled="!newPlaylistName.trim()">Create</button>
            </div>
          </div>
        </div>

        <!-- Add to Playlist Modal -->
        <div class="modal-backdrop" v-if="trackToAddToPlaylist" @click.self="trackToAddToPlaylist = null">
          <div class="modal-card">
            <div class="modal-header">
              <h3>Add to Playlist</h3>
              <button class="modal-close-btn" @click="trackToAddToPlaylist = null"><i class="ph ph-x"></i></button>
            </div>
            <div class="modal-body">
              <p style="margin-bottom:12px;color:var(--text-muted)">Add <strong>{{ trackToAddToPlaylist.title }}</strong> to:</p>
              <div v-if="playlists.length > 0" class="playlist-select-list">
                <div
                  v-for="p in playlists"
                  :key="p.id"
                  class="playlist-select-item"
                  @click="addTrackToPlaylist(p.id)"
                >
                  <i class="ph-bold ph-playlist"></i>
                  <span>{{ p.name }}</span>
                </div>
              </div>
              <div v-else style="padding:16px;text-align:center;color:var(--text-muted)">
                No playlists found. Create one first!
              </div>
            </div>
          </div>
        </div>
      </div>
    `,
    setup() {
      const player = window.MusicPlayer;
      const currentView = ref("tracks");
      const libraryFilter = ref("all");
      const searchQuery = ref("");
      const tracks = ref([]);
      const albums = ref([]);
      const artists = ref([]);
      const favorites = ref([]);
      const playlists = ref([]);
      const scanStatus = reactive({ running: false, phase: "idle", progress: "", percent: 0 });
      const showScanBanner = ref(false);
      let bannerTimeout = null;

      const selectedPlaylist = ref(null);
      const selectedAlbum = ref(null);
      const selectedArtist = ref(null);

      const showCreatePlaylistModal = ref(false);
      const newPlaylistName = ref("");
      const newPlaylistDesc = ref("");
      const trackToAddToPlaylist = ref(null);

      const panelLyricsRef = ref(null);
      const activePanelLyricEl = ref(null);
      const mainContentRef = ref(null);

      function formatTime(s) {
        if (!s || isNaN(s)) return "0:00";
        const mins = Math.floor(s / 60);
        const secs = Math.floor(s % 60);
        return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
      }

      async function loadData() {
        try {
          const [tr, al, ar, fav, pl] = await Promise.all([
            API.get("/api/music/tracks"),
            API.get("/api/music/albums"),
            API.get("/api/music/artists"),
            API.get("/api/music/favorites"),
            API.get("/api/music/playlists"),
          ]);
          tracks.value = tr || [];
          albums.value = al || [];
          artists.value = ar || [];
          favorites.value = fav || [];
          playlists.value = pl || [];
        } catch (e) {
          console.error("[MusicPage] Load data failed:", e);
        }
      }

      async function reloadFavorites() {
        try {
          const fav = await API.get("/api/music/favorites");
          favorites.value = fav || [];
        } catch (e) {}
      }

      const displayedTracks = computed(() => {
        let baseList = [];
        if (currentView.value === "liked") {
          baseList = favorites.value;
        } else if (currentView.value === "playlist" && selectedPlaylist.value) {
          baseList = selectedPlaylist.value.tracks || [];
        } else if (currentView.value === "album" && selectedAlbum.value) {
          baseList = tracks.value.filter((t) => t.album_id === selectedAlbum.value.id);
        } else if (currentView.value === "artist" && selectedArtist.value) {
          baseList = tracks.value.filter(
            (t) =>
              t.artist_id === selectedArtist.value.id ||
              (t.artist_name && t.artist_name.toLowerCase() === selectedArtist.value.name.toLowerCase())
          );
        } else {
          baseList = tracks.value;
        }

        if (!searchQuery.value.trim()) return baseList;
        const q = searchQuery.value.toLowerCase();
        return baseList.filter(
          (t) =>
            (t.title && t.title.toLowerCase().includes(q)) ||
            (t.artist_name && t.artist_name.toLowerCase().includes(q)) ||
            (t.album_title && t.album_title.toLowerCase().includes(q))
        );
      });

      const filteredAlbums = computed(() => {
        if (!searchQuery.value.trim()) return albums.value;
        const q = searchQuery.value.toLowerCase();
        return albums.value.filter(
          (a) =>
            (a.title && a.title.toLowerCase().includes(q)) ||
            (a.artist_name && a.artist_name.toLowerCase().includes(q))
        );
      });

      const filteredArtists = computed(() => {
        if (!searchQuery.value.trim()) return artists.value;
        const q = searchQuery.value.toLowerCase();
        return artists.value.filter((a) => a.name && a.name.toLowerCase().includes(q));
      });

      const artistAlbums = computed(() => {
        if (!selectedArtist.value) return [];
        const aId = selectedArtist.value.id;
        const aName = (selectedArtist.value.name || "").toLowerCase();
        return albums.value.filter(
          (a) => a.artist_id === aId || (a.artist_name && a.artist_name.toLowerCase() === aName)
        );
      });

      const artistBackdropUrl = computed(() => {
        if (!selectedArtist.value) return null;
        const p = selectedArtist.value.fanart_path || selectedArtist.value.backdrop_path || selectedArtist.value.cover_path;
        if (p) return "/api/music/covers/" + p.replace("music_covers/", "");
        return null;
      });

      const artistBioCardStyle = computed(() => {
        if (!selectedArtist.value) return {};
        const p = selectedArtist.value.fanart_path || selectedArtist.value.cover_path;
        if (p) {
          const url = "/api/music/covers/" + p.replace("music_covers/", "");
          return {
            backgroundImage: `linear-gradient(to top, rgba(14, 16, 20, 0.95) 0%, rgba(14, 16, 20, 0.65) 60%, rgba(14, 16, 20, 0.25) 100%), url('${url}')`,
          };
        }
        return {
          background: "linear-gradient(135deg, rgba(35, 40, 50, 0.8) 0%, rgba(18, 20, 26, 0.9) 100%)",
        };
      });

      // Dynamic Adaptive Hero Metadata
      const heroTypeTag = computed(() => {
        switch (currentView.value) {
          case "liked": return "PLAYLIST";
          case "playlist": return "PLAYLIST";
          case "album": return "ALBUM";
          case "artist": return "ARTIST";
          case "albums": return "COLLECTION";
          case "artists": return "COLLECTION";
          default: return "LIBRARY";
        }
      });

      const heroMainTitle = computed(() => {
        switch (currentView.value) {
          case "liked": return "Liked Songs";
          case "playlist": return selectedPlaylist.value?.name || "Playlist";
          case "album": return selectedAlbum.value?.title || "Album";
          case "artist": return selectedArtist.value?.name || "Artist";
          case "albums": return "Albums";
          case "artists": return "Artists";
          default: return "All Songs";
        }
      });

      const heroDescription = computed(() => {
        if (currentView.value === "liked") return "Your personal collection of saved favorite tracks.";
        if (currentView.value === "playlist") return selectedPlaylist.value?.description || "";
        if (currentView.value === "album") return selectedAlbum.value?.genre || "";
        if (currentView.value === "tracks") return "Lossless and high-fidelity tracks directly from your storage.";
        return "";
      });

      const heroArtistText = computed(() => {
        if (currentView.value === "album") return selectedAlbum.value?.artist_name || "";
        return "";
      });

      const heroCoverUrl = computed(() => {
        if (currentView.value === "album" && selectedAlbum.value?.cover_path) {
          return "/api/music/covers/" + selectedAlbum.value.cover_path.replace("music_covers/", "");
        }
        if (currentView.value === "artist" && selectedArtist.value?.cover_path) {
          return "/api/music/covers/" + selectedArtist.value.cover_path.replace("music_covers/", "");
        }
        if (currentView.value === "tracks" && tracks.value.length > 0 && tracks.value[0].cover_path) {
          return "/api/music/covers/" + tracks.value[0].cover_path.replace("music_covers/", "");
        }
        return null;
      });

      const heroPlaceholderClass = computed(() => {
        if (currentView.value === "liked") return "liked-tile";
        if (currentView.value === "artist") return "circle-tile";
        return "";
      });

      const heroPlaceholderIcon = computed(() => {
        if (currentView.value === "liked") return "ph-fill ph-heart";
        if (currentView.value === "artist") return "ph-fill ph-user";
        if (currentView.value === "album") return "ph-fill ph-disc";
        return "ph-fill ph-music-notes";
      });

      const heroTotalDuration = computed(() => {
        const totalSecs = displayedTracks.value.reduce((acc, t) => acc + (t.duration || 0), 0);
        if (!totalSecs) return "";
        const mins = Math.round(totalSecs / 60);
        if (mins >= 60) {
          const hrs = Math.floor(mins / 60);
          const rem = mins % 60;
          return `${hrs} hr ${rem} min`;
        }
        return `${mins} min`;
      });

      const heroAmbientStyle = computed(() => {
        if (currentView.value === "liked") {
          return { background: "linear-gradient(180deg, rgba(80, 56, 160, 0.85) 0%, rgba(18, 18, 18, 0.95) 100%)" };
        }
        if (currentView.value === "artist" && artistBackdropUrl.value) {
          return {
            backgroundImage: `linear-gradient(to bottom, rgba(10, 10, 14, 0.3) 0%, rgba(18, 18, 22, 0.75) 60%, rgba(18, 18, 22, 0.98) 100%), url('${artistBackdropUrl.value}')`,
            backgroundSize: "cover",
            backgroundPosition: "center 25%",
          };
        }
        return {
          background: `var(--spotify-header-gradient, linear-gradient(180deg, rgba(30, 215, 96, 0.45) 0%, rgba(18, 18, 18, 0.95) 100%))`,
        };
      });

      const rootStyle = computed(() => ({
        "--spotify-accent": player.state.dominantColor || "#1ed760",
        "--spotify-accent-glow": player.state.accentGlow || "rgba(30, 215, 96, 0.35)",
      }));

      const isCurrentViewPlaying = computed(() => {
        if (!player.state.isPlaying || !player.state.currentTrack) return false;
        return displayedTracks.value.some((t) => t.id === player.state.currentTrack.id);
      });

      const isCurrentViewFavorited = computed(() => {
        if (currentView.value === "album" && selectedAlbum.value) {
          const albumTracks = tracks.value.filter((t) => t.album_id === selectedAlbum.value.id);
          return albumTracks.length > 0 && albumTracks.every((t) => isFavorited(t.id));
        }
        return false;
      });

      function isFavorited(trackId) {
        return favorites.value.some((f) => f.id === trackId);
      }

      async function toggleFavorite(track) {
        try {
          const res = await API.post("/api/music/favorites", { track_id: track.id });
          if (res && res.ok) {
            track.is_favorite = res.favorited;
            if (player.state.currentTrack?.id === track.id) {
              player.state.currentTrack.is_favorite = res.favorited;
            }
            await reloadFavorites();
          }
        } catch (e) {
          console.error("[MusicPage] Toggle favorite failed:", e);
        }
      }

      async function toggleFavoriteCurrentView() {
        if (currentView.value === "album" && selectedAlbum.value) {
          const albumTracks = tracks.value.filter((t) => t.album_id === selectedAlbum.value.id);
          const shouldFav = !isCurrentViewFavorited.value;
          for (const t of albumTracks) {
            if (isFavorited(t.id) !== shouldFav) {
              await toggleFavorite(t);
            }
          }
        }
      }

      function selectView(v) {
        currentView.value = v;
        if (v !== "album") selectedAlbum.value = null;
        if (v !== "artist") selectedArtist.value = null;
        if (v !== "playlist") selectedPlaylist.value = null;
        if (mainContentRef.value) mainContentRef.value.scrollTo({ top: 0, behavior: "smooth" });
      }

      function playCurrentViewTracks() {
        if (displayedTracks.value.length === 0) return;
        if (isCurrentViewPlaying.value) {
          player.togglePlay();
        } else {
          player.playTrack(displayedTracks.value[0], displayedTracks.value, 0);
        }
      }

      async function openAlbum(album) {
        selectedAlbum.value = album;
        currentView.value = "album";
        if (album.cover_path) {
          const url = `/api/music/covers/${album.cover_path.replace("music_covers/", "")}`;
          document.documentElement.style.setProperty(
            "--spotify-header-gradient",
            `linear-gradient(180deg, rgba(80, 80, 100, 0.75) 0%, rgba(18, 18, 18, 0.95) 100%)`
          );
        }
        if (mainContentRef.value) mainContentRef.value.scrollTo({ top: 0, behavior: "smooth" });
      }

      function playAlbumDirectly(album) {
        const alTracks = tracks.value.filter((t) => t.album_id === album.id);
        if (alTracks.length > 0) {
          player.playTrack(alTracks[0], alTracks, 0);
        }
      }

      function openAlbumById(albumId) {
        if (!albumId) return;
        const al = albums.value.find((a) => a.id === albumId);
        if (al) openAlbum(al);
      }

      async function openArtist(artist) {
        if (!artist) return;
        selectedArtist.value = artist;
        currentView.value = "artist";
        if (mainContentRef.value) mainContentRef.value.scrollTo({ top: 0, behavior: "smooth" });

        // Auto-fetch artist metadata/biography if missing and has valid ID
        if (!artist.biography && artist.id) {
          try {
            const res = await API.post(`/api/music/artists/${artist.id}/fetch-info`);
            if (res && res.artist) {
              Object.assign(selectedArtist.value, res.artist);
              const idx = artists.value.findIndex((a) => a.id === artist.id);
              if (idx !== -1) Object.assign(artists.value[idx], res.artist);
            }
          } catch (e) {
            // Silently fallback if offline or no TheAudioDB match
          }
        }
      }

      function openArtistByName(artistName) {
        if (!artistName) return;
        const ar = artists.value.find((a) => a.name.toLowerCase() === artistName.toLowerCase());
        if (ar) {
          openArtist(ar);
        } else {
          // Check if there are tracks matching this artist name
          const arTracks = tracks.value.filter(
            (t) => t.artist_name && t.artist_name.toLowerCase() === artistName.toLowerCase()
          );
          if (arTracks.length > 0) {
            const virtualArtist = {
              id: arTracks[0].artist_id || 0,
              name: artistName,
              cover_path: arTracks[0].cover_path || null,
              track_count: arTracks.length,
            };
            openArtist(virtualArtist);
          } else {
            searchQuery.value = artistName;
            currentView.value = "tracks";
          }
        }
      }

      function playArtistDirectly(artist) {
        const arTracks = tracks.value.filter(
          (t) =>
            t.artist_id === artist.id ||
            (t.artist_name && t.artist_name.toLowerCase() === artist.name.toLowerCase())
        );
        if (arTracks.length > 0) {
          player.playTrack(arTracks[0], arTracks, 0);
        }
      }

      async function openPlaylist(playlist) {
        try {
          const fullPl = await API.get(`/api/music/playlists/${playlist.id}`);
          selectedPlaylist.value = fullPl || playlist;
          currentView.value = "playlist";
          if (mainContentRef.value) mainContentRef.value.scrollTo({ top: 0, behavior: "smooth" });
        } catch (e) {
          selectedPlaylist.value = playlist;
          currentView.value = "playlist";
        }
      }

      async function createPlaylist() {
        if (!newPlaylistName.value.trim()) return;
        try {
          const res = await API.post("/api/music/playlists", {
            name: newPlaylistName.value.trim(),
            description: newPlaylistDesc.value.trim(),
          });
          if (res && res.id) {
            newPlaylistName.value = "";
            newPlaylistDesc.value = "";
            showCreatePlaylistModal.value = false;
            const updated = await API.get("/api/music/playlists");
            playlists.value = updated || [];
          }
        } catch (e) {
          console.error("[MusicPage] Create playlist failed:", e);
        }
      }

      async function deletePlaylist(playlistId) {
        if (!confirm("Are you sure you want to delete this playlist?")) return;
        try {
          await API.delete(`/api/music/playlists/${playlistId}`);
          playlists.value = playlists.value.filter((p) => p.id !== playlistId);
          if (selectedPlaylist.value?.id === playlistId) {
            selectView("tracks");
          }
        } catch (e) {
          console.error("[MusicPage] Delete playlist failed:", e);
        }
      }

      function openAddToPlaylistModal(track) {
        trackToAddToPlaylist.value = track;
      }

      async function addTrackToPlaylist(playlistId) {
        if (!trackToAddToPlaylist.value) return;
        try {
          await API.post(`/api/music/playlists/${playlistId}/tracks`, {
            track_id: trackToAddToPlaylist.value.id,
          });
          trackToAddToPlaylist.value = null;
          const updated = await API.get("/api/music/playlists");
          playlists.value = updated || [];
        } catch (e) {
          console.error("[MusicPage] Add track to playlist failed:", e);
        }
      }

      // Scanner Poll
      let scanTimer = null;
      async function triggerScan() {
        try {
          if (bannerTimeout) clearTimeout(bannerTimeout);
          showScanBanner.value = true;
          scanStatus.running = true;
          scanStatus.progress = "Starting music scan...";
          await API.post("/api/music/scan");
          pollScanStatus();
        } catch (e) {
          console.error("[MusicPage] Scan trigger failed:", e);
          showScanBanner.value = false;
        }
      }

      async function pollScanStatus() {
        try {
          const st = await API.get("/api/music/scan/status");
          if (st) {
            const wasRunning = scanStatus.running;
            Object.assign(scanStatus, st);
            if (st.running) {
              showScanBanner.value = true;
              scanTimer = setTimeout(pollScanStatus, 1500);
            } else {
              if (wasRunning && st.phase === "complete") {
                loadData();
                showScanBanner.value = true;
                if (bannerTimeout) clearTimeout(bannerTimeout);
                bannerTimeout = setTimeout(() => {
                  showScanBanner.value = false;
                }, 3000);
              } else if (!wasRunning) {
                // Keep banner hidden if scan was already completed before loading
                showScanBanner.value = false;
              }
            }
          }
        } catch (e) {}
      }

      // Auto-scroll synced lyrics in right panel
      watch(
        () => player.state.activeLyricIndex,
        () => {
          nextTick(() => {
            if (activePanelLyricEl.value && panelLyricsRef.value) {
              const container = panelLyricsRef.value;
              const el = activePanelLyricEl.value;
              const target = el.offsetTop - container.offsetHeight / 2 + el.offsetHeight / 2;
              container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
            }
          });
        }
      );

      onMounted(() => {
        loadData();
        pollScanStatus();
        window.MusicViewDispatcher = {
          openArtist,
          openArtistByName,
          openAlbum,
          openPlaylist,
          selectView,
        };
      });

      onUnmounted(() => {
        if (scanTimer) clearTimeout(scanTimer);
        if (bannerTimeout) clearTimeout(bannerTimeout);
        if (window.MusicViewDispatcher && window.MusicViewDispatcher.openArtist === openArtist) {
          window.MusicViewDispatcher = null;
        }
      });

      return {
        showScanBanner,
        player,
        currentView,
        libraryFilter,
        searchQuery,
        tracks,
        albums,
        artists,
        favorites,
        playlists,
        selectedPlaylist,
        selectedAlbum,
        selectedArtist,
        displayedTracks,
        artistAlbums,
        artistBioCardStyle,
        filteredAlbums,
        filteredArtists,
        scanStatus,
        showCreatePlaylistModal,
        newPlaylistName,
        newPlaylistDesc,
        trackToAddToPlaylist,
        panelLyricsRef,
        activePanelLyricEl,
        mainContentRef,
        rootStyle,
        heroTypeTag,
        heroMainTitle,
        heroDescription,
        heroArtistText,
        heroCoverUrl,
        heroPlaceholderClass,
        heroPlaceholderIcon,
        heroTotalDuration,
        heroAmbientStyle,
        isCurrentViewPlaying,
        isCurrentViewFavorited,
        formatTime,
        isFavorited,
        toggleFavorite,
        toggleFavoriteCurrentView,
        selectView,
        playCurrentViewTracks,
        openAlbum,
        openAlbumById,
        playAlbumDirectly,
        openArtist,
        openArtistByName,
        playArtistDirectly,
        openPlaylist,
        createPlaylist,
        deletePlaylist,
        openAddToPlaylistModal,
        addTrackToPlaylist,
        triggerScan,
      };
    },
  };

  // Expose components globally
  window.GlobalMusicDock = GlobalMusicDock;
  window.NowPlayingModal = NowPlayingModal;
  window.MusicPage = MusicPage;
})();
