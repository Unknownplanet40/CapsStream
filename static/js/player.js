(function () {
const PlayerPage = {
  name: "PlayerPage",
  template: `
    <div
      class="custom-player-wrapper"
      @mousemove="showControls"
      @touchstart="onPlayerTouchStart"
      @touchmove="onPlayerTouchMove"
      @touchend="onPlayerTouchEnd"
      @touchcancel="onPlayerTouchCancel"
      @click="handleContainerClick"
      @dblclick="handleContainerDblClick"
    >
      <!-- Shortcuts Modal -->
      <shortcuts-modal v-if="showShortcuts" @close="showShortcuts = false" />
      <!-- Native Video Surface -->
      <video
        ref="videoRef"
        class="custom-player-video"
        :class="'fit-' + (aspectRatioFit || 'contain')"
        :style="{ filter: 'brightness(' + (brightnessLevel / 100) + ')' }"
        crossorigin="anonymous"
        playsinline
        webkit-playsinline="true"
        x5-playsinline="true"
        x5-video-player-type="h5-page"
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
          <i :class="'ph-bold ' + (playerAch.icon && playerAch.icon.startsWith('ph-') ? playerAch.icon : 'ph-trophy')" style="font-size:1.15rem;margin-right:6px"></i>
          <span>{{ playerAch.title }}</span>
        </div>
      </transition>



      <!-- Child Screen Lock Overlay -->
      <div v-if="isChildLocked" class="player-child-lock-overlay" @click.stop="promptUnlockHint">
        <transition name="fade">
          <div v-if="showUnlockHint" class="child-lock-hint-pill" @click.stop="toggleChildLock">
            <i class="ph-fill ph-lock-key"></i>
            <span>Screen Locked • Click to Unlock</span>
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

      <!-- Brightness Swipe HUD (Left side gesture) -->
      <transition name="fade">
        <div v-if="brightnessHUD" class="player-hud-pill">
          <i class="ph-fill ph-sun player-hud-icon"></i>
          <div class="player-hud-bar">
            <div class="player-hud-fill" :style="{ width: brightnessLevel + '%' }"></div>
          </div>
          <span class="player-hud-value">{{ brightnessLevel }}%</span>
        </div>
      </transition>

      <!-- Double-Tap Seek Ripples (Left & Right +/-10s) -->
      <div v-if="doubleTapRipple" class="player-doubletap-ripple" :class="doubleTapRipple.side">
        <div class="ripple-badge">
          <i :class="doubleTapRipple.side === 'right' ? 'ph-bold ph-arrow-clockwise' : 'ph-bold ph-arrow-counter-clockwise'"></i>
          <span>{{ doubleTapRipple.side === 'right' ? '+10s' : '-10s' }}</span>
        </div>
      </div>

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
      <div class="custom-player-controls" :class="{ hidden: controlsHidden && !showResumeModal && !playerError }" @touchstart="showControls" @mousemove="showControls" @click.stop="showControls">
        <!-- Top Bar (Always Clickable) -->
        <div class="custom-player-top" style="z-index: 500; position: relative; pointer-events: auto;">
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
          <!-- Side-by-Side Row above Seekbar: Show Info (LEFT) strictly when paused -->
          <div class="player-overlay-row" v-if="!isPlaying && media">
            <div class="player-paused-info">
              <div class="player-paused-logo-container">
                <img v-if="media.logo_path" :src="imgUrl(media.logo_path)" :alt="media.title" class="player-paused-logo" />
                <h2 v-else class="player-paused-title">{{ media.title }}</h2>
              </div>
              <p v-if="media.overview" class="player-paused-overview">{{ media.overview }}</p>
            </div>
          </div>

          <!-- Seekbar -->
          <div class="seekbar-wrapper"
               ref="seekbarRef"
               @click="seekToClick"
               @mouseenter="onSeekbarMouseEnter"
               @mousemove="hoverSeekbar"
               @mouseleave="onSeekbarMouseLeave"
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
                <div v-if="volume > 1.0" class="volume-boost-badge">{{ Math.round(volume * 100) }}%</div>
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
              <!-- Audio Track & Sound Enhancer Menu -->
              <div style="position:relative">
                <button class="ctrl-btn" @click="showAudioMenu = !showAudioMenu; showSubMenu = false; showSpeedMenu = false; showQualityMenu = false" title="Audio Track & Sound Enhancer" id="ctrl-audio" style="font-size:0.85rem;font-weight:700">
                  <i class="ph ph-microphone-stage" style="font-size:1.35rem"></i>
                </button>
                <div v-if="showAudioMenu" class="player-popup-menu" @click.stop style="min-width:220px">
                  <div style="font-size:0.75rem;color:var(--text-muted);padding:4px 12px 6px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                    Audio Tracks
                  </div>
                  <div v-if="!audioTracks || !audioTracks.length" class="player-menu-item active">
                    Default Audio
                  </div>
                  <div v-for="track in audioTracks" :key="track.index" class="player-menu-item" :class="{ active: (streamState.audioTrack ?? defaultAudioIndex) === track.index }" @click="selectAudioTrack(track.index)">
                    {{ track.title }}<span v-if="track.index === defaultAudioIndex" style="opacity:0.6;font-weight:400"> · Default</span>
                  </div>

                  <!-- Sound Enhancer / Night Mode -->
                  <div style="border-top:1px solid rgba(255,255,255,0.1);margin:6px 0 4px"></div>
                  <div style="font-size:0.75rem;color:var(--text-muted);padding:4px 12px 6px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;display:flex;align-items:center;justify-content:space-between">
                    <span>Sound Enhancer</span>
                    <span style="color:var(--accent);text-transform:capitalize;font-size:0.7rem;font-weight:700">{{ audioEnhancerMode }}</span>
                  </div>
                  <div style="display:flex;gap:4px;padding:0 12px 6px">
                    <button
                      v-for="opt in [{ id: 'off', label: 'Off' }, { id: 'dialogue', label: 'Dialogue' }, { id: 'night', label: 'Night' }]"
                      :key="opt.id"
                      class="player-aspect-pill"
                      :class="{ active: audioEnhancerMode === opt.id }"
                      @click="setAudioEnhancerMode(opt.id)"
                      :title="opt.id === 'dialogue' ? 'Boosts speech frequencies for crystal clear dialogue' : opt.id === 'night' ? 'Dialogue boost + compresses loud sound effects & explosions' : 'Standard audio output'"
                    >
                      {{ opt.label }}
                    </button>
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

              <!-- Video Quality & Player Options Menu (Gear Icon) -->
              <div style="position:relative">
                <button class="ctrl-btn" :class="{ active: showQualityMenu }" @click="showQualityMenu = !showQualityMenu; showSpeedMenu = false; showSubMenu = false; showAudioMenu = false" title="Player Options & Quality" id="ctrl-quality" style="font-size:0.85rem;font-weight:700">
                  <i class="ph ph-gear-six" style="font-size:1.35rem"></i>
                </button>
                <div v-if="showQualityMenu" class="player-popup-menu" @click.stop style="min-width:220px">
                  <div style="font-size:0.75rem;color:var(--text-muted);padding:6px 12px 4px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                    Player Options
                  </div>

                  <!-- Aspect Ratio Selector inside Player Options -->
                  <div class="player-menu-section-item" style="padding:4px 12px 6px">
                    <div style="font-size:0.8rem;font-weight:600;display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                      <span style="display:flex;align-items:center;gap:6px">
                        <i class="ph ph-frame-corners" style="font-size:0.95rem"></i> Aspect Ratio
                      </span>
                      <span style="font-size:0.72rem;color:var(--accent);text-transform:capitalize;font-weight:700">{{ aspectRatioFit }}</span>
                    </div>
                    <div class="player-aspect-pills" style="display:flex;gap:4px">
                      <button
                        v-for="mode in ['contain', 'cover', 'fill']"
                        :key="mode"
                        class="player-aspect-pill"
                        :class="{ active: aspectRatioFit === mode }"
                        @click="aspectRatioFit = mode"
                      >
                        {{ mode.charAt(0).toUpperCase() + mode.slice(1) }}
                      </button>
                    </div>
                  </div>

                  <!-- Sound Enhancer Mode inside Player Options -->
                  <div class="player-menu-section-item" style="padding:4px 12px 6px">
                    <div style="font-size:0.8rem;font-weight:600;display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                      <span style="display:flex;align-items:center;gap:6px">
                        <i class="ph ph-speaker-high" style="font-size:0.95rem"></i> Sound Enhancer
                      </span>
                      <span style="font-size:0.72rem;color:var(--accent);text-transform:capitalize;font-weight:700">{{ audioEnhancerMode }}</span>
                    </div>
                    <div class="player-aspect-pills" style="display:flex;gap:4px">
                      <button
                        v-for="opt in [{ id: 'off', label: 'Off' }, { id: 'dialogue', label: 'Dialogue' }, { id: 'night', label: 'Night' }]"
                        :key="opt.id"
                        class="player-aspect-pill"
                        :class="{ active: audioEnhancerMode === opt.id }"
                        @click="setAudioEnhancerMode(opt.id)"
                        :title="opt.id === 'dialogue' ? 'Boosts speech frequencies for crystal clear dialogue' : opt.id === 'night' ? 'Dialogue boost + compresses loud sound effects & explosions' : 'Standard audio output'"
                      >
                        {{ opt.label }}
                      </button>
                    </div>
                  </div>

                  <!-- Picture-in-Picture Toggle inside Player Options -->
                  <div
                    v-if="isPipSupported"
                    class="player-menu-item"
                    :class="{ active: isPipActive }"
                    @click="togglePip(); showQualityMenu = false"
                    id="player-menu-pip"
                    style="display:flex;align-items:center;justify-content:space-between"
                  >
                    <span style="display:flex;align-items:center;gap:8px">
                      <i :class="isPipActive ? 'ph-fill ph-screencast' : 'ph ph-screencast'"></i> Picture-in-Picture (P)
                    </span>
                    <i v-if="isPipActive" class="ph-bold ph-check" style="color:var(--accent)"></i>
                  </div>

                  <!-- Edit Skip Markers -->
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

              <!-- Episodes & Seasons Drawer Button (Series / Anime) -->
              <div style="position:relative" v-if="isSeriesMedia">
                <button
                  class="ctrl-btn"
                  :class="{ active: showEpisodesDrawer }"
                  @click="toggleEpisodesDrawer"
                  title="Episodes & Seasons (E)"
                  id="ctrl-episodes"
                >
                  <i class="ph ph-squares-four" style="font-size:1.35rem"></i>
                </button>
              </div>

              <!-- Queue & Playlist Drawer Button -->
              <div style="position:relative">
                <button
                  class="ctrl-btn"
                  :class="{ active: showQueueDrawer }"
                  @click="toggleQueueDrawer"
                  title="Queue & Playlist (Q)"
                  id="ctrl-queue"
                >
                  <i class="ph ph-queue" style="font-size:1.35rem"></i>
                  <span v-if="store.queue && store.queue.length" class="player-queue-badge">
                    {{ store.queue.length }}
                  </span>
                </button>
              </div>

              <!-- Fullscreen -->
              <button class="ctrl-btn" @click="toggleFullscreen" title="Fullscreen (F)" id="ctrl-fullscreen">
                <i :class="isFullscreen ? 'ph ph-arrows-in-simple' : 'ph ph-arrows-out-simple'"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Floating Skip Intro / Recap Action -->
      <div v-if="activeSkipAction && !(showCreditsShrink && hasNextEp) && activeSkipAction.type !== 'Next'" class="player-skip-container" @click.stop>
        <button class="player-skip-btn" @click="executeSkipAction" id="player-skip-btn">
          <div class="player-skip-icon">
            <i class="ph ph-fast-forward"></i>
          </div>
          <div class="player-skip-meta">
            <span class="player-skip-label">Skip</span>
            <span class="player-skip-title">{{ activeSkipAction.type }}</span>
            <span class="player-skip-sub">Jump to {{ formatSecToTime(activeSkipAction.end) }}</span>
          </div>
          <kbd class="player-skip-kbd" title="Press 'S' to skip">S</kbd>
        </button>
        <button v-if="!store.profile?.is_kids" class="player-skip-edit-btn" @click.stop="showSkipModal = true" title="Edit Skip Timestamps" id="player-skip-edit-btn">
          <i class="ph ph-sliders-horizontal"></i>
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
            <div v-else class="resume-thumb-placeholder"><i class="ph-bold ph-film-strip"></i></div>
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

      <!-- "Are You Still Watching?" Inactivity Sleep Modal -->
      <div v-if="showInactivityPrompt" class="modal-backdrop" @click.stop>
        <div class="resume-modal-card inactivity-sleep-card" @click.stop>
          <div class="resume-card-info" style="text-align:center">
            <div class="resume-badge" style="background:rgba(245,158,11,0.15);color:#fbbf24;border-color:rgba(245,158,11,0.3)">
              <i class="ph ph-moon-stars"></i> INACTIVITY PAUSE
            </div>
            <div class="resume-card-heading">Are you still watching?</div>
            <div class="resume-card-subtext" style="margin-top:6px">
              Playback paused after {{ consecutiveAutoAdvances }} continuous auto-advances.
            </div>
          </div>
          <div class="resume-card-actions" style="margin-top:1.5rem">
            <button class="btn btn-primary btn-full" @click="confirmStillWatching" id="btn-still-watching-continue" autoFocus>
              <i class="ph-fill ph-play"></i>
              <span>I'm Still Watching</span>
            </button>
            <button class="btn btn-secondary btn-full" @click="goHome" id="btn-still-watching-home">
              <i class="ph ph-house"></i>
              <span>Back to Home</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Netflix / Disney+ Floating Right-Side Next Episode Card -->
      <transition name="fade">
        <div v-if="showCreditsShrink && hasNextEp" class="next-ep-floating-card" @click.stop>
          <div class="next-ep-floating-header">
            <div class="next-ep-floating-badge">
              <i class="ph ph-hourglass-high"></i>
              <span>Next Episode in {{ Math.ceil(nextEpCountdownSeconds) }}s</span>
            </div>
            <button class="next-ep-floating-close" @click="dismissCreditsShrink" title="Dismiss (Watch Credits)">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <!-- Progress countdown line -->
          <div class="next-ep-floating-progress-bar">
            <div class="next-ep-floating-progress-fill" :style="{ width: nextEpProgressPercent + '%' }"></div>
          </div>

          <!-- Preview Body -->
          <div class="next-ep-floating-body" @click="handleNextEpClick">
            <div class="next-ep-floating-thumb-wrap">
              <img
                v-if="nextEp.still_path || nextEp.backdrop_path || seriesData?.backdrop_path"
                :src="imgUrl(nextEp.still_path || nextEp.backdrop_path || seriesData?.backdrop_path)"
                class="next-ep-floating-thumb-img"
                @error="e => e.target.style.display = 'none'"
              />
              <div v-else class="next-ep-floating-thumb-fallback">
                <i class="ph ph-film-strip"></i>
              </div>
              <div class="next-ep-floating-play-icon">
                <i class="ph-fill ph-play"></i>
              </div>
            </div>

            <div class="next-ep-floating-info">
              <div class="next-ep-floating-ep-code">
                S{{ (nextEp.season || activeDrawerSeason).toString().padStart(2,'0') }}E{{ (nextEp.episode || 1).toString().padStart(2,'0') }}
              </div>
              <div class="next-ep-floating-title" :title="nextEp.ep_title || nextEp.title">
                {{ nextEp.ep_title || nextEp.title || ('Episode ' + nextEp.episode) }}
              </div>
              <div v-if="nextEp.duration" class="next-ep-floating-duration">
                {{ formatDuration(nextEp.duration) }}
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="next-ep-floating-actions">
            <button class="btn btn-primary btn-full" @click="handleNextEpClick" id="btn-next-ep-play-now">
              <i class="ph-fill ph-play"></i>
              <span>Play Next</span>
            </button>
            <button class="btn btn-secondary btn-full" @click="dismissCreditsShrink" id="btn-next-ep-dismiss">
              <span>Watch Credits</span>
            </button>
          </div>
        </div>
      </transition>

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

      <!-- In-Player Slide-Out Episodes & Seasons Drawer -->
      <transition name="slide-left">
        <div v-if="showEpisodesDrawer" class="player-episodes-drawer" @click.stop>
          <div class="episodes-drawer-header">
            <div class="episodes-drawer-title-group">
              <div class="episodes-drawer-show-title" :title="seriesData?.title || media?.title">
                <i class="ph ph-television" style="color:var(--accent);margin-right:6px"></i>
                <span>{{ seriesData?.title || media?.title || 'Episodes' }}</span>
              </div>
              <!-- Season Selector Pills -->
              <div class="drawer-season-pills" v-if="drawerSeasonsList.length > 1">
                <button
                  v-for="sNum in drawerSeasonsList"
                  :key="sNum"
                  class="drawer-season-pill"
                  :class="{ active: activeDrawerSeason === sNum }"
                  @click="activeDrawerSeason = sNum"
                >
                  Season {{ sNum }}
                </button>
              </div>
            </div>
            <button class="queue-close-btn" @click="showEpisodesDrawer = false" title="Close Episodes (Esc)">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <!-- Episodes List -->
          <div class="episodes-drawer-list">
            <div
              v-for="ep in drawerEpisodesList"
              :key="ep.id || ('ep-' + ep.season + '-' + ep.episode)"
              class="drawer-ep-item"
              :class="{
                'active-playing': Number(ep.id) === Number(media?.id) || (ep.season === media?.season && ep.episode === media?.episode),
                'missing-ep': ep.is_local === false || ep.is_mounted === false
              }"
              @click="playEpisodeFromDrawer(ep)"
            >
              <!-- 16:9 Episode Thumbnail -->
              <div class="drawer-ep-thumb-wrap">
                <img
                  v-if="ep.still_path || ep.backdrop_path || seriesData?.backdrop_path"
                  :src="imgUrl(ep.still_path || ep.backdrop_path || seriesData?.backdrop_path)"
                  class="drawer-ep-thumb-img"
                  @error="e => e.target.style.display = 'none'"
                />
                <div v-else class="drawer-ep-thumb-fallback">
                  <i class="ph ph-film-strip"></i>
                </div>

                <!-- Watch Progress Line -->
                <div v-if="calcProgressPercent(ep) > 0" class="drawer-ep-progress-bar">
                  <div class="drawer-ep-progress-fill" :style="{ width: calcProgressPercent(ep) + '%' }"></div>
                </div>

                <!-- Active Now Playing Overlay / Equalizer -->
                <div v-if="Number(ep.id) === Number(media?.id) || (ep.season === media?.season && ep.episode === media?.episode)" class="drawer-ep-playing-overlay">
                  <div class="now-playing-equalizer">
                    <span></span><span></span><span></span>
                  </div>
                </div>

                <!-- Play Hover Icon -->
                <div v-else-if="ep.is_local !== false && ep.is_mounted !== false" class="drawer-ep-hover-overlay">
                  <i class="ph-fill ph-play"></i>
                </div>

                <!-- Missing Episode Overlay -->
                <div v-else class="drawer-ep-missing-overlay">
                  <span>{{ ep.is_mounted === false ? 'Unmounted' : 'Missing' }}</span>
                </div>
              </div>

              <!-- Episode Info -->
              <div class="drawer-ep-info">
                <div class="drawer-ep-meta-row">
                  <span class="drawer-ep-code">S{{ (ep.season || activeDrawerSeason).toString().padStart(2,'0') }}E{{ (ep.episode || 1).toString().padStart(2,'0') }}</span>
                  <span v-if="ep.duration" class="drawer-ep-duration">{{ formatDuration(ep.duration) }}</span>
                </div>
                <div class="drawer-ep-title" :title="ep.ep_title || ep.title || ('Episode ' + ep.episode)">
                  {{ ep.ep_title || ep.title || ('Episode ' + ep.episode) }}
                </div>
                <div v-if="ep.overview" class="drawer-ep-overview">
                  {{ ep.overview }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </transition>

      <!-- In-Player Slide-Out Queue Drawer -->
      <transition name="slide-left">
        <div v-if="showQueueDrawer" class="player-queue-drawer" @click.stop>
          <div class="queue-drawer-header">
            <div class="queue-drawer-title">
              <i class="ph ph-queue" style="color:var(--accent);font-size:1.3rem"></i>
              <span>{{ store.queuePlaylistName || 'Playback Queue' }}</span>
              <span v-if="store.queue && store.queue.length" class="queue-count-pill">{{ store.queue.length }}</span>
            </div>
            <button class="queue-close-btn" @click="showQueueDrawer = false" title="Close Queue">
              <i class="ph ph-x"></i>
            </button>
          </div>

          <!-- Queue Controls Toolbar -->
          <div class="queue-toolbar">
            <button
              class="queue-tool-btn"
              :class="{ active: store.queueShuffle }"
              @click="toggleQueueShuffle"
              title="Shuffle Queue"
            >
              <i class="ph ph-shuffle"></i> Shuffle
            </button>
            <button
              class="queue-tool-btn"
              :class="{ active: store.queueRepeat !== 'off' }"
              @click="cycleQueueRepeat"
              :title="'Repeat: ' + store.queueRepeat"
            >
              <i :class="store.queueRepeat === 'one' ? 'ph ph-repeat-once' : 'ph ph-repeat'"></i>
              {{ store.queueRepeat === 'all' ? 'Repeat All' : store.queueRepeat === 'one' ? 'Repeat One' : 'Repeat Off' }}
            </button>
            <button class="queue-tool-btn danger" @click="clearActiveQueue" title="Clear Queue">
              <i class="ph ph-trash"></i> Clear
            </button>
          </div>

          <!-- Queue Items List -->
          <div v-if="!store.queue || !store.queue.length" class="queue-empty-state">
            <i class="ph ph-queue"></i>
            <div style="font-weight:700;font-size:0.95rem;margin-bottom:4px">Queue is empty</div>
            <p style="font-size:0.8rem;color:var(--text-muted)">Add titles from your library or playlists to play them back-to-back.</p>
          </div>

          <div v-else class="queue-items-list">
            <div
              v-for="(item, qIdx) in store.queue"
              :key="item.item_id || item.id + '-' + qIdx"
              class="queue-item-card"
              :class="{ 'is-playing': qIdx === store.queueIndex }"
              @click="playQueueItem(qIdx)"
            >
              <div class="queue-item-drag-handle">
                <span v-if="qIdx === store.queueIndex" class="queue-now-playing-icon">▶</span>
                <span v-else class="queue-item-num">{{ qIdx + 1 }}</span>
              </div>
              <div class="queue-item-thumb">
                <img :src="imgUrl(item.still_path || item.poster_path || item.backdrop_path)" :alt="item.title" loading="lazy" />
              </div>
              <div class="queue-item-meta">
                <div class="queue-item-title" :title="item.title">
                  {{ item.title }}
                </div>
                <div class="queue-item-sub">
                  <span v-if="item.season_number && item.episode_number">
                    S{{ item.season_number }} E{{ item.episode_number }} · 
                  </span>
                  <span>{{ formatTime(item.duration || 0) }}</span>
                </div>
              </div>
              <div class="queue-item-actions" @click.stop>
                <button class="queue-action-btn" @click.stop="moveQueueItem(qIdx, -1)" :disabled="qIdx === 0" title="Move Up">
                  <i class="ph ph-caret-up"></i>
                </button>
                <button class="queue-action-btn" @click.stop="moveQueueItem(qIdx, 1)" :disabled="qIdx === store.queue.length - 1" title="Move Down">
                  <i class="ph ph-caret-down"></i>
                </button>
                <button class="queue-action-btn danger" @click.stop="removeQueueItem(qIdx)" title="Remove">
                  <i class="ph ph-x"></i>
                </button>
              </div>
            </div>
          </div>
        </div>
      </transition>

      <!-- Codec Compatibility Notice Pill (HEVC / 10-Bit Color / AV1, non-blocking, bottom-center) -->
      <transition name="fade" @after-leave="onCodecNoticeAfterLeave">
        <div
          v-if="codecNoticePill"
          class="player-codec-notice-pill"
          style="position:absolute;bottom:90px;left:50%;transform:translateX(-50%);z-index:300;display:flex;align-items:center;gap:10px;background:rgba(18,18,26,0.9);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.12);border-radius:99px;padding:8px 16px 8px 12px;font-size:0.83rem;color:rgba(255,255,255,0.88);pointer-events:auto;white-space:nowrap;box-shadow:0 4px 20px rgba(0,0,0,0.45)"
        >
          <i class="ph-bold ph-film-slate" style="font-size:1rem;color:#60a5fa;flex-shrink:0"></i>
          <span style="font-weight:600;color:#fff">Codec Notice:</span>
          <div style="display:flex;align-items:center;gap:6px">
            <span
              v-for="tag in codecNoticePill.tags"
              :key="tag"
              style="display:inline-block;padding:2px 8px;border-radius:6px;font-size:0.75rem;font-weight:600;background:rgba(255,255,255,0.1);color:#e2e8f0;border:1px solid rgba(255,255,255,0.15)"
            >{{ tag }}</span>
          </div>
          <span style="color:rgba(255,255,255,0.65);font-size:0.78rem">Requires hardware decoding</span>
          <button
            @click="dismissCodecNotice"
            style="background:none;border:none;color:rgba(255,255,255,0.45);cursor:pointer;padding:0 2px;font-size:0.9rem;flex-shrink:0;margin-left:4px"
            title="Dismiss"
          ><i class="ph ph-x"></i></button>
        </div>
      </transition>

      <!-- Auto-Switch 4K Notification Pill (non-blocking, bottom-center) -->
      <transition name="fade">
        <div
          v-if="autoSwitched4K && !isCodecNoticeActive"
          style="position:absolute;bottom:90px;left:50%;transform:translateX(-50%);z-index:300;display:flex;align-items:center;gap:10px;background:rgba(18,18,26,0.88);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1);border-radius:99px;padding:8px 16px 8px 12px;font-size:0.83rem;color:rgba(255,255,255,0.85);pointer-events:auto;white-space:nowrap;box-shadow:0 4px 20px rgba(0,0,0,0.4)"
        >
          <i class="ph ph-info" style="font-size:1rem;color:rgba(255,200,80,0.9);flex-shrink:0"></i>
          <span>Switched to {{ autoSwitched4K.label }} — 4K may not play smoothly</span>
          <button
            @click="dismissAutoSwitched4K"
            style="background:none;border:none;color:rgba(255,255,255,0.45);cursor:pointer;padding:0 2px;font-size:0.9rem;flex-shrink:0"
            title="Dismiss"
          ><i class="ph ph-x"></i></button>
        </div>
      </transition>

      <!-- Stutter 4K Banner (non-blocking, bottom, mid-playback) -->
      <transition name="fade">
        <div
          v-if="stutter4KBanner && !isCodecNoticeActive && !autoSwitched4K"
          style="position:absolute;bottom:80px;left:50%;transform:translateX(-50%);z-index:300;display:flex;align-items:center;gap:10px;background:rgba(18,18,26,0.9);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,160,60,0.25);border-radius:99px;padding:9px 18px 9px 14px;font-size:0.84rem;color:rgba(255,255,255,0.85);pointer-events:auto;white-space:nowrap;box-shadow:0 4px 20px rgba(0,0,0,0.45)"
        >
          <i class="ph ph-warning" style="font-size:1rem;color:rgba(255,160,60,0.9);flex-shrink:0"></i>
          <span>4K playback is struggling on this device</span>
          <button
            @click="stutter4KAutoSwitch"
            style="margin-left:4px;background:#e50914;border:none;border-radius:99px;padding:4px 14px;color:#fff;font-size:0.8rem;font-weight:700;cursor:pointer;transition:background 0.2s;flex-shrink:0"
          >Switch to 1080p</button>
          <button
            @click="stutter4KBanner = null"
            style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.18);border-radius:99px;padding:4px 12px;color:rgba(255,255,255,0.8);font-size:0.8rem;font-weight:500;cursor:pointer;flex-shrink:0"
          >Keep Playing</button>
        </div>
      </transition>

      <!-- Low Memory Protection & In-Place Recovery Banner -->
      <transition name="fade">
        <div v-if="lowMemoryBanner && !isCodecNoticeActive && !autoSwitched4K && !stutter4KBanner" class="player-low-memory-banner" @click.stop>
          <i class="ph ph-warning-circle player-low-memory-icon"></i>
          <div class="player-low-memory-msg">
            <span>{{ lowMemoryBanner.message || 'Low memory detected • Light mode active' }}</span>
          </div>
          <div class="player-low-memory-actions">
            <button class="player-low-memory-btn-recover" @click="freeMemoryAndRecover" title="Flush video buffers and re-anchor playback">
              <i :class="recoveringMemory ? 'ph ph-circle-notch' : 'ph ph-lightning'" :style="recoveringMemory ? 'animation:spin 1s linear infinite' : ''"></i>
              <span>{{ recoveringMemory ? 'Cleaning…' : 'Free Up Memory & Recover' }}</span>
            </button>
            <button class="player-low-memory-btn-dismiss" @click="dismissLowMemoryBanner" title="Dismiss">
              <i class="ph ph-x"></i>
            </button>
          </div>
        </div>
      </transition>

      <!-- Playback Error Overlay (real failures only) -->
      <div
        v-if="playerError"
        class="player-issue-overlay"
        style="position:absolute;inset:0;background:radial-gradient(circle at center, rgba(16,16,24,0.78) 0%, rgba(6,6,10,0.92) 100%);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);z-index:400;padding:2.5rem 1.5rem;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;pointer-events:auto"
        @click.stop.prevent
        @dblclick.stop.prevent
      >
        <div class="player-issue-icon-wrap" style="position:relative;margin-bottom:1.25rem;display:flex;align-items:center;justify-content:center">
          <div style="position:absolute;width:90px;height:90px;border-radius:50%;background:radial-gradient(circle, rgba(239,68,68,0.28) 0%, transparent 70%);pointer-events:none"></div>
          <i class="ph ph-warning" style="font-size:3.8rem;color:rgba(255,255,255,0.9);position:relative;z-index:2"></i>
        </div>
        <div style="font-size:1.5rem;font-weight:700;letter-spacing:-0.3px;color:#fff;margin-bottom:0.65rem">
          Playback Issue
        </div>
        <div style="max-width:540px;margin:0 auto 1.5rem;font-size:0.92rem;color:rgba(255,255,255,0.72);line-height:1.65;font-weight:400">
          {{ playerError }}
        </div>
        <!-- Primary Action Button (Top) -->
        <div v-if="!streamState.transcode" style="display:flex;justify-content:center;margin-bottom:12px;width:100%">
          <button class="btn player-issue-btn-red" style="background:#e50914;color:#fff;border:none;border-radius:99px;padding:0.75rem 1.85rem;font-weight:700;font-size:0.95rem;display:flex;align-items:center;gap:8px;box-shadow:0 4px 18px rgba(229,9,20,0.45);cursor:pointer;transition:all 0.2s" @click="enableCompatPlayback">
            <i class="ph-bold ph-lightning"></i>
            Play Converted (1080p)
          </button>
        </div>
        <!-- Secondary Actions -->
        <div style="display:flex;gap:12px;justify-content:center;align-items:center;flex-wrap:wrap">
          <button class="btn player-issue-btn-dark" style="background:rgba(255,255,255,0.12);color:#fff;border:1px solid rgba(255,255,255,0.18);border-radius:99px;padding:0.65rem 1.5rem;font-weight:600;font-size:0.9rem;display:flex;align-items:center;gap:8px;cursor:pointer;transition:all 0.2s" @click="recoverFromError" :disabled="recovering">
            <i :class="recovering ? 'ph ph-circle-notch' : 'ph-bold ph-arrow-counter-clockwise'" :style="recovering ? 'animation:spin 1s linear infinite' : ''"></i>
            {{ recovering ? 'Recovering…' : 'Resume Playback' }}
          </button>
          <button class="btn player-issue-btn-dark" style="background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.85);border:1px solid rgba(255,255,255,0.14);border-radius:99px;padding:0.65rem 1.5rem;font-weight:600;font-size:0.9rem;cursor:pointer;transition:all 0.2s" @click="goBack">
            Go Back
          </button>
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
    const autoSwitched4K = ref(null);  // { label, original4kOption }
    const stutter4KBanner = ref(false);
    const lowMemoryBanner = ref(null);
    const isLightMode = ref(false);
    const recoveringMemory = ref(false);

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
      audioTrack: null,     // null/undefined/default -> native; otherwise remote-audio index
      transcode: false,     // hardware-accelerated compatibility playback
      maxHeight: 1080,      // target resolution limit (1080, 720, 480)
      streamStart: 0,       // content time where the converted stream begins
    });

    // Retained for compatibility with helpers below; video is never
    // transcoded anymore, so this is permanently false.
    const isTranscodeAudio = computed(() => false);

    function contentToPlayer(t) {
      return Math.max(0, t - (streamState.transcode ? streamState.streamStart : 0));
    }
    function playerToContent(t) {
      return (streamState.transcode ? (streamState.streamStart || 0) : 0) + (Number(t) || 0);
    }
    function currentContentTime() {
      const v = videoRef.value;
      const raw = (v && isFinite(v.currentTime) ? v.currentTime : 0) || (isFinite(currentTime.value) ? currentTime.value : 0);
      return playerToContent(raw);
    }

    // ── Stream swap: the ONLY way playback source changes ──────────
    let reloadToken = 0;

    function buildStreamUrl(mediaId, bustCache = false) {
      if (!streamState.transcode) {
        return `/api/stream/${mediaId}`;
      }
      const maxH = streamState.maxHeight || 1080;
      let url = `/api/stream/${mediaId}?transcode=1&max_height=${maxH}&boost=1`;
      if (streamState.audioTrack !== null && streamState.audioTrack !== undefined) {
        url += `&audio_track=${streamState.audioTrack}`;
      }
      if (streamState.streamStart > 0) {
        url += `&start=${Number(streamState.streamStart).toFixed(3)}`;
      }
      if (bustCache) {
        url += `&_t=${Date.now()}`;
      }
      return url;
    }

    function swapStream(atContentTime, forceReload = false) {
      const v = videoRef.value;
      if (!v) return;
      const token = ++reloadToken;
      // Exact float position for frame-perfect continuation
      const playerPos = streamState.transcode
        ? 0
        : Math.max(0, Number(atContentTime || 0));

      const onMeta = () => {
        v.removeEventListener("loadedmetadata", onMeta);
        if (token !== reloadToken) return;   // a newer swap superseded us
        try {
          if (playerPos > 0 && isFinite(playerPos)) {
            if (v.fastSeek) {
              v.fastSeek(playerPos);
            } else {
              v.currentTime = playerPos;
            }
          }
          currentTime.value = playerPos;
        } catch (e) {}
        applySubtitleOffset();
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
      v.addEventListener("loadedmetadata", onMeta, { once: true });

      // Append media fragment #t=... so the browser requests the target byte-range directly on initial probe
      const isTranscode = !!streamState.transcode;
      const wantBase = buildStreamUrl(streamState.mediaId, isTranscode && (forceReload || !!v.error));
      const want = wantBase + (playerPos > 0 && !isTranscode ? `#t=${playerPos.toFixed(3)}` : '');
      const absWantBase = new URL(wantBase.split('&_t=')[0], location.origin).href;

      const needsFullReload = forceReload || !!v.error || isTranscode || !v.src || !v.src.startsWith(absWantBase);

      if (needsFullReload) {
        currentTime.value = playerPos;
        v.src = want;
        try {
          if (playerPos > 0 && isFinite(playerPos)) v.currentTime = playerPos;
        } catch (e) {}
        v.load();
        v.play().catch(() => {});
      } else {
        // Same source already loaded — just reposition deterministically
        try {
          if (playerPos > 0 && isFinite(playerPos)) {
            if (v.fastSeek) v.fastSeek(playerPos);
            else v.currentTime = playerPos;
          }
          currentTime.value = playerPos;
        } catch (e) {}
        applySubtitleOffset();
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
        !streamState.transcode &&
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

    // Only offer switching when 2 or more quality options exist.
    const canSwitchQuality = computed(() =>
      !!media.value && qualityOptions.value.length > 1
    );

    async function loadQualityOptions(mediaId) {
      try {
        const opts = await API.get(`/api/quality-options/${mediaId}`);
        qualityOptions.value = opts || [];
        if (!selectedQualityMediaId.value || !qualityOptions.value.some((o) => o.media_id === selectedQualityMediaId.value)) {
          const current = qualityOptions.value.find((o) => o.is_current);
          if (current) {
            selectedQualityMediaId.value = current.media_id;
          } else if (qualityOptions.value.length > 0) {
            selectedQualityMediaId.value = qualityOptions.value[0].media_id;
          }
        }
      } catch (e) {
        qualityOptions.value = [];
      }
    }

    // ── Force 4K even though compat check failed (undo auto-switch) ──
    function force4KPlayback() {
      const original = autoSwitched4K.value?.original4kOption;
      dismissAutoSwitched4K();
      stutter4KBanner.value = null;
      if (original) {
        selectQuality(original, true);
      }
    }

    // ── Auto-switch to best non-4K option when stutter is detected ──
    function stutter4KAutoSwitch() {
      stutter4KBanner.value = null;
      const fallback = (qualityOptions.value || []).find(
        (o) => !(o.base_label || o.resolution || "").startsWith("4K") && o.media_id !== selectedQualityMediaId.value
      );
      if (fallback) {
        selectQuality(fallback, true);
      } else if (!streamState.transcode) {
        enableCompatPlayback(true);
      }
    }

    async function selectQuality(option, bypassCheck = false) {
      if (!option || option.media_id === selectedQualityMediaId.value) {
        showQualityMenu.value = false;
        return;
      }

      // ── 4K Compatibility Smart Auto-Switch ──────────────────────────
      const is4KOption = (option.base_label || option.resolution || "").startsWith("4K");
      const check4KEnabled = playerSettings.value?.playback?.check_4k_compat !== false;
      if (is4KOption && !bypassCheck && check4KEnabled) {
        const compat = await check4KCompatibility();
        if (!compat.compatible) {
          showQualityMenu.value = false;
          const fallback = (qualityOptions.value || []).find(
            (o) => o.media_id !== option.media_id && !(o.base_label || o.resolution || "").startsWith("4K")
          ) || null;
          if (fallback) {
            // Silently switch to fallback and show undo pill
            const original4kOption = option;
            selectQuality(fallback, true);
            setAutoSwitched4K({
              label: fallback.display_label || fallback.base_label || "1080p",
              original4kOption,
            });
          } else if (!streamState.transcode) {
            // No lower quality available — switch to converted playback silently
            enableCompatPlayback(true);
          }
          return;
        }
      }
      // ──────────────────────────────────────────────────────────────

      showQualityMenu.value = false;
      dismissAutoSwitched4K();
      stutter4KBanner.value = null;
      trackPlayerFeature("quality");
      suppressResume = true;
      saveProgressNow();

      // Immediately silence & detach any existing remote audio stream and pause old video
      detachRemoteAudio();
      if (videoRef.value) {
        try { videoRef.value.pause(); } catch (e) {}
      }

      const atContent = currentContentTime();
      selectedQualityMediaId.value = option.media_id;
      streamState.mediaId = option.media_id;
      triggerCodecNotice(option.file_path || media.value?.file_path || "");

      // Refresh metadata, audio tracks, subtitles, skip-times, and thumb sheet for new quality file
      API.get(`/api/media/${option.media_id}`).then((newMedia) => {
        if (newMedia) {
          media.value = newMedia;
          if (newMedia.duration) displayDuration.value = newMedia.duration;
          subtitles.value = newMedia.subtitles || [];
        }
      }).catch(() => {});

      API.get(`/api/audio-tracks/${option.media_id}`).then((tracks) => {
        audioTracks.value = Array.isArray(tracks) ? tracks : [];
      }).catch(() => { audioTracks.value = []; });

      loadSkipTimes(option.media_id);
      loadThumbSheet(option.media_id);

      swapStream(atContent, true);

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

    let pendingSeekTarget = null;
    let seekDebounceTimer = null;

    function seekTo(targetTime) {
      if (!videoRef.value) return;
      const maxDur = media.value?.duration || duration.value || 0;
      const validTarget = Math.min(Math.max(0, targetTime), maxDur > 0 ? maxDur : targetTime);
      suppressResume = true;
      pendingSeekTarget = validTarget;
      currentTime.value = contentToPlayer(validTarget);

      if (seekDebounceTimer) {
        clearTimeout(seekDebounceTimer);
      }

    // Smooth seek debouncing (120ms): accumulates multiple rapid skip/seek requests
      // without bombarding Chromium's demuxer or spinning up redundant FFmpeg processes.
      if (streamState.transcode) {
        isBuffering.value = true;
      }
      seekDebounceTimer = setTimeout(() => {
        seekDebounceTimer = null;
        const target = pendingSeekTarget;
        pendingSeekTarget = null;
        if (target === null || target === undefined || !videoRef.value) return;

        if (streamState.transcode) {
          isBuffering.value = true;
          const token = ++reloadToken;
          alignedStreamStart(target).then((startAt) => {
            if (token !== reloadToken) return;
            streamState.streamStart = startAt;
            swapStream(0);
          });
        } else {
          try {
            if (videoRef.value.fastSeek && Math.abs(videoRef.value.currentTime - target) > 15) {
              videoRef.value.fastSeek(target);
            } else {
              videoRef.value.currentTime = target;
            }
          } catch (e) {
            try { videoRef.value.currentTime = target; } catch (err) {}
          }
          currentTime.value = target;
        }
        saveProgressNow();
      }, 120);
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

    // ─── Codec Compatibility Notice (HEVC / 10-Bit Color / AV1) ─────
    // Direct playback of HEVC/x265, 10-bit color, and AV1 requires hardware
    // decoding support on browsers. Show a non-blocking informational notice.
    const codecNoticePill = ref(null);
    const isCodecNoticeActive = ref(false);
    let codecNoticeTimer = null;
    let autoSwitched4KTimer = null;

    function startAutoSwitched4KTimer() {
      if (autoSwitched4KTimer) {
        clearTimeout(autoSwitched4KTimer);
        autoSwitched4KTimer = null;
      }
      if (autoSwitched4K.value) {
        autoSwitched4KTimer = setTimeout(() => {
          autoSwitched4K.value = null;
          autoSwitched4KTimer = null;
        }, 8000);
      }
    }

    function setAutoSwitched4K(data) {
      if (autoSwitched4KTimer) {
        clearTimeout(autoSwitched4KTimer);
        autoSwitched4KTimer = null;
      }
      autoSwitched4K.value = data;
      if (!isCodecNoticeActive.value && data) {
        startAutoSwitched4KTimer();
      }
    }

    function dismissAutoSwitched4K() {
      if (autoSwitched4KTimer) {
        clearTimeout(autoSwitched4KTimer);
        autoSwitched4KTimer = null;
      }
      autoSwitched4K.value = null;
    }

    function triggerCodecNotice(path) {
      if (codecNoticeTimer) {
        clearTimeout(codecNoticeTimer);
        codecNoticeTimer = null;
      }
      if (!path) {
        codecNoticePill.value = null;
        isCodecNoticeActive.value = false;
        return;
      }
      const info = typeof getCodecInfo === "function" ? getCodecInfo(path) : null;
      if (info && info.hasWarning && info.tags && info.tags.length) {
        isCodecNoticeActive.value = true;
        if (autoSwitched4KTimer) {
          clearTimeout(autoSwitched4KTimer);
          autoSwitched4KTimer = null;
        }
        codecNoticePill.value = {
          tags: info.tags,
          note: info.note || "Advanced encoding requires hardware decoding support.",
        };
        codecNoticeTimer = setTimeout(() => {
          codecNoticePill.value = null;
          codecNoticeTimer = null;
        }, 7000);
      } else {
        codecNoticePill.value = null;
        isCodecNoticeActive.value = false;
      }
    }

    function dismissCodecNotice() {
      if (codecNoticeTimer) {
        clearTimeout(codecNoticeTimer);
        codecNoticeTimer = null;
      }
      codecNoticePill.value = null;
    }

    function onCodecNoticeAfterLeave() {
      isCodecNoticeActive.value = false;
      if (autoSwitched4K.value && !autoSwitched4KTimer) {
        startAutoSwitched4KTimer();
      }
    }

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

    async function enableCompatPlayback(force = false) {
      if (!media.value) return;
      suppressResume = true;
      isBuffering.value = true;
      const token = ++reloadToken;
      const at = currentContentTime();
      const startAt = await alignedStreamStart(at);
      if (token !== reloadToken) return;   // superseded
      streamState.transcode = true;
      streamState.streamStart = startAt;
      swapStream(0, force);
    }

    function disableCompatPlayback() {
      suppressResume = true;
      streamState.transcode = false;
      streamState.streamStart = 0;
      reloadToken++;
      swapStream(currentContentTime());
    }

    // Fetch encoder capabilities once when codec notice appears
    watch(codecNoticePill, (pill) => {
      if (pill) fetchCompatCaps();
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
    let memoryHealthTimer = null;

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
      // Never auto-hide if a settings/selection submenu or modal is open
      if (showSubMenu.value || showAudioMenu.value || showQualityMenu.value || showSpeedMenu.value || showOnlineSubModal.value || showResumeModal.value) {
        return;
      }
      if (videoRef.value && !videoRef.value.paused) {
        hideTimer = setTimeout(() => {
          if (showSubMenu.value || showAudioMenu.value || showQualityMenu.value || showSpeedMenu.value || showOnlineSubModal.value || showResumeModal.value) {
            return;
          }
          controlsHidden.value = true;
        }, 4500);
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
      if (playerError.value) return;
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

    const doubleTapRipple = ref(null);
    let doubleTapTimer = null;
    const brightnessHUD = ref(false);
    let brightnessTimer = null;
    const brightnessLevel = ref(100);
    const aspectRatioFit = ref("contain");

    function cycleAspectRatio() {
      const modes = ["contain", "cover", "fill"];
      const idx = modes.indexOf(aspectRatioFit.value);
      aspectRatioFit.value = modes[(idx + 1) % modes.length];
    }

    function triggerDoubleTapRipple(side) {
      if (doubleTapTimer) clearTimeout(doubleTapTimer);
      doubleTapRipple.value = { side };
      doubleTapTimer = setTimeout(() => {
        doubleTapRipple.value = null;
      }, 450);
    }

    let touchGestureState = {
      startX: 0,
      startY: 0,
      startTime: 0,
      lastY: 0,
      mode: null, // 'brightness' | 'volume' | 'pinch' | null
      startVal: 0,
      initialPinchDist: 0,
    };

    function getTouchDist(t1, t2) {
      return Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
    }

    function onPlayerTouchStart(e) {
      if (playerError.value) return;
      lastTouchTime = Date.now();
      if (e.target.closest(".custom-player-controls") || e.target.closest(".shortcuts-modal-card")) {
        showControls();
        return;
      }
      if (e.touches && e.touches.length === 2) {
        touchGestureState.mode = "pinch";
        touchGestureState.initialPinchDist = getTouchDist(e.touches[0], e.touches[1]);
        return;
      }
      if (e.touches && e.touches.length === 1) {
        const t = e.touches[0];
        const rect = e.currentTarget.getBoundingClientRect();
        touchGestureState.startX = t.clientX - rect.left;
        touchGestureState.startY = t.clientY - rect.top;
        touchGestureState.lastY = t.clientY;
        touchGestureState.startTime = Date.now();
        touchGestureState.mode = null;
      }
    }

    function onPlayerTouchMove(e) {
      if (playerError.value) return;
      if (e.target.closest(".custom-player-controls") || e.target.closest(".shortcuts-modal-card")) return;
      if (e.touches && e.touches.length === 2 && touchGestureState.mode === "pinch") {
        const currentDist = getTouchDist(e.touches[0], e.touches[1]);
        const scale = currentDist / (touchGestureState.initialPinchDist || 1);
        if (scale > 1.25 && aspectRatioFit.value !== "cover") {
          aspectRatioFit.value = "cover";
        } else if (scale < 0.85 && aspectRatioFit.value !== "contain") {
          aspectRatioFit.value = "contain";
        }
        return;
      }

      if (e.touches && e.touches.length === 1) {
        const t = e.touches[0];
        const rect = e.currentTarget.getBoundingClientRect();
        const deltaX = (t.clientX - rect.left) - touchGestureState.startX;
        const deltaY = (t.clientY - rect.top) - touchGestureState.startY;

        // If vertical swipe > 20px and not yet decided
        if (!touchGestureState.mode && Math.abs(deltaY) > 20 && Math.abs(deltaY) > Math.abs(deltaX)) {
          const isLeft = touchGestureState.startX < rect.width * 0.45;
          const isRight = touchGestureState.startX > rect.width * 0.55;
          if (isLeft) {
            touchGestureState.mode = "brightness";
            touchGestureState.startVal = brightnessLevel.value;
          } else if (isRight) {
            touchGestureState.mode = "volume";
            touchGestureState.startVal = volume.value;
          }
        }

        if (touchGestureState.mode === "brightness") {
          const diffY = touchGestureState.startY - (t.clientY - rect.top);
          const sensitivity = 0.45;
          const next = Math.max(30, Math.min(150, Math.round(touchGestureState.startVal + diffY * sensitivity)));
          brightnessLevel.value = next;
          brightnessHUD.value = true;
          if (brightnessTimer) clearTimeout(brightnessTimer);
          brightnessTimer = setTimeout(() => { brightnessHUD.value = false; }, 1200);
        } else if (touchGestureState.mode === "volume") {
          const diffY = touchGestureState.startY - (t.clientY - rect.top);
          const sensitivity = 0.005;
          const nextVol = Math.max(0, Math.min(2.0, touchGestureState.startVal + diffY * sensitivity));
          setVolume(nextVol);
          showVolumeOSD();
        }
      }
    }

    let lastTapInfo = { time: 0, x: 0, y: 0 };
    let lastTouchTime = 0;
    let singleTapTimeout = null;

    function onPlayerTouchEnd(e) {
      if (playerError.value) return;
      if (e.target.closest(".custom-player-controls") || e.target.closest(".shortcuts-modal-card")) return;
      lastTouchTime = Date.now();
      if (touchGestureState.mode === "brightness" || touchGestureState.mode === "volume" || touchGestureState.mode === "pinch") {
        touchGestureState.mode = null;
        return;
      }
      const touch = e.changedTouches ? e.changedTouches[0] : null;
      if (!touch) return;
      const now = Date.now();
      const delta = now - lastTapInfo.time;
      const dist = Math.hypot(touch.clientX - lastTapInfo.x, touch.clientY - lastTapInfo.y);

      if (delta < 320 && dist < 50) {
        // Double tap gesture: Left 40% = -10s, Right 40% = +10s
        if (e.cancelable) e.preventDefault();
        clearTimeout(singleTapTimeout);
        singleTapTimeout = null;
        const rect = e.currentTarget.getBoundingClientRect();
        const touchX = touch.clientX - rect.left;
        if (touchX < rect.width * 0.4) {
          skip(-10);
          triggerDoubleTapRipple("left");
        } else if (touchX > rect.width * 0.6) {
          skip(10);
          triggerDoubleTapRipple("right");
        }
        lastTapInfo = { time: 0, x: 0, y: 0 };
      } else {
        lastTapInfo = { time: now, x: touch.clientX, y: touch.clientY };
        clearTimeout(singleTapTimeout);
        singleTapTimeout = setTimeout(() => {
          // Single tap on mobile ONLY toggles controls, NEVER pauses video
          if (controlsHidden.value) {
            showControls();
          } else {
            controlsHidden.value = true;
          }
          singleTapTimeout = null;
        }, 220);
      }
    }

    function onPlayerTouchCancel() {
      touchGestureState.mode = null;
    }

    function handleContainerClick(e) {
      if (playerError.value) return;
      if (e.target.closest(".custom-player-controls")) return;
      // Prevent synthetic touch clicks from toggling play immediately after tap
      if (Date.now() - lastTouchTime < 1000) return;
      if (controlsHidden.value) {
        showControls();
      } else {
        togglePlay();
      }
    }

    function handleContainerDblClick(e) {
      if (playerError.value) return;
      if (e.target.closest(".custom-player-controls")) return;
      // Strictly ignore dblclick on touch interactions to prevent unfullscreen
      if (Date.now() - lastTouchTime < 1500) return;
      toggleFullscreen();
    }

    function skip(seconds) {
      if (!videoRef.value) return;
      const step = seconds !== undefined && seconds !== null ? seconds : playerSettings.value?.playback?.seek_step || 10;
      const basePos = pendingSeekTarget !== null ? pendingSeekTarget : playerToContent(currentTime.value || 0);
      const maxDur = media.value?.duration || duration.value || 0;
      const targetTime = Math.min(Math.max(0, basePos + step), maxDur > 0 ? maxDur : basePos + step);
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
    let dialogueFilterNode = null;
    let compressorNode = null;

    function initWebAudio() {
      if (audioCtx || !videoRef.value) return;
      try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        audioCtx = new AudioContextClass();
        gainNode = audioCtx.createGain();
        audioSource = audioCtx.createMediaElementSource(videoRef.value);

        dialogueFilterNode = audioCtx.createBiquadFilter();
        dialogueFilterNode.type = "peaking";
        dialogueFilterNode.frequency.setValueAtTime(2200, audioCtx.currentTime);
        dialogueFilterNode.Q.setValueAtTime(1.2, audioCtx.currentTime);
        dialogueFilterNode.gain.setValueAtTime(0, audioCtx.currentTime);

        compressorNode = audioCtx.createDynamicsCompressor();
        compressorNode.threshold.setValueAtTime(-24, audioCtx.currentTime);
        compressorNode.knee.setValueAtTime(12, audioCtx.currentTime);
        compressorNode.ratio.setValueAtTime(1, audioCtx.currentTime);
        compressorNode.attack.setValueAtTime(0.003, audioCtx.currentTime);
        compressorNode.release.setValueAtTime(0.25, audioCtx.currentTime);

        audioSource.connect(dialogueFilterNode);
        dialogueFilterNode.connect(compressorNode);
        compressorNode.connect(gainNode);
        gainNode.connect(audioCtx.destination);

        applyAudioEnhancer();
      } catch (e) {
        console.warn("AudioContext init notice:", e);
      }
    }

    function initAudioBoost() {
      initWebAudio();
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
        icon: ach.icon || "ph-trophy",
        title: store.profile?.is_kids ? `Badge Unlocked: ${ach.title}` : (ach.title || "Achievement Unlocked!"),
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

    let cachedSeekbarRect = null;
    let hoverRafId = null;

    function onSeekbarMouseEnter() {
      if (seekbarRef.value) {
        cachedSeekbarRect = seekbarRef.value.getBoundingClientRect();
      }
    }

    function onSeekbarMouseLeave() {
      showHoverTooltip.value = false;
      cachedSeekbarRect = null;
      if (hoverRafId) {
        cancelAnimationFrame(hoverRafId);
        hoverRafId = null;
      }
    }

    function seekToClick(e) {
      if (!seekbarRef.value || !duration.value) return;
      const rect = cachedSeekbarRect || seekbarRef.value.getBoundingClientRect();
      if (!rect || rect.width <= 0) return;
      const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      // Seekbar is player-relative — seekTo expects CONTENT time
      const targetTime = playerToContent(pos * displayDuration.value);
      seekTo(targetTime);
      unlockAchievementSilently("seeker");
    }

    function hoverSeekbar(e) {
      if (!displayDuration.value) return;
      const clientX = e.clientX;
      if (hoverRafId) cancelAnimationFrame(hoverRafId);
      hoverRafId = requestAnimationFrame(() => {
        if (!cachedSeekbarRect && seekbarRef.value) {
          cachedSeekbarRect = seekbarRef.value.getBoundingClientRect();
        }
        const rect = cachedSeekbarRect;
        if (!rect || rect.width <= 0) return;
        const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        hoverTooltipPos.value = clientX - rect.left;
        hoverTooltipTime.value = pos * displayDuration.value;
        showHoverTooltip.value = true;
      });
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

    // ─── Video Frame Rendering Health Monitor ──────────────────────
    // Detects when the browser is playing audio successfully (currentTime advancing)
    // but failing to decode or display video frames (black screen / unsupported codec).
    let renderHealthTimer = null;
    let lastRenderedFrameTime = 0;
    let lastRenderedFrameCount = 0;
    let lastPlaybackStartTime = 0;
    let rvfcHandle = null;
    let consecutiveZeroFrameChecks = 0;
    let hasAutoFallbackTriggered = false;

    function setupVideoFrameCallback() {
      const v = videoRef.value;
      if (!v) return;
      if ("requestVideoFrameCallback" in v) {
        const onFrame = (now, metadata) => {
          lastRenderedFrameTime = Date.now();
          lastRenderedFrameCount++;
          consecutiveZeroFrameChecks = 0;
          if (videoRef.value && !videoRef.value.paused) {
            try {
              rvfcHandle = videoRef.value.requestVideoFrameCallback(onFrame);
            } catch (e) {}
          }
        };
        try {
          if (rvfcHandle && "cancelVideoFrameCallback" in v) {
            v.cancelVideoFrameCallback(rvfcHandle);
          }
          rvfcHandle = v.requestVideoFrameCallback(onFrame);
        } catch (e) {}
      }
    }

    function checkVideoRenderingHealth() {
      const v = videoRef.value;
      if (!v || v.paused || v.ended || v.seeking || !media.value) {
        consecutiveZeroFrameChecks = 0;
        return;
      }

      const now = Date.now();
      const playingDuration = (now - lastPlaybackStartTime) / 1000;
      const currentPos = v.currentTime || 0;

      // Only check health after playback has been active for at least 2.2 seconds
      if (playingDuration < 2.2 || currentPos < 1.0) {
        return;
      }

      // Read total decoded/rendered video frames from standard or browser APIs
      let decodedFrames = -1;
      try {
        if (typeof v.getVideoPlaybackQuality === "function") {
          const q = v.getVideoPlaybackQuality();
          if (q && typeof q.totalVideoFrames === "number") {
            decodedFrames = q.totalVideoFrames;
          }
        }
      } catch (e) {}

      if (decodedFrames < 0) {
        if (typeof v.webkitDecodedFrameCount === "number") {
          decodedFrames = v.webkitDecodedFrameCount;
        } else if (typeof v.mozDecodedFrames === "number") {
          decodedFrames = v.mozDecodedFrames;
        } else {
          decodedFrames = lastRenderedFrameCount;
        }
      }

      // Check 1: Video dimensions are 0 (e.g., container demuxed audio but dropped video stream)
      const zeroDimensions = v.videoWidth === 0 && v.videoHeight === 0;

      // Check 2: Zero decoded/rendered frames while audio has been playing for > 2.2s
      const zeroDecodedFrames = decodedFrames === 0 && lastRenderedFrameCount === 0;

      // Check 3: Frame rendering froze > 4.5s ago while currentTime continues to advance
      const frameRendererFrozen = lastRenderedFrameTime > 0 && (now - lastRenderedFrameTime > 4500) && (now - lastPlaybackStartTime > 5000);

      if (zeroDimensions || zeroDecodedFrames || frameRendererFrozen) {
        consecutiveZeroFrameChecks++;
        console.warn(`[Player Health] Video rendering issue detected (zeroDimensions: ${zeroDimensions}, zeroFrames: ${zeroDecodedFrames}, frameFrozen: ${frameRendererFrozen}, checkCount: ${consecutiveZeroFrameChecks})`);

        // Check for underlying memory starvation causing frame drop stalls
        if (frameRendererFrozen) {
          checkMemoryPressure();
        }

        // If verified over 2 consecutive checks (~2.4s) and compat transcode not active:
        if (consecutiveZeroFrameChecks >= 2 && !streamState.transcode && !hasAutoFallbackTriggered) {
          hasAutoFallbackTriggered = true;
          console.warn("[Player Health] Video not displaying while audio plays. Auto-switching to converted compatibility stream...");
          addToast("Unsupported video codec — switching to converted playback...", "info");
          enableCompatPlayback();
        }
      } else {
        consecutiveZeroFrameChecks = 0;
      }
    }

    function onVideoPlaying() {
      isPlaying.value = true;
      isBuffering.value = false;
      playerError.value = null;
      lastPlaybackStartTime = Date.now();
      setupVideoFrameCallback();
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

    let lastCueIdx = 0;
    let lastCueTrack = null;

    function findActiveCues(cues, now) {
      if (!cues || cues.length === 0) return [];
      const len = cues.length;

      // 1. Fast sequential check: during normal playback, current/next cue is at or near lastCueIdx
      if (lastCueIdx >= 0 && lastCueIdx < len) {
        const c = cues[lastCueIdx];
        if (c && now >= c.startTime && now <= c.endTime) {
          const active = [sanitizeCueText(c.text)];
          let i = lastCueIdx + 1;
          while (i < len && cues[i].startTime <= now) {
            if (now <= cues[i].endTime) {
              const s = sanitizeCueText(cues[i].text);
              if (s) active.push(s);
            }
            i++;
          }
          let j = lastCueIdx - 1;
          while (j >= 0 && cues[j].endTime >= now) {
            if (now >= cues[j].startTime) {
              const s = sanitizeCueText(cues[j].text);
              if (s) active.unshift(s);
            }
            j--;
          }
          return active.filter(Boolean);
        } else if (lastCueIdx + 1 < len) {
          const next = cues[lastCueIdx + 1];
          if (next && now >= next.startTime && now <= next.endTime) {
            lastCueIdx++;
            return [sanitizeCueText(next.text)].filter(Boolean);
          }
        }
      }

      // 2. Binary search for O(log N) jump when seeking or scene jump
      let low = 0;
      let high = len - 1;
      let bestIdx = -1;

      while (low <= high) {
        const mid = (low + high) >> 1;
        const midCue = cues[mid];
        if (!midCue) break;
        if (midCue.startTime <= now) {
          bestIdx = mid;
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }

      if (bestIdx >= 0) {
        lastCueIdx = bestIdx;
        const active = [];
        let i = bestIdx;
        while (i < len && cues[i].startTime <= now) {
          if (now <= cues[i].endTime) {
            const s = sanitizeCueText(cues[i].text);
            if (s) active.push(s);
          }
          i++;
        }
        let j = bestIdx - 1;
        while (j >= 0 && cues[j].endTime >= now) {
          if (now >= cues[j].startTime) {
            const s = sanitizeCueText(cues[j].text);
            if (s) active.unshift(s);
          }
          j--;
        }
        return active.filter(Boolean);
      }

      return [];
    }

    function updateActiveCueText() {
      try {
        if (!videoRef.value) return;
        const tracks = videoRef.value.textTracks;
        if (!tracks || selectedSub.value < 0 || !tracks[selectedSub.value]) {
          if (activeCueText.value !== "") activeCueText.value = "";
          return;
        }
        const track = tracks[selectedSub.value];
        if (lastCueTrack !== track) {
          lastCueTrack = track;
          lastCueIdx = 0;
        }
        const offsetSec = (subOffsetMs.value || 0) / 1000;
        const now = currentTime.value - offsetSec;

        // Primary: fast binary search + sequential pointer scan
        if (track.cues && track.cues.length > 0) {
          const active = findActiveCues(track.cues, now);
          const newText = active.length > 0 ? active.join("\n") : "";
          if (activeCueText.value !== newText) {
            activeCueText.value = newText;
          }
          return;
        }

        // Secondary fallback: browser-managed activeCues
        if (track.activeCues && track.activeCues.length > 0) {
          const active = [];
          for (let i = 0; i < track.activeCues.length; i++) {
            if (track.activeCues[i]) {
              const s = sanitizeCueText(track.activeCues[i].text);
              if (s) active.push(s);
            }
          }
          const newText = active.length > 0 ? active.join("\n") : "";
          if (activeCueText.value !== newText) {
            activeCueText.value = newText;
          }
          return;
        }

        if (activeCueText.value !== "") {
          activeCueText.value = "";
        }
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

    const customBlobUrls = [];

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
        customBlobUrls.push(url);
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
        addToast("Entered Picture-in-Picture", "info");
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
      if (isLightMode.value) return;
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
          addToast(`${r.message} — reloading subtitles`, "success", 5000);
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
      checkCreditsShrink();
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
      // ─── Web Audio API (Dialogue Boost & Night Mode) ─────────────
      if (audioEnhancerMode.value !== "off") {
        initWebAudio();
        applyAudioEnhancer();
      }
    }

    // ─── Web Audio API (Dialogue Boost & Night Mode) ─────────────
    const audioEnhancerMode = ref(localStorage.getItem("capsstream_audio_enhancer") || "off");

    function applyAudioEnhancer() {
      if (!audioCtx || !dialogueFilterNode || !compressorNode) return;
      if (audioCtx.state === "suspended") {
        audioCtx.resume().catch(() => {});
      }
      const t = audioCtx.currentTime;
      if (audioEnhancerMode.value === "dialogue") {
        dialogueFilterNode.gain.setTargetAtTime(5.0, t, 0.05);
        compressorNode.ratio.setTargetAtTime(1.5, t, 0.05);
        compressorNode.threshold.setTargetAtTime(-20, t, 0.05);
      } else if (audioEnhancerMode.value === "night") {
        dialogueFilterNode.gain.setTargetAtTime(6.0, t, 0.05);
        compressorNode.ratio.setTargetAtTime(8.0, t, 0.05);
        compressorNode.threshold.setTargetAtTime(-26, t, 0.05);
      } else {
        dialogueFilterNode.gain.setTargetAtTime(0, t, 0.05);
        compressorNode.ratio.setTargetAtTime(1.0, t, 0.05);
      }
    }

    function setAudioEnhancerMode(mode) {
      audioEnhancerMode.value = mode;
      localStorage.setItem("capsstream_audio_enhancer", mode);
      if (mode !== "off") {
        initWebAudio();
      }
      applyAudioEnhancer();
    }

    // ─── Inactivity Sleep Prompt (Netflix Style) ─────────────────
    const showInactivityPrompt = ref(false);
    const consecutiveAutoAdvances = ref(0);
    const inactivitySleepLimit = computed(() => {
      const p = store.profile?.inactivity_sleep_limit ?? playerSettings.value?.playback?.inactivity_sleep_limit;
      if (p !== undefined && p !== null) return Number(p);
      return 3;
    });

    function resetInactivityCounter() {
      consecutiveAutoAdvances.value = 0;
      showInactivityPrompt.value = false;
    }

    function confirmStillWatching() {
      resetInactivityCounter();
      if (videoRef.value) {
        videoRef.value.play().catch(() => {});
      }
    }

    // ─── End-Credits Shrink & Next Episode Preview ───────────────
    const showCreditsShrink = ref(false);
    const creditsShrinkDismissed = ref(false);

    function checkCreditsShrink() {
      if (!isSeriesMedia.value || !hasNextEp.value || creditsShrinkDismissed.value || isEnded.value) {
        return;
      }
      const curr = currentTime.value;
      const dur = displayDuration.value;
      let shouldShrink = false;

      if (skipTimes.value?.ed && skipTimes.value.ed.start > 0) {
        if (curr >= skipTimes.value.ed.start) {
          shouldShrink = true;
        }
      } else if (media.value?.outro_start && media.value.outro_start > 0) {
        if (curr >= media.value.outro_start) {
          shouldShrink = true;
        }
      } else if (dur > 90 && (dur - curr) <= 30) {
        shouldShrink = true;
      }

      if (shouldShrink && !showCreditsShrink.value) {
        showCreditsShrink.value = true;
        startAutoAdvanceCountdown(10.0);
      }
    }

    function dismissCreditsShrink() {
      showCreditsShrink.value = false;
      creditsShrinkDismissed.value = true;
      cancelAutoAdvance();
    }

    const isEnded = ref(false);
    const nextEpCountdownSeconds = ref(5);
    const nextEpProgressPercent = ref(0);
    let autoAdvanceInterval = null;

    function startAutoAdvanceCountdown(durationSec = 5.0) {
      cancelAutoAdvance();
      isEnded.value = true;
      controlsHidden.value = false;
      nextEpCountdownSeconds.value = durationSec;
      nextEpProgressPercent.value = 0;

      const startTime = Date.now();

      autoAdvanceInterval = setInterval(() => {
        const elapsed = (Date.now() - startTime) / 1000;
        const remaining = Math.max(0, durationSec - elapsed);
        nextEpCountdownSeconds.value = remaining;
        nextEpProgressPercent.value = Math.min(100, (elapsed / durationSec) * 100);

        if (remaining <= 0) {
          cancelAutoAdvance();
          playNext(true);
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
      playNext(false);
      unlockAchievementSilently("next_ep_advance");
    }

    // ─── In-Player Episodes & Seasons Drawer ──────────────────────
    const showEpisodesDrawer = ref(false);
    const seriesData = ref(null);
    const activeDrawerSeason = ref(1);

    const isSeriesMedia = computed(() => {
      if (!media.value) return false;
      return media.value.type === "series" || media.value.type === "anime" || (seriesData.value && Object.keys(seriesData.value.seasons || {}).length > 0);
    });

    const drawerSeasonsList = computed(() => {
      if (!seriesData.value?.seasons) return [];
      return Object.keys(seriesData.value.seasons).map(Number).sort((a, b) => a - b);
    });

    const drawerEpisodesList = computed(() => {
      if (!seriesData.value?.seasons) return [];
      const eps = seriesData.value.seasons[activeDrawerSeason.value] || [];
      return eps.slice().sort((a, b) => (a.episode || 0) - (b.episode || 0));
    });

    function toggleEpisodesDrawer() {
      showEpisodesDrawer.value = !showEpisodesDrawer.value;
      if (showEpisodesDrawer.value) {
        showQueueDrawer.value = false;
        showSpeedMenu.value = false;
        showSubMenu.value = false;
        showAudioMenu.value = false;
        showQualityMenu.value = false;
        showControls();
        if (media.value?.season) {
          activeDrawerSeason.value = Number(media.value.season) || 1;
        }
        Vue.nextTick(() => {
          const listEl = document.querySelector(".episodes-drawer-list");
          const activeEl = listEl?.querySelector(".drawer-ep-item.active-playing");
          if (listEl && activeEl) {
            const targetScroll = activeEl.offsetTop - (listEl.clientHeight / 2) + (activeEl.clientHeight / 2);
            listEl.scrollTo({ top: Math.max(0, targetScroll), behavior: "smooth" });
          }
        });
      }
    }

    function playEpisodeFromDrawer(ep) {
      if (ep.is_local === false || ep.is_mounted === false) {
        addToast(ep.is_mounted === false ? "This episode is on an unmounted drive" : "This episode is not downloaded locally", "warning");
        return;
      }
      if (!ep.id || Number(ep.id) === Number(media.value?.id)) return;
      showEpisodesDrawer.value = false;
      router.push(`/watch/${ep.id}`);
    }


    // ─── Queue & Playlist Drawer ─────────────────────────────────
    const showQueueDrawer = ref(false);

    function toggleQueueDrawer() {
      showQueueDrawer.value = !showQueueDrawer.value;
      if (showQueueDrawer.value) {
        showEpisodesDrawer.value = false;
        showControls();
      }
    }

    function toggleQueueShuffle() {
      store.queueShuffle = !store.queueShuffle;
      if (store.queueShuffle && store.queue && store.queue.length > 1) {
        const curr = store.queue[store.queueIndex] || store.queue[0];
        const rest = store.queue.filter((_, idx) => idx !== store.queueIndex);
        for (let i = rest.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [rest[i], rest[j]] = [rest[j], rest[i]];
        }
        store.queue = [curr, ...rest];
        store.queueIndex = 0;
        addToast("Queue shuffled", "info");
      }
    }

    function cycleQueueRepeat() {
      if (store.queueRepeat === "off") store.queueRepeat = "all";
      else if (store.queueRepeat === "all") store.queueRepeat = "one";
      else store.queueRepeat = "off";
    }

    function clearActiveQueue() {
      store.queue = [];
      store.queueIndex = -1;
      store.queuePlaylistId = null;
      store.queuePlaylistName = "";
      showQueueDrawer.value = false;
      addToast("Queue cleared", "info");
    }

    function playQueueItem(index) {
      if (!store.queue || !store.queue[index]) return;
      store.queueIndex = index;
      const target = store.queue[index];
      router.push(`/watch/${target.id}`);
    }

    function moveQueueItem(index, direction) {
      const targetIdx = index + direction;
      if (!store.queue || targetIdx < 0 || targetIdx >= store.queue.length) return;
      const moved = [...store.queue];
      [moved[index], moved[targetIdx]] = [moved[targetIdx], moved[index]];
      store.queue = moved;
      if (store.queueIndex === index) store.queueIndex = targetIdx;
      else if (store.queueIndex === targetIdx) store.queueIndex = index;
    }

    function removeQueueItem(index) {
      if (!store.queue || index < 0 || index >= store.queue.length) return;
      const removed = store.queue[index];
      store.queue.splice(index, 1);
      if (store.queueIndex > index) store.queueIndex--;
      else if (store.queueIndex >= store.queue.length) {
        store.queueIndex = Math.max(0, store.queue.length - 1);
      }
      addToast(`Removed "${removed.title}" from queue`, "info");
    }

    function onEnded() {
      isPlaying.value = false;
      // 1. If repeat 'one' is active
      if (store.queueRepeat === "one" && videoRef.value) {
        seekTo(0);
        videoRef.value.play().catch(() => {});
        return;
      }

      // 2. If active queue has next item
      if (store.queue && store.queue.length > 0) {
        if (store.queueIndex + 1 < store.queue.length) {
          playQueueItem(store.queueIndex + 1);
          return;
        } else if (store.queueRepeat === "all" && store.queue.length > 0) {
          playQueueItem(0);
          return;
        }
      }

      // 3. Fallback to normal auto-play next episode
      const autoNext = playerSettings.value?.playback?.auto_play_next !== false;
      if (showNextEp.value && autoNext) {
        startAutoAdvanceCountdown();
      }
    }

    let consecutiveErrorCount = 0;
    let lastErrorTimestamp = 0;

    function onVideoError(e) {
      const v = videoRef.value;
      if (!v || !v.currentSrc || v.currentSrc.endsWith('/stream/') || v.currentSrc.endsWith('/null') || v.currentSrc.endsWith('/undefined')) {
        return;
      }
      // MEDIA_ERR_ABORTED (code 1) occurs normally during stream resets and episode transitions
      if (!v.error || v.error.code === 0 || v.error.code === 1) {
        return;
      }
      if (v.currentSrc && v.currentSrc.includes('/api/stream/')) {
        console.error("[HTML5 Player Error]", e, "code:", v.error.code, "msg:", v.error.message);

        const now = Date.now();
        if (now - lastErrorTimestamp < 3500) {
          consecutiveErrorCount++;
        } else {
          consecutiveErrorCount = 1;
        }
        lastErrorTimestamp = now;

        // If native direct playback encountered network (code 2), decode (code 3), or unsupported source (code 4),
        // seamlessly switch to hardware-accelerated/smart converted playback
        if (!streamState.transcode && (v.error.code === 2 || v.error.code === 3 || v.error.code === 4)) {
          console.warn("[HTML5 Player] Video decode/pipeline error natively (code " + v.error.code + "). Seamlessly switching to smart converted playback...");
          addToast("Optimizing media stream for smooth playback...", "info");
          playerError.value = null;
          enableCompatPlayback(true);
          return;
        }

        // If converted stream encountered a hiccup, reconnect at keyframe
        if (streamState.transcode && consecutiveErrorCount < 3) {
          console.warn("[HTML5 Player] Converted stream hiccup — reconnecting at keyframe...");
          playerError.value = null;
          enableCompatPlayback(true);
          return;
        }

        // If we have failed repeatedly (>= 3 times within 3.5s), stop auto-reconnecting
        if (consecutiveErrorCount >= 3) {
          console.warn("[HTML5 Player] Multiple consecutive playback errors encountered. Halting auto-retry loop.");
          const p = (media.value?.file_path || "").toLowerCase();
          const isHeavy4k = p.includes("2160") || p.includes("4k") || p.includes("uhd");
          playerError.value = isHeavy4k
            ? "Playback failed — 4K/HEVC content needs hardware acceleration or converted playback. Click 'Play Converted' or 'Resume' below."
            : "The stream encountered an issue. Click 'Play Converted' or 'Resume Playback' to continue.";
        }
      }
    }

    // ─── Error recovery: reload the stream and resume from last position ──
    const recovering = ref(false);

    async function recoverFromError() {
      const v = videoRef.value;
      if (!v) return;
      recovering.value = true;
      playerError.value = null;
      consecutiveErrorCount = 0;
      try {
        await enableCompatPlayback(true);
      } catch (e) {
        console.warn("[Player] Recovery failed:", e);
        playerError.value = "Could not reconnect to the stream. Try refreshing or relaunching the server.";
      } finally {
        recovering.value = false;
      }
    }

    // ─── Low-Memory Protection & In-Place Player Recovery ───────────
    let lastMemoryCheckTime = 0;

    async function checkMemoryPressure() {
      const now = Date.now();
      if (now - lastMemoryCheckTime < 8000) return;
      lastMemoryCheckTime = now;

      // 1. Check Browser JS Heap if available
      if (window.performance && window.performance.memory) {
        try {
          const { usedJSHeapSize, jsHeapSizeLimit } = window.performance.memory;
          if (jsHeapSizeLimit > 0 && usedJSHeapSize / jsHeapSizeLimit > 0.85) {
            if (!lowMemoryBanner.value) {
              lowMemoryBanner.value = {
                message: "High browser memory usage detected • Light mode active",
              };
              isLightMode.value = true;
              thumbSheet.value = null;
              saveProgressNow();
            }
            return;
          }
        } catch (e) {}
      }

      // 2. Query lightweight backend host RAM health check
      try {
        const res = await API.get("/api/system/health-status");
        if (res && res.is_low_memory) {
          if (!lowMemoryBanner.value) {
            lowMemoryBanner.value = {
              message: `System RAM high (${res.ram_load_pct}%) • Light mode active`,
            };
            isLightMode.value = true;
            thumbSheet.value = null;
            saveProgressNow();
          }
        }
      } catch (e) {}
    }

    function dismissLowMemoryBanner() {
      lowMemoryBanner.value = null;
    }

    async function freeMemoryAndRecover() {
      if (recoveringMemory.value) return;
      recoveringMemory.value = true;
      try {
        // 1. Immediately persist watch progress so position is secure
        await saveProgressNow();

        // 2. Activate light mode and discard heavy thumbnail sprite sheets
        isLightMode.value = true;
        thumbSheet.value = null;
        clearTimeout(thumbRetryTimer);

        // 3. Capture current content timestamp
        const at = Math.max(0, currentContentTime());

        // 4. Release media element / video buffer to clear GPU and memory allocations
        const v = videoRef.value;
        if (v) {
          try {
            v.pause();
            v.removeAttribute("src");
            v.load();
          } catch (e) {}
        }

        // 5. Short pause to let browser GC reclaim memory
        await new Promise((r) => setTimeout(r, 120));

        // 6. Re-anchor stream cleanly at the exact content timestamp
        swapStream(at, true);
        addToast("Memory cleared • Playback re-anchored", "success", 4000);
        lowMemoryBanner.value = null;
      } catch (err) {
        console.error("[Player] freeMemoryAndRecover error:", err);
      } finally {
        recoveringMemory.value = false;
      }
    }

    // Fast-recovery Watchdog: detects stalled decoders and buffered freezes
    let lastStallCheckTime = Date.now();
    let lastStallVideoTime = -1;
    let stallDurationSec = 0;
    let autoRecoverAttempts = 0;

    function checkPlaybackStall() {
      const v = videoRef.value;
      if (!v || v.paused || v.ended || v.seeking || !media.value || showResumeModal.value) {
        stallDurationSec = 0;
        lastStallVideoTime = v ? v.currentTime : -1;
        lastStallCheckTime = Date.now();
        return;
      }

      const now = Date.now();
      const deltaReal = (now - lastStallCheckTime) / 1000;
      lastStallCheckTime = now;

      const curr = v.currentTime;
      // If playback position has advanced by at least 0.2s, video is actively progressing
      if (lastStallVideoTime >= 0 && Math.abs(curr - lastStallVideoTime) >= 0.2) {
        stallDurationSec = 0;
        autoRecoverAttempts = 0;
        lastStallVideoTime = curr;
        if (playerError.value && (playerError.value.includes("stuck") || playerError.value.includes("Stuck") || playerError.value.includes("stalled"))) {
          playerError.value = null; // recovered on its own
        }
        return;
      }

      lastStallVideoTime = curr;
      stallDurationSec += deltaReal;

      // Smart Watchdog: check memory pressure if video begins stalling
      if (stallDurationSec >= 2.0) {
        checkMemoryPressure();
      }

      // Smart Watchdog: if playback freezes for >= 3.5s while active, attempt auto-recovery
      if (stallDurationSec >= 3.5 && autoRecoverAttempts < 2) {
        autoRecoverAttempts++;
        stallDurationSec = 0;
        console.warn(`[Player Watchdog] Stalled stream detected (attempt ${autoRecoverAttempts}/2). Reconnecting...`);
        addToast("Stream buffer stalled — auto-recovering...", "info");
        if (!streamState.transcode) {
          enableCompatPlayback(true);
        } else {
          const at = currentContentTime();
          alignedStreamStart(at).then((startAt) => {
            streamState.streamStart = startAt;
            swapStream(0, true);
          });
        }
        return;
      }

      // If stall persists after auto-recovery attempts (>= 8s continuous freeze)
      if (stallDurationSec >= 8) {
        const p = (media.value?.file_path || "").toLowerCase();
        const heavy = p.includes("2160") || p.includes("4k") || p.includes("uhd") ||
                      (codecInfo.value?.tags || []).some((t) => t.includes("HEVC"));
        if (heavy) {
          // For 4K/HEVC: show non-blocking stutter banner — ask before switching, don't block player
          if (!stutter4KBanner.value) {
            stutter4KBanner.value = true;
          }
        } else {
          // For standard content: show full-screen error overlay as usual
          playerError.value = "Playback appears stuck. Use Resume Playback to reload the stream from where you left off.";
        }
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
      // Block all shortcuts while error overlay is shown
      if (playerError.value) return;
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
        case "e":
        case "E":
          e.preventDefault();
          if (isSeriesMedia.value) toggleEpisodesDrawer();
          break;
        case "q":
        case "Q":
          e.preventDefault();
          toggleQueueDrawer();
          break;
        case "n":
        case "N":
          e.preventDefault();
          if (hasNextEp.value) handleNextEpClick();
          break;
        case "s":
        case "S":
          if (activeSkipAction.value) {
            e.preventDefault();
            executeSkipAction();
          }
          break;
        case "Escape":
          if (showEpisodesDrawer.value) {
            e.preventDefault();
            showEpisodesDrawer.value = false;
          } else if (showQueueDrawer.value) {
            e.preventDefault();
            showQueueDrawer.value = false;
          }
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

    async function lockLandscapeOrientation() {
      try {
        if (screen.orientation && screen.orientation.lock) {
          await screen.orientation.lock("landscape").catch(() => {});
        } else if (screen.lockOrientation) {
          screen.lockOrientation("landscape");
        } else if (screen.mozLockOrientation) {
          screen.mozLockOrientation("landscape");
        } else if (screen.msLockOrientation) {
          screen.msLockOrientation("landscape");
        }
      } catch (e) {}
    }

    function unlockOrientation() {
      try {
        if (screen.orientation && screen.orientation.unlock) {
          screen.orientation.unlock();
        } else if (screen.unlockOrientation) {
          screen.unlockOrientation();
        } else if (screen.mozUnlockOrientation) {
          screen.mozUnlockOrientation();
        } else if (screen.msUnlockOrientation) {
          screen.msUnlockOrientation();
        }
      } catch (e) {}
    }

    function handleFullscreenChange() {
      const isFull = !!(document.fullscreenElement || document.webkitFullscreenElement);
      isFullscreen.value = isFull;
      if (isFull) {
        lockLandscapeOrientation();
      } else {
        unlockOrientation();
      }
    }

    function toggleFullscreen() {
      if (!videoRef.value) return;
      const v = videoRef.value;
      const container = v.closest(".custom-player-wrapper") || v;
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

      // On iOS Safari, standard container.requestFullscreen() fails on phones; webkitEnterFullscreen gives native landscape player
      if (isIOS && v.webkitEnterFullscreen && !v.webkitDisplayingFullscreen) {
        try {
          v.webkitEnterFullscreen();
          isFullscreen.value = true;
          return;
        } catch (e) {}
      }

      if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        const req = container.requestFullscreen || container.webkitRequestFullscreen || container.mozRequestFullScreen || container.msRequestFullscreen;
        if (req) {
          const p = req.call(container);
          if (p && p.then) {
            p.then(() => {
              lockLandscapeOrientation();
            }).catch(() => {
              if (v.requestFullscreen) v.requestFullscreen().then(lockLandscapeOrientation).catch(() => {});
              else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen();
            });
          } else {
            lockLandscapeOrientation();
          }
        } else if (v.webkitEnterFullscreen) {
          v.webkitEnterFullscreen();
        }
        isFullscreen.value = true;
      } else {
        const exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
        if (exit) {
          exit.call(document);
        }
        unlockOrientation();
        isFullscreen.value = false;
      }
      API.post("/api/achievements/unlock", { achievement_id: "fullscreen_pro" }).then((res) => {
        if (res && res.unlocked) {
          addToast(`Achievement Unlocked: ${res.unlocked.icon} ${res.unlocked.title}!`, "success");
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
      hasAutoFallbackTriggered = false;
      consecutiveZeroFrameChecks = 0;
      lastRenderedFrameCount = 0;
      lastRenderedFrameTime = 0;
      lastPlaybackStartTime = 0;
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
      }

      try {
        media.value = await API.get(`/api/media/${mediaId}`);
        subtitles.value = media.value.subtitles || [];

        // Pre-emptive compatibility check: if media is HEVC and browser lacks native decode support
        const vInfo = media.value.video_info || {};
        const codecTag = (vInfo.codec || "").toLowerCase();
        const filePath = (media.value.file_path || "").toLowerCase();
        const isHevc = codecTag.includes("265") || codecTag.includes("hevc") || filePath.includes("x265") || filePath.includes("hevc") || filePath.includes("h.265");

        if (isHevc && !hevcSupported && !streamState.transcode) {
          console.info("[Player] HEVC content detected on browser without native HEVC decoder. Starting in converted mode...");
          streamState.transcode = true;
        }

        // ── 4K Hardware / Browser Compatibility Guard (Smart Auto-Switch) ──
        const is4KInitial = (media.value?.base_label || "").startsWith("4K") ||
                            (media.value?.video_info?.height >= 2160 || media.value?.video_info?.width >= 3840) ||
                            (media.value?.height >= 2160 || media.value?.width >= 3840) ||
                            (filePath.includes("2160p") || filePath.includes("4k") || filePath.includes("uhd"));

        const check4KEnabled = playerSettings.value?.playback?.check_4k_compat !== false;
        if (is4KInitial && !streamState.transcode && check4KEnabled) {
          const compat = await check4KCompatibility();
          if (!compat.compatible) {
            const currentOpt = (qualityOptions.value || []).find((o) => o.media_id === selectedQualityMediaId.value);
            const fallback = (qualityOptions.value || []).find(
              (o) => !(o.base_label || o.resolution || "").startsWith("4K") && o.media_id !== selectedQualityMediaId.value
            ) || null;
            if (fallback) {
              // Silently switch to fallback quality and show undo pill (non-blocking)
              setAutoSwitched4K({
                label: fallback.display_label || fallback.base_label || "1080p",
                original4kOption: currentOpt || null,
              });
              selectedQualityMediaId.value = fallback.media_id;
              streamState.mediaId = fallback.media_id;
            }
          }
        }

        // ── Codec Compatibility Notice (HEVC / 10-Bit Color / AV1) ──
        const activeOpt = (qualityOptions.value || []).find((o) => o.media_id === selectedQualityMediaId.value);
        const activePath = activeOpt?.file_path || media.value?.file_path || filePath || "";
        triggerCodecNotice(activePath);

        // Auto-download subtitles via OpenSubtitles when none exist and enabled
        if (!subtitles.value.length) {
          maybeAutoDownloadSubs();
        }

        applyResumedProgress();

        // Auto-select preferred subtitle language if auto_load enabled or profile default set
        if (subtitles.value.length > 0) {
          const profSub = (store.profile?.default_sub_lang || "").toLowerCase();
          if (profSub === "off") {
            selectSub(-1);
          } else {
            const autoLoad = playerSettings.value?.subtitles?.auto_load !== false;
            if (autoLoad || profSub) {
              let prefLang = profSub || (playerSettings.value?.subtitles?.preferred_language || "en").toLowerCase();
              if (prefLang === "auto") prefLang = "en";
              const prefIdx = subtitles.value.findIndex((s) => (s.language || "").toLowerCase().startsWith(prefLang) || (s.label || "").toLowerCase().includes(prefLang));
              const defaultIdx = prefIdx >= 0 ? prefIdx : 0;
              selectSub(defaultIdx);
            }
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

      // Prioritize profile's preferred audio language if available
      const profAudio = (store.profile?.default_audio_lang || "").toLowerCase();
      let targetAudio = null;
      if (profAudio && audioTracks.value.length > 0) {
        targetAudio = audioTracks.value.find((t) => (t.language || "").toLowerCase().startsWith(profAudio) || (t.title || "").toLowerCase().includes(profAudio));
      }
      if (!targetAudio) {
        targetAudio = audioTracks.value.find((t) => t.default) || audioTracks.value[0];
      }
      defaultAudioIndex.value = targetAudio ? targetAudio.index : 0;
      streamState.audioTrack = defaultAudioIndex.value;

      if (media.value.type !== "movie" && media.value.tmdb_id) {
        try {
          const show = await API.get(`/api/show/${media.value.tmdb_id}?type=${media.value.type}`);
          seriesData.value = show;
          if (media.value.season) {
            activeDrawerSeason.value = Number(media.value.season) || 1;
          }
          const allEps = Object.values(show.seasons || {})
            .flat()
            .sort((a, b) => {
              if (a.season !== b.season) return (a.season || 0) - (b.season || 0);
              return (a.episode || 0) - (b.episode || 0);
            });
          const idx = allEps.findIndex(
            (e) => e.id === Number(mediaId) || (e.season === media.value.season && e.episode === media.value.episode)
          );
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
          seriesData.value = null;
        }
      } else {
        nextEp.value = null;
        seriesData.value = null;
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

      // Active video rendering health check — ensures video frames are decoding alongside audio
      renderHealthTimer = setInterval(() => checkVideoRenderingHealth(), 1200);

      // Periodic system & browser memory health check
      memoryHealthTimer = setInterval(() => checkMemoryPressure(), 25000);

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

    async function playNext(isAuto = false) {
      await saveProgressNow();
      if (isAuto) {
        consecutiveAutoAdvances.value++;
        if (inactivitySleepLimit.value > 0 && consecutiveAutoAdvances.value >= inactivitySleepLimit.value) {
          if (videoRef.value) videoRef.value.pause();
          showInactivityPrompt.value = true;
          return;
        }
      } else {
        consecutiveAutoAdvances.value = 0;
      }
      if (videoRef.value) {
        videoRef.value.pause();
        try { videoRef.value.currentTime = 0; } catch (e) {}
      }
      currentTime.value = 0;
      showResumeModal.value = false;
      resumeTime.value = 0;
      hasResumedProgress = false;
      showCreditsShrink.value = false;
      creditsShrinkDismissed.value = false;
      if (nextEp.value && nextEp.value.id && nextEp.value.is_local !== false && nextEp.value.is_mounted !== false) {
        router.push(`/watch/${nextEp.value.id}`);
      }
    }

    onMounted(() => {
      initPlayer();
      document.addEventListener("fullscreenchange", handleFullscreenChange);
      document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
      if (videoRef.value) {
        videoRef.value.addEventListener("webkitbeginfullscreen", () => {
          isFullscreen.value = true;
        });
        videoRef.value.addEventListener("webkitendfullscreen", () => {
          isFullscreen.value = false;
          unlockOrientation();
        });
      }
    });

    onUnmounted(() => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
      unlockOrientation();
      cancelAutoAdvance();
      saveProgressNow();
      detachRemoteAudio();
      clearInterval(progressTimer);
      clearInterval(stallTimer);
      clearInterval(renderHealthTimer);
      if (memoryHealthTimer) clearInterval(memoryHealthTimer);
      if (rvfcHandle && videoRef.value && "cancelVideoFrameCallback" in videoRef.value) {
        try { videoRef.value.cancelVideoFrameCallback(rvfcHandle); } catch (e) {}
      }
      clearTimeout(hideTimer);
      clearTimeout(thumbRetryTimer);
      clearTimeout(volumeOSDTimer);
      clearTimeout(seekOSDTimer);
      clearTimeout(nextEpHideTimer);
      if (seekDebounceTimer) { clearTimeout(seekDebounceTimer); seekDebounceTimer = null; }
      pendingSeekTarget = null;
      if (playerAchTimer) clearTimeout(playerAchTimer);
      if (hoverRafId) cancelAnimationFrame(hoverRafId);

      window.removeEventListener("pagehide", flushProgressOnHide);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("keydown", handleKeyboard);

      if (codecNoticeTimer) { clearTimeout(codecNoticeTimer); codecNoticeTimer = null; }
      if (autoSwitched4KTimer) { clearTimeout(autoSwitched4KTimer); autoSwitched4KTimer = null; }
      codecNoticePill.value = null;
      isCodecNoticeActive.value = false;
      autoSwitched4K.value = null;

      // Clean up Web Audio graph
      if (audioCtx) {
        try {
          if (compressorNode) compressorNode.disconnect();
          if (dialogueFilterNode) dialogueFilterNode.disconnect();
          if (audioSource) audioSource.disconnect();
          audioCtx.close().catch(() => {});
        } catch (e) {}
        audioCtx = null;
        audioSource = null;
        dialogueFilterNode = null;
        compressorNode = null;
      }

      // Revoke any custom uploaded subtitle blob URLs
      for (const u of customBlobUrls) {
        try { URL.revokeObjectURL(u); } catch (e) {}
      }
      customBlobUrls.length = 0;

      // Release hardware video decoder context
      const v = videoRef.value;
      if (v) {
        try {
          v.pause();
          v.removeAttribute("src");
          v.load();
        } catch (e) {}
      }
    });

    watch(
      () => route.params.id,
      () => {
        cancelAutoAdvance();
        clearInterval(progressTimer);
        clearInterval(stallTimer);
        clearInterval(renderHealthTimer);
        if (memoryHealthTimer) clearInterval(memoryHealthTimer);
        if (seekDebounceTimer) { clearTimeout(seekDebounceTimer); seekDebounceTimer = null; }
        pendingSeekTarget = null;
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
        if (codecNoticeTimer) { clearTimeout(codecNoticeTimer); codecNoticeTimer = null; }
        if (autoSwitched4KTimer) { clearTimeout(autoSwitched4KTimer); autoSwitched4KTimer = null; }
        codecNoticePill.value = null;
        isCodecNoticeActive.value = false;
        autoSwitched4K.value = null;
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
      codecNoticePill,
      isCodecNoticeActive,
      dismissCodecNotice,
      onCodecNoticeAfterLeave,
      dismissAutoSwitched4K,
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
      handleContainerDblClick,
      skip,
      toggleMute,
      onVolumeInput,
      seekToClick,
      hoverSeekbar,
      onSeekbarMouseEnter,
      onSeekbarMouseLeave,
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
      recoverFromError,
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
      audioEnhancerMode,
      setAudioEnhancerMode,
      showInactivityPrompt,
      consecutiveAutoAdvances,
      confirmStillWatching,
      showCreditsShrink,
      dismissCreditsShrink,
      showEpisodesDrawer,
      toggleEpisodesDrawer,
      seriesData,
      activeDrawerSeason,
      drawerSeasonsList,
      drawerEpisodesList,
      playEpisodeFromDrawer,
      calcProgressPercent,
      isSeriesMedia,
      showQueueDrawer,
      toggleQueueDrawer,
      toggleQueueShuffle,
      cycleQueueRepeat,
      clearActiveQueue,
      playQueueItem,
      moveQueueItem,
      removeQueueItem,
      onPlayerTouchStart,
      onPlayerTouchMove,
      onPlayerTouchEnd,
      onPlayerTouchCancel,
      handleContainerClick,
      doubleTapRipple,
      brightnessHUD,
      brightnessLevel,
      aspectRatioFit,
      cycleAspectRatio,
      autoSwitched4K,
      stutter4KBanner,
      force4KPlayback,
      stutter4KAutoSwitch,
      lowMemoryBanner,
      isLightMode,
      recoveringMemory,
      freeMemoryAndRecover,
      dismissLowMemoryBanner,
      checkMemoryPressure,
    };
  },
};

// ─── Browse Page ──────────────────────────────────────────────


window.PlayerPage = PlayerPage;
})();
