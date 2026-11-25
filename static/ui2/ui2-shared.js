/* CapsStream New UI 2.0 — Shared State, Ambient Glow & Cards */
(function () {
  const { reactive, computed, ref } = Vue;

  const ui2State = reactive({
    view: "home", // home | anime | discover | library | detail | person
    detailItem: null,
    fullDetailItem: null,
    personTarget: null,
    searchOpen: false,
    settingsOpen: false,
    ambientEnabled: localStorage.getItem("cs_ui2_bg_show") !== "false",
    ambientIntensity: Number(localStorage.getItem("cs_ui2_bg_intensity") || 45),
    lowPower: localStorage.getItem("cs_low_power") === "true",
    bgPreset: localStorage.getItem("cs_ui2_bg_preset") || "Mood",
    ambientColors: ["rgba(229, 9, 20, 0.22)", "rgba(56, 189, 248, 0.16)"],
    watchlistIds: new Set(),
  });

  function setAmbientForItem(item) {
    const seed = String(item?.id || item?.tmdb_id || item?.title || "0");
    let hash = 0;
    for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
    const warm = Math.abs(hash) % 2 === 0;
    ui2State.ambientColors = warm
      ? ["rgba(234, 88, 12, 0.24)", "rgba(37, 99, 235, 0.16)"]
      : ["rgba(56, 189, 248, 0.22)", "rgba(229, 9, 20, 0.16)"];
  }

  function formatMeta(item) {
    if (!item) return "";
    const parts = [];
    if (item.rating) parts.push("★ " + Number(item.rating).toFixed(1));
    if (item.year) parts.push(item.year);
    if (item.type) {
      const t = item.type === "movie" ? "Film" : item.type === "anime" ? "Anime" : "Series";
      parts.push(t);
    }
    return parts.join(" / ");
  }

  function timeLeftLabel(item) {
    const dur = Number(item?.duration || 0);
    const pos = Number(item?.position || 0);
    if (dur > 0 && pos >= 0 && dur > pos) {
      const mins = Math.max(1, Math.round((dur - pos) / 60));
      return mins + "m left";
    }
    return "";
  }

  function progressPct(item) {
    if (item?.progress_percent != null) return Math.min(100, Math.max(0, Math.round(item.progress_percent)));
    const dur = Number(item?.duration || 0);
    const pos = Number(item?.position || 0);
    if (dur > 0 && pos > 0) return Math.min(100, Math.round((pos / dur) * 100));
    return 0;
  }

  async function toggleWatchlist(item) {
    const id = item?.id || item?.tmdb_id;
    if (!id) return;
    try {
      await window.API.post("/api/favorites/toggle", { media_id: id });
      if (ui2State.watchlistIds.has(id)) {
        ui2State.watchlistIds.delete(id);
        window.addToast?.("Removed from Watchlist", "info");
      } else {
        ui2State.watchlistIds.add(id);
        window.addToast?.("Added to Watchlist", "success");
      }
    } catch (e) {
      window.addToast?.("Could not update Watchlist", "error");
    }
  }

  function playItem(item) {
    if (!item?.id) return;
    window.__capsRouter?.push("/watch/" + item.id);
  }

  function openDetailsModal(item) {
    ui2State.detailItem = item;
  }

  function openFullDetails(item) {
    ui2State.detailItem = null;
    ui2State.fullDetailItem = item;
    ui2State.view = "detail";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const Ui2Card = {
    name: "Ui2Card",
    props: {
      item: { type: Object, required: true },
      variant: { type: String, default: "poster" }, // poster | landscape | continue
      badge: { type: String, default: "" },
      badgeTone: { type: String, default: "" },
    },
    emits: ["open", "play", "remove"],
    template: `
      <div
        class="ui2-card"
        :class="variant === 'poster' ? 'poster' : 'landscape'"
        @click="$emit('open', item)"
        tabindex="0"
        @keydown.enter="$emit('open', item)"
      >
        <div class="ui2-card-media">
          <img class="ui2-card-img" :src="imageSrc" :alt="item.title" loading="lazy" />
          <div class="ui2-card-scrim"></div>

          <span v-if="badge" class="ui2-card-badge" :class="badgeTone">{{ badge }}</span>
          <span v-else-if="variant === 'continue' && (item.season || item.episode)" class="ui2-card-badge">
            S{{ item.season || 1 }} · E{{ item.episode || 1 }}
          </span>

          <img
            v-if="variant === 'landscape' && item.logo_path"
            class="ui2-card-logo-overlay"
            :src="imgUrl(item.logo_path)"
            :alt="item.title"
            loading="lazy"
          />

          <template v-if="variant === 'continue'">
            <button class="ui2-cw-center-play" aria-label="Resume playback" @click.stop="$emit('play', item)">
              <i class="ph-fill ph-play"></i>
            </button>
            <div class="ui2-cw-top-right">
              <button class="ui2-mini-circle" aria-label="Details" @click.stop="$emit('open', item)">
                <i class="ph ph-info"></i>
              </button>
              <button class="ui2-mini-circle" aria-label="Remove from queue" @click.stop="$emit('remove', item)">
                <i class="ph ph-x"></i>
              </button>
            </div>
            <div class="ui2-cw-progress-track">
              <div class="ui2-cw-progress-fill" :style="{ width: pct + '%' }"></div>
            </div>
            <span class="ui2-cw-pct">{{ pct }}%</span>
          </template>

          <div v-else class="ui2-card-hover-actions">
            <button class="ui2-mini-circle" aria-label="Add to watchlist" @click.stop="toggleWatchlist(item)">
              <i :class="inWatchlist ? 'ph-bold ph-check' : 'ph-bold ph-plus'"></i>
            </button>
            <button class="ui2-mini-circle play" aria-label="Play" @click.stop="$emit('play', item)">
              <i class="ph-fill ph-play"></i>
            </button>
          </div>
        </div>

        <div class="ui2-card-caption">
          <div class="ui2-card-title">{{ item.title }}</div>
          <div class="ui2-card-meta">
            <template v-if="variant === 'continue'">
              {{ cwMeta }}
            </template>
            <template v-else>
              {{ formatMeta(item) }}
            </template>
          </div>
        </div>
      </div>
    `,
    setup(props) {
      const imgUrl = window.imgUrl || ((p) => p || "");
      const imageSrc = computed(() => {
        if (props.variant === "poster") {
          return imgUrl(props.item.poster_path || props.item.backdrop_path || "", "poster");
        }
        return imgUrl(props.item.backdrop_path || props.item.poster_path || "", "backdrop");
      });
      const pct = computed(() => progressPct(props.item));
      const inWatchlist = computed(() => ui2State.watchlistIds.has(props.item.id || props.item.tmdb_id));
      const cwMeta = computed(() => {
        const parts = [];
        parts.push(props.item.type === "movie" ? "Film" : props.item.type === "anime" ? "Anime" : "Series");
        if (props.item.year) parts.push(props.item.year);
        const left = timeLeftLabel(props.item);
        if (left) parts.push(left);
        return parts.join(" / ");
      });
      return { imgUrl, imageSrc, pct, inWatchlist, cwMeta, formatMeta, toggleWatchlist };
    },
  };

  const Ui2Row = {
    name: "Ui2Row",
    components: { Ui2Card },
    props: {
      eyebrow: { type: String, default: "NO. 01" },
      title: { type: String, required: true },
      subtitle: { type: String, default: "" },
      items: { type: Array, default: () => [] },
      variant: { type: String, default: "poster" }, // poster | landscape | continue | top10
      badge: { type: String, default: "" },
      badgeTone: { type: String, default: "" },
    },
    emits: ["open", "play", "remove"],
    template: `
      <section class="ui2-row">
        <div class="ui2-row-header">
          <div>
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>{{ eyebrow }}</div>
            <h2 class="ui2-row-title">{{ title }}</h2>
            <p v-if="subtitle" class="ui2-row-sub">{{ subtitle }}</p>
          </div>
          <div class="ui2-row-arrows">
            <button class="ui2-arrow-btn" aria-label="Scroll left" :disabled="atStart" @click="scroll(-560)">
              <i class="ph-bold ph-caret-left"></i>
            </button>
            <button class="ui2-arrow-btn" aria-label="Scroll right" :disabled="atEnd" @click="scroll(560)">
              <i class="ph-bold ph-caret-right"></i>
            </button>
          </div>
        </div>

        <slot name="header-extra"></slot>

        <div class="ui2-scroller" ref="scrollerRef" @scroll="updateBounds">
          <template v-if="variant === 'top10'">
            <div v-for="(item, idx) in items.slice(0, 10)" :key="item.id || idx" class="ui2-top10-card">
              <span class="ui2-top10-num">{{ idx + 1 }}</span>
              <ui2-card
                :item="item"
                variant="poster"
                @open="$emit('open', $event)"
                @play="$emit('play', $event)"
              />
            </div>
          </template>
          <template v-else>
            <ui2-card
              v-for="(item, idx) in items"
              :key="(item.id || item.tmdb_id || idx) + '-' + variant"
              :item="item"
              :variant="variant"
              :badge="badge"
              :badge-tone="badgeTone"
              @open="$emit('open', $event)"
              @play="$emit('play', $event)"
              @remove="$emit('remove', $event)"
            />
          </template>
        </div>
      </section>
    `,
    setup() {
      const scrollerRef = ref(null);
      const atStart = ref(true);
      const atEnd = ref(false);

      function updateBounds() {
        const el = scrollerRef.value;
        if (!el) return;
        atStart.value = el.scrollLeft <= 4;
        atEnd.value = el.scrollLeft + el.clientWidth >= el.scrollWidth - 8;
      }

      function scroll(delta) {
        const el = scrollerRef.value;
        if (!el) return;
        el.scrollBy({ left: delta, behavior: "smooth" });
        setTimeout(updateBounds, 280);
      }

      return { scrollerRef, atStart, atEnd, scroll, updateBounds };
    },
  };

  window.Ui2Shared = {
    ui2State,
    setAmbientForItem,
    formatMeta,
    timeLeftLabel,
    progressPct,
    toggleWatchlist,
    playItem,
    openDetailsModal,
    openFullDetails,
    Ui2Card,
    Ui2Row,
  };
})();
