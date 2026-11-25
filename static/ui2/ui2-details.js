/* CapsStream New UI 2.0 — Details Modal & Full Details Page (Zero Trailers) */
(function () {
  const { ref, computed, watch, onMounted, onUnmounted } = Vue;

  const Ui2DetailsModal = {
    name: "Ui2DetailsModal",
    template: `
      <div class="ui2-modal-backdrop" v-if="ui2State.detailItem" @click.self="close">
        <div class="ui2-modal" role="dialog" aria-modal="true" :aria-label="detail.title">
          <button class="ui2-modal-close" aria-label="Close modal" @click="close">
            <i class="ph-bold ph-x"></i>
          </button>

          <!-- Static Backdrop Header Art (No Trailers) -->
          <div class="ui2-modal-hero">
            <img
              v-if="detail.backdrop_path || detail.poster_path"
              class="ui2-modal-hero-img"
              :src="imgUrl(detail.backdrop_path || detail.poster_path, 'original')"
              :alt="detail.title"
            />
            <div class="ui2-modal-hero-scrim"></div>
            <div style="position:relative;z-index:2;width:100%">
              <div class="ui2-eyebrow">
                <span class="ui2-eyebrow-dash"></span>
                {{ eyebrowText }}
              </div>
              <img
                v-if="detail.logo_path"
                class="ui2-hero-logo"
                style="max-height:84px"
                :src="imgUrl(detail.logo_path)"
                :alt="detail.title"
              />
              <h2 v-else style="font-size:2rem;font-weight:800;margin:0 0 10px">{{ detail.title }}</h2>
            </div>
          </div>

          <div class="ui2-modal-body">
            <!-- Score Ring + Genre Chips -->
            <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:18px">
              <div class="ui2-score-ring" :style="{ '--pct': scorePct }">
                <span>{{ scorePct }}</span>
              </div>
              <span class="ui2-mono" style="font-size:0.72rem;color:var(--ui2-text-muted)">TMDB score</span>
              <span v-for="g in genres" :key="g" class="ui2-chip" style="padding:4px 11px;font-size:0.74rem">{{ g }}</span>
            </div>

            <!-- Action Buttons (No Trailer) -->
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:18px">
              <button class="ui2-btn-primary" @click="playPrimary">
                <i class="ph-fill ph-play"></i>
                {{ resumeLabel }}
              </button>
              <button class="ui2-btn-glass" @click="toggleWatchlist(detail)">
                <i :class="inWatchlist ? 'ph-bold ph-check' : 'ph-bold ph-bookmark-simple'"></i>
                Watchlist
              </button>
              <button class="ui2-btn-glass" @click="markWatched">
                <i class="ph-bold ph-check-circle"></i> Mark watched
              </button>
              <button class="ui2-btn-circle" aria-label="Download" @click="downloadMedia">
                <i class="ph-bold ph-download-simple"></i>
              </button>
              <button class="ui2-btn-circle" aria-label="Share" @click="shareMedia">
                <i class="ph-bold ph-share-network"></i>
              </button>
              <button class="ui2-btn-glass" @click="openFullDetails(detail)">
                <i class="ph-bold ph-arrows-out"></i> Expand
              </button>
            </div>

            <p v-if="detail.overview" style="color:rgba(255,255,255,0.78);line-height:1.6;margin:0">{{ detail.overview }}</p>

            <!-- Tabs (Episodes, About, Cast, More like this — NO Videos) -->
            <div class="ui2-tabs">
              <button v-for="t in tabs" :key="t.id" class="ui2-tab" :class="{ active: tab === t.id }" @click="tab = t.id">
                {{ t.label }}
              </button>
            </div>

            <!-- Episodes Tab -->
            <div v-if="tab === 'episodes'">
              <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px">
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <button
                    v-for="s in seasons"
                    :key="s"
                    class="ui2-chip"
                    :class="{ active: activeSeason === s }"
                    @click="activeSeason = s"
                  >
                    Season {{ s }}
                  </button>
                </div>
                <div style="display:flex;align-items:center;gap:12px">
                  <span class="ui2-mono" style="font-size:0.72rem;color:var(--ui2-text-muted)">
                    {{ detail.year || '' }} · {{ seasonEpisodes.length }} episodes · {{ watchedCount }}/{{ seasonEpisodes.length }}
                  </span>
                  <button class="ui2-btn-glass" style="padding:6px 12px;font-size:0.78rem" @click="markSeasonWatched">
                    Mark season watched
                  </button>
                </div>
              </div>

              <div v-if="!seasonEpisodes.length" style="color:var(--ui2-text-muted);padding:16px 0">
                No episodes available for this title.
              </div>
              <div v-else style="display:flex;flex-direction:column;gap:10px">
                <div
                  v-for="ep in seasonEpisodes"
                  :key="ep.id"
                  style="display:grid;grid-template-columns:150px 1fr auto;gap:14px;align-items:center;padding:10px;border-radius:12px;background:var(--ui2-surface);border:1px solid var(--ui2-border);cursor:pointer"
                  @click="playItem(ep)"
                >
                  <div style="position:relative;aspect-ratio:16/9;border-radius:8px;overflow:hidden;background:#111">
                    <img
                      v-if="ep.still_path || detail.backdrop_path"
                      :src="imgUrl(ep.still_path || detail.backdrop_path, 'backdrop')"
                      :alt="ep.title"
                      style="width:100%;height:100%;object-fit:cover"
                    />
                    <span v-if="ep.duration" style="position:absolute;right:6px;bottom:6px;font-family:var(--ui2-font-mono);font-size:0.65rem;padding:2px 6px;border-radius:6px;background:rgba(0,0,0,0.8)">
                      {{ Math.round(ep.duration / 60) }}m
                    </span>
                  </div>
                  <div style="min-width:0">
                    <div class="ui2-mono" style="font-size:0.68rem;color:var(--ui2-text-muted)">
                      E{{ String(ep.episode || 1).padStart(2, '0') }} · {{ ep.air_date || detail.year || '' }} · ★ {{ Number(ep.rating || detail.rating || 0).toFixed(1) }}
                    </div>
                    <div style="font-weight:700;font-size:0.95rem;margin:2px 0 4px">{{ ep.ep_title || ep.title }}</div>
                    <div style="font-size:0.8rem;color:var(--ui2-text-muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
                      {{ ep.overview || 'Episode ready for playback.' }}
                    </div>
                  </div>
                  <div style="display:flex;gap:6px" @click.stop>
                    <button class="ui2-mini-circle" aria-label="Download episode" @click="downloadMedia(ep)">
                      <i class="ph ph-download-simple"></i>
                    </button>
                    <button class="ui2-mini-circle" aria-label="Mark episode watched" @click="markEpisodeWatched(ep)">
                      <i :class="ep.watched ? 'ph-fill ph-check-circle' : 'ph ph-check'"></i>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- About Tab -->
            <div v-if="tab === 'about'" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px">
              <div style="padding:14px;border-radius:14px;background:var(--ui2-surface);border:1px solid var(--ui2-border)">
                <div class="ui2-mono" style="font-size:0.68rem;color:var(--ui2-text-muted)">Origin</div>
                <div style="margin-top:6px;font-weight:600">{{ detail.origin_country || detail.language || 'International' }}</div>
              </div>
              <div style="padding:14px;border-radius:14px;background:var(--ui2-surface);border:1px solid var(--ui2-border)">
                <div class="ui2-mono" style="font-size:0.68rem;color:var(--ui2-text-muted)">Rated</div>
                <div style="margin-top:6px;font-weight:600">{{ detail.certification || detail.maturity_rating || 'TV-14' }}</div>
              </div>
              <div style="padding:14px;border-radius:14px;background:var(--ui2-surface);border:1px solid var(--ui2-border)">
                <div class="ui2-mono" style="font-size:0.68rem;color:var(--ui2-text-muted)">Networks & Studios</div>
                <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
                  <button
                    v-for="st in studios"
                    :key="st"
                    class="ui2-chip"
                    @click="openPerson({ name: st, kind: 'TELEVISION NETWORK' })"
                  >
                    {{ st }}
                  </button>
                </div>
              </div>
            </div>

            <!-- Cast Tab -->
            <div v-if="tab === 'cast'" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:14px">
              <div
                v-for="c in (detail.cast || []).slice(0, 18)"
                :key="c.name"
                style="background:var(--ui2-surface);border:1px solid var(--ui2-border);border-radius:13px;overflow:hidden;cursor:pointer"
                @click="openPerson({ name: c.name, profile: c.profile, kind: 'ACTOR / CREW' })"
              >
                <div style="aspect-ratio:2/3;background:#111">
                  <img
                    v-if="c.profile"
                    :src="'https://image.tmdb.org/t/p/w185' + c.profile"
                    :alt="c.name"
                    style="width:100%;height:100%;object-fit:cover"
                  />
                </div>
                <div style="padding:8px 10px">
                  <div style="font-weight:600;font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ c.name }}</div>
                  <div style="font-size:0.74rem;color:var(--ui2-text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ c.character || 'Cast' }}</div>
                </div>
              </div>
            </div>

            <!-- More like this Tab -->
            <div v-if="tab === 'similar'" class="ui2-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr))">
              <ui2-card
                v-for="s in similarItems"
                :key="s.id || s.tmdb_id"
                :item="s"
                variant="poster"
                @open="ui2State.detailItem = $event"
                @play="playItem"
              />
            </div>
          </div>
        </div>
      </div>
    `,
    setup() {
      const { ui2State, toggleWatchlist, playItem, openFullDetails } = window.Ui2Shared;
      const imgUrl = window.imgUrl || ((p) => p || "");
      const richDetail = ref(null);
      const episodes = ref([]);
      const similarItems = ref([]);
      const tab = ref("episodes");
      const activeSeason = ref(1);

      const detail = computed(() => richDetail.value || ui2State.detailItem || {});
      const scorePct = computed(() => Math.min(100, Math.round((Number(detail.value.rating || 7.2)) * 10)));
      const genres = computed(() => String(detail.value.genres || "").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 5));
      const studios = computed(() => {
        const raw = detail.value.networks || detail.value.studios || "CapsStream Library";
        return String(raw).split(",").map((s) => s.trim()).filter(Boolean);
      });
      const seasons = computed(() => {
        const set = new Set(episodes.value.map((e) => Number(e.season || 1)));
        return set.size ? Array.from(set).sort((a, b) => a - b) : [1];
      });
      const seasonEpisodes = computed(() => episodes.value.filter((e) => Number(e.season || 1) === activeSeason.value));
      const watchedCount = computed(() => seasonEpisodes.value.filter((e) => e.watched).length);
      const inWatchlist = computed(() => ui2State.watchlistIds.has(detail.value.id || detail.value.tmdb_id));
      const tabs = computed(() => {
        const list = [];
        if (detail.value.type !== "movie") list.push({ id: "episodes", label: "Episodes" });
        list.push({ id: "about", label: "About" }, { id: "cast", label: "Cast" }, { id: "similar", label: "More like this" });
        return list;
      });
      const eyebrowText = computed(() => {
        const t = (detail.value.type || "series").toUpperCase();
        const parts = [t];
        if (detail.value.year) parts.push(detail.value.year);
        if (detail.value.type !== "movie") parts.push(seasons.value.length + " SEASON" + (seasons.value.length > 1 ? "S" : ""));
        parts.push(detail.value.certification || "TV-14");
        return parts.join(" / ");
      });
      const resumeLabel = computed(() => {
        if (detail.value.type !== "movie" && seasonEpisodes.value.length) {
          const ep = seasonEpisodes.value.find((e) => !e.watched) || seasonEpisodes.value[0];
          return `Resume S${ep.season || 1} · E${ep.episode || 1}`;
        }
        return "Play";
      });

      watch(() => ui2State.detailItem, async (item) => {
        if (!item) return;
        richDetail.value = null;
        episodes.value = [];
        similarItems.value = [];
        tab.value = item.type === "movie" ? "about" : "episodes";
        try {
          if (item.id) {
            const full = await window.API.get("/api/media/" + item.id);
            if (full) richDetail.value = { ...item, ...full };
          }
          if (item.tmdb_id && item.type !== "movie") {
            const show = await window.API.get("/api/show/" + item.tmdb_id);
            if (show?.episodes) episodes.value = show.episodes;
          }
          if (item.id) {
            const sim = await window.API.get("/api/media/" + item.id + "/similar");
            similarItems.value = Array.isArray(sim) ? sim.slice(0, 12) : [];
          }
        } catch (e) {}
      }, { immediate: true });

      function close() { ui2State.detailItem = null; }
      function playPrimary() {
        const target = (detail.value.type !== "movie" && seasonEpisodes.value[0]) ? seasonEpisodes.value[0] : detail.value;
        close();
        playItem(target);
      }
      async function markWatched() {
        if (!detail.value.id) return;
        try {
          await window.API.post("/api/progress/mark-watched", { media_id: detail.value.id });
          window.addToast?.("Marked as watched", "success");
        } catch (e) {}
      }
      async function markEpisodeWatched(ep) {
        if (!ep?.id) return;
        try {
          await window.API.post("/api/progress/mark-watched", { media_id: ep.id });
          ep.watched = true;
        } catch (e) {}
      }
      async function markSeasonWatched() {
        for (const ep of seasonEpisodes.value) await markEpisodeWatched(ep);
        window.addToast?.("Season marked watched", "success");
      }
      function downloadMedia(target) {
        const id = target?.id || detail.value.id;
        if (id) window.open("/api/stream/" + id + "?download=1", "_blank");
      }
      function shareMedia() {
        navigator.clipboard?.writeText(window.location.href);
        window.addToast?.("Link copied", "info");
      }
      function openPerson(person) {
        ui2State.detailItem = null;
        ui2State.personTarget = person;
        ui2State.view = "person";
      }

      return {
        ui2State, detail, scorePct, genres, studios, seasons, seasonEpisodes, watchedCount,
        inWatchlist, tabs, tab, activeSeason, similarItems, eyebrowText, resumeLabel,
        imgUrl, close, playPrimary, playItem, toggleWatchlist, markWatched,
        markEpisodeWatched, markSeasonWatched, downloadMedia, shareMedia, openFullDetails, openPerson,
      };
    },
  };

  const Ui2DetailsPage = {
    name: "Ui2DetailsPage",
    template: `
      <div v-if="detail" style="padding-bottom:80px">
        <!-- Sticky Sub-header on scroll -->
        <div
          v-if="scrolled"
          style="position:fixed;top:74px;left:0;right:0;z-index:850;background:rgba(10,10,14,0.86);backdrop-filter:blur(20px);border-bottom:1px solid var(--ui2-border);padding:10px 48px;display:flex;align-items:center;justify-content:space-between;gap:16px"
        >
          <div style="display:flex;align-items:center;gap:12px">
            <button class="ui2-btn-glass" style="padding:6px 14px" @click="goBack">
              <i class="ph-bold ph-arrow-left"></i> Back
            </button>
            <img v-if="detail.poster_path" :src="imgUrl(detail.poster_path, 'poster')" :alt="detail.title" width="32" height="46" style="width:32px;height:46px;border-radius:6px;object-fit:cover" />
            <div>
              <div style="font-weight:700;font-size:0.95rem">{{ detail.title }}</div>
              <div class="ui2-mono" style="font-size:0.66rem;color:var(--ui2-text-muted)">{{ detail.year }} · {{ detail.type }}</div>
            </div>
          </div>
          <div style="display:flex;gap:18px">
            <a href="#ui2-story" class="ui2-tab active" style="text-decoration:none">Overview</a>
            <a href="#ui2-episodes" class="ui2-tab" style="text-decoration:none">Episodes</a>
            <a href="#ui2-cast" class="ui2-tab" style="text-decoration:none">Cast</a>
            <a href="#ui2-similar" class="ui2-tab" style="text-decoration:none">More like this</a>
          </div>
        </div>

        <!-- Hero -->
        <section class="ui2-hero" style="min-height:76vh;padding-top:110px">
          <img
            v-if="detail.backdrop_path || detail.poster_path"
            class="ui2-hero-bg"
            :src="imgUrl(detail.backdrop_path || detail.poster_path, 'original')"
            :alt="detail.title"
          />
          <div class="ui2-hero-scrim"></div>

          <div style="position:relative;z-index:2;width:100%">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:28px">
              <button class="ui2-btn-glass" @click="goBack"><i class="ph-bold ph-arrow-left"></i> Back</button>
              <img v-if="detail.logo_path" :src="imgUrl(detail.logo_path)" :alt="detail.title" style="max-height:42px;object-fit:contain" />
            </div>

            <div style="display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:40px;align-items:end">
              <div>
                <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>{{ detail.type }} / {{ detail.year }}</div>
                <img v-if="detail.logo_path" class="ui2-hero-logo" :src="imgUrl(detail.logo_path)" :alt="detail.title" />
                <h1 v-else class="ui2-hero-title">{{ detail.title }}</h1>
                <p v-if="detail.tagline" style="font-style:italic;color:var(--ui2-text-muted);margin:0 0 14px">"{{ detail.tagline }}"</p>

                <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:18px">
                  <div class="ui2-score-ring" :style="{ '--pct': Math.round((detail.rating || 7.5) * 10) }">
                    <span>{{ Math.round((detail.rating || 7.5) * 10) }}</span>
                  </div>
                  <span class="ui2-mono" style="font-size:0.74rem;color:var(--ui2-text-muted)">
                    {{ detail.duration ? Math.round(detail.duration / 60) + 'm' : 'HD' }} · {{ episodes.length || 1 }} Episodes
                  </span>
                </div>

                <div style="display:flex;gap:10px;flex-wrap:wrap">
                  <button class="ui2-btn-primary" @click="playItem(episodes[0] || detail)">
                    <i class="ph-fill ph-play"></i> Play
                  </button>
                  <button class="ui2-btn-glass" @click="toggleWatchlist(detail)">
                    <i class="ph-bold ph-bookmark-simple"></i> Watchlist
                  </button>
                </div>
              </div>

              <div v-if="detail.poster_path" style="border-radius:18px;overflow:hidden;border:1px solid rgba(255,255,255,0.22);box-shadow:0 0 42px rgba(229,9,20,0.22)">
                <img :src="imgUrl(detail.poster_path, 'poster')" :alt="detail.title" style="width:100%;display:block" />
              </div>
            </div>
          </div>
        </section>

        <!-- Sections -->
        <div class="ui2-sections" style="margin-top:32px">
          <section id="ui2-story">
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>01: THE STORY</div>
            <h2 class="ui2-row-title" style="margin-bottom:12px">Synopsis</h2>
            <p style="max-width:760px;color:rgba(255,255,255,0.8);line-height:1.7">{{ detail.overview || 'No overview available.' }}</p>
          </section>

          <section id="ui2-episodes" v-if="episodes.length">
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>02: EPISODES</div>
            <h2 class="ui2-row-title" style="margin-bottom:16px">Episode guide</h2>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px">
              <div
                v-for="ep in episodes"
                :key="ep.id"
                style="display:flex;gap:12px;padding:12px;border-radius:13px;background:var(--ui2-surface);border:1px solid var(--ui2-border);cursor:pointer"
                @click="playItem(ep)"
              >
                <img
                  :src="imgUrl(ep.still_path || detail.backdrop_path || detail.poster_path, 'backdrop')"
                  style="width:128px;height:72px;border-radius:8px;object-fit:cover;flex-shrink:0"
                />
                <div style="min-width:0">
                  <div class="ui2-mono" style="font-size:0.66rem;color:var(--ui2-text-muted)">S{{ ep.season || 1 }} · E{{ ep.episode || 1 }}</div>
                  <div style="font-weight:700;font-size:0.92rem;margin:2px 0">{{ ep.ep_title || ep.title }}</div>
                  <div style="font-size:0.78rem;color:var(--ui2-text-muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">
                    {{ ep.overview || '' }}
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    `,
    setup() {
      const { ui2State, toggleWatchlist, playItem } = window.Ui2Shared;
      const imgUrl = window.imgUrl || ((p) => p || "");
      const detail = computed(() => ui2State.fullDetailItem);
      const episodes = ref([]);
      const scrolled = ref(false);

      function onScroll() { scrolled.value = window.scrollY > 360; }
      function goBack() { ui2State.view = "home"; }

      onMounted(async () => {
        window.addEventListener("scroll", onScroll, { passive: true });
        if (detail.value?.tmdb_id && detail.value?.type !== "movie") {
          try {
            const show = await window.API.get("/api/show/" + detail.value.tmdb_id);
            episodes.value = show?.episodes || [];
          } catch (e) {}
        }
      });
      onUnmounted(() => window.removeEventListener("scroll", onScroll));

      return { detail, episodes, scrolled, imgUrl, goBack, playItem, toggleWatchlist };
    },
  };

  window.Ui2DetailsModal = Ui2DetailsModal;
  window.Ui2DetailsPage = Ui2DetailsPage;
})();
