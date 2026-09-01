window.PlayerPage = Vue.defineComponent({
  template: `
    <div class="player-container" ref="containerRef" @mousemove="onMouseMove" @mouseleave="hideControls" @click="togglePlayPause">
      <video
        ref="videoRef"
        class="video-element"
        :src="videoSrc"
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @play="isPlaying = true"
        @pause="isPlaying = false"
        @waiting="isBuffering = true"
        @playing="isBuffering = false"
        @error="onError"
        crossorigin="anonymous"
      ></video>
      
      <!-- Loading / Error States -->
      <div v-if="isBuffering" class="player-spinner"><i class="ph ph-spinner ph-spin"></i></div>
      <div v-if="error" class="player-error">{{ error }}</div>

      <!-- Controls Overlay -->
      <transition name="fade">
        <div class="player-controls" v-show="showControls" @click.stop>
          <div class="controls-header">
            <button class="btn-icon" @click="goBack"><i class="ph ph-arrow-left"></i></button>
            <div class="title-container">
              <h2>{{ mediaTitle }}</h2>
            </div>
          </div>
          
          <div class="controls-footer">
            <div class="progress-bar-container" @click="seek">
              <div class="progress-bar" :style="{ width: progressPercent + '%' }"></div>
            </div>
            
            <div class="controls-row">
              <div class="left-controls">
                <button class="btn-icon" @click="togglePlayPause">
                  <i :class="isPlaying ? 'ph ph-pause' : 'ph ph-play'"></i>
                </button>
                <span class="time-display">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
              </div>
              
              <div class="right-controls">
                <button class="btn-icon" @click="toggleFullscreen">
                  <i :class="isFullscreen ? 'ph ph-corners-in' : 'ph ph-corners-out'"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      </transition>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute();
    const router = VueRouter.useRouter();
    
    const mediaId = Vue.ref(route.params.id);
    const videoRef = Vue.ref(null);
    const containerRef = Vue.ref(null);
    
    const mediaTitle = Vue.ref("Loading...");
    const videoSrc = Vue.ref("");
    
    const isPlaying = Vue.ref(false);
    const isBuffering = Vue.ref(false);
    const error = Vue.ref("");
    
    const currentTime = Vue.ref(0);
    const duration = Vue.ref(0);
    
    const showControls = Vue.ref(true);
    const isFullscreen = Vue.ref(false);
    
    let controlsTimeout = null;

    const progressPercent = Vue.computed(() => {
      return duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0;
    });

    const formatTime = (time) => {
      if (!time || isNaN(time)) return "00:00";
      const h = Math.floor(time / 3600);
      const m = Math.floor((time % 3600) / 60);
      const s = Math.floor(time % 60);
      if (h > 0) return \`\${h}:\${m.toString().padStart(2, '0')}:\${s.toString().padStart(2, '0')}\`;
      return \`\${m.toString().padStart(2, '0')}:\${s.toString().padStart(2, '0')}\`;
    };

    const fetchMediaInfo = async () => {
      try {
        const data = await window.API.get(\`/api/media/\${mediaId.value}\`);
        mediaTitle.value = data.title || "Unknown Media";
        videoSrc.value = \`/api/stream/\${mediaId.value}\`;
      } catch (err) {
        error.value = "Failed to load media info";
      }
    };

    const togglePlayPause = () => {
      if (videoRef.value) {
        if (videoRef.value.paused) {
          videoRef.value.play().catch(e => console.error("Playback failed:", e));
        } else {
          videoRef.value.pause();
        }
      }
    };

    const onTimeUpdate = () => {
      if (videoRef.value) {
        currentTime.value = videoRef.value.currentTime;
      }
    };

    const onLoadedMetadata = () => {
      if (videoRef.value) {
        duration.value = videoRef.value.duration;
      }
    };

    const onError = () => {
      error.value = "An error occurred during playback";
      isBuffering.value = false;
    };

    const seek = (e) => {
      if (!videoRef.value) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const pos = (e.clientX - rect.left) / rect.width;
      videoRef.value.currentTime = pos * duration.value;
    };

    const onMouseMove = () => {
      showControls.value = true;
      resetControlsTimeout();
    };

    const hideControls = () => {
      if (isPlaying.value) showControls.value = false;
    };

    const resetControlsTimeout = () => {
      clearTimeout(controlsTimeout);
      controlsTimeout = setTimeout(() => {
        if (isPlaying.value) showControls.value = false;
      }, 3000);
    };

    const toggleFullscreen = async () => {
      if (!document.fullscreenElement) {
        if (containerRef.value.requestFullscreen) {
          await containerRef.value.requestFullscreen();
          isFullscreen.value = true;
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
          isFullscreen.value = false;
        }
      }
    };
    
    const goBack = () => {
      router.back();
    };

    const saveProgress = async () => {
      if (currentTime.value > 0 && duration.value > 0 && window.store?.profile?.id) {
        try {
          await window.API.post(\`/api/profiles/\${window.store.profile.id}/progress\`, {
            media_id: mediaId.value,
            progress_time: currentTime.value,
            duration: duration.value
          });
        } catch (e) {
          console.warn("Failed to save progress", e);
        }
      }
    };

    // Keyboard Shortcuts
    const handleKeydown = (e) => {
      if (e.key === " ") {
        e.preventDefault();
        togglePlayPause();
      } else if (e.key === "ArrowRight") {
        if (videoRef.value) videoRef.value.currentTime += 10;
      } else if (e.key === "ArrowLeft") {
        if (videoRef.value) videoRef.value.currentTime -= 10;
      } else if (e.key === "f" || e.key === "F") {
        toggleFullscreen();
      }
    };

    Vue.onMounted(() => {
      fetchMediaInfo();
      window.addEventListener("keydown", handleKeydown);
      resetControlsTimeout();
    });

    Vue.onUnmounted(() => {
      saveProgress();
      window.removeEventListener("keydown", handleKeydown);
      clearTimeout(controlsTimeout);
      if (videoRef.value) {
        videoRef.value.pause();
        videoRef.value.src = "";
        videoRef.value.load();
      }
    });

    return {
      videoRef,
      containerRef,
      mediaTitle,
      videoSrc,
      isPlaying,
      isBuffering,
      error,
      currentTime,
      duration,
      showControls,
      isFullscreen,
      progressPercent,
      formatTime,
      togglePlayPause,
      onTimeUpdate,
      onLoadedMetadata,
      onError,
      seek,
      onMouseMove,
      hideControls,
      toggleFullscreen,
      goBack
    };
  }
});
