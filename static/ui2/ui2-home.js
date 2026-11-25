/* CapsStream New UI 2.0 — Home & Anime Pages (Zero Trailers) */
(function () {
  const { ref, computed, onMounted, onUnmounted } = Vue;

  const Ui2Home = {
    name: "Ui2Home",
    props: {
      mode: { type: String, default: "home" }, // home | anime
    },
    template: `
      <div>
        <!-- Loading Skeleton -->
        <div v-if="loading" style="padding:110px 48px 40px">
          <div class="ui2-shimmer" style="height:420px;margin-bottom:36px"></div>
          <div style="display:flex;gap:16px;overflow:hidden">
            <div v-for="n in 6" :key="n" class="ui2-shimmer" style="width:176px;height:264px;flex:0 0 auto"></div>
          </div>
        </div>

        <template v-else>
          <!-- HERO (Static backdrop only — ZERO trailers) -->
          <section class="ui2-hero" v-if="currentHero">
            <img
              v-if="currentHero.backdrop_path || currentHero.poster_path"
              class="ui2-hero-bg"
              :src="imgUrl(currentHero.backdrop_path || currentHero.poster_path, 'original')"
              :alt="currentHero.title"
            />
            <div class="ui2-hero-scrim"></div>

            <!-- Top-left segmented progress bar -->
            <div class="ui2-hero-segments" v-if="heroItems.length > 1">
              <button
                v-for="(h, idx) in heroItems.slice(0, 6)"
                :key="h.id || idx"
                class="ui2-hero-seg"
                :class="{ active: idx === heroIndex, done: idx < heroIndex }"
                :aria-label="'Featured ' + (idx + 1)"
                @click="jumpHero(idx)"
              >
                <span class="ui2-hero-seg-fill"></span>
              </button>
            </div>

            <div class="ui2-hero-grid">
              <div>
                <div class="ui2-eyebrow">
                  <span class="ui2-eyebrow-dash"></span>
                  {{ mode === 'anime' ? 'TRENDING ANIME' : 'TRENDING TODAY' }} / NO. {{ String(heroIndex + 1).padStart(2, '0') }}
                </div>

                <img
                  v-if="mode !== 'anime' && currentHero.logo_path"
                  class="ui2-hero-logo"
                  :src="imgUrl(currentHero.logo_path)"
                  :alt="currentHero.title"
                />
                <h1 v-else class="ui2-hero-title">{{ currentHero.title }}</h1>

                <div class="ui2-hero-meta">
                  <span v-if="currentHero.rating"><span class="star">★</span> {{ Number(currentHero.rating).toFixed(1) }}</span>
                  <span v-if="currentHero.year">· {{ currentHero.year }}</span>
                  <span v-if="currentHero.type">· {{ currentHero.type === 'movie' ? 'Film' : currentHero.type === 'anime' ? 'Anime' : 'Series' }}</span>
                </div>

                <p class="ui2-hero-overview" v-if="currentHero.overview">{{ currentHero.overview }}</p>

                <div class="ui2-hero-actions">
                  <button class="ui2-btn-primary" @click="playItem(currentHero)">
                    <i class="ph-fill ph-play"></i> Play
                  </button>
                  <button class="ui2-btn-glass" @click="openDetailsModal(currentHero)">
                    Details <i class="ph-bold ph-arrow-up-right"></i>
                  </button>
                  <button class="ui2-btn-circle" aria-label="Add to watchlist" @click="toggleWatchlist(currentHero)">
                    <i :class="inWatchlist ? 'ph-bold ph-check' : 'ph-bold ph-plus'"></i>
                  </button>
                </div>
              </div>

              <!-- UP NEXT 3 stacked glass cards -->
              <div class="ui2-upnext" v-if="upNextItems.length">
                <div class="ui2-upnext-label">UP NEXT</div>
                <button
                  v-for="u in upNextItems"
                  :key="u.item.id || u.idx"
                  class="ui2-upnext-card"
                  @click="jumpHero(u.idx)"
                >
                  <img
                    class="ui2-upnext-thumb"
                    :src="imgUrl(u.item.backdrop_path || u.item.poster_path, 'backdrop')"
                    :alt="u.item.title"
                  />
                  <div>
                    <div class="ui2-upnext-no">No. {{ String(u.idx + 1).padStart(2, '0') }}</div>
                    <div class="ui2-upnext-title">{{ u.item.title }}</div>
                  </div>
                </button>
              </div>
            </div>
          </section>

          <!-- SECTIONS -->
          <div class="ui2-sections">
            <template v-if="mode === 'anime'">
              <ui2-row
                v-if="animeTrending.length"
                eyebrow="NO. 01"
                title="Trending anime"
                subtitle="Most watched anime right now"
                :items="animeTrending"
                variant="landscape"
                badge="New release"
                badge-tone="red"
                @open="openDetailsModal"
                @play="playItem"
              />
              <ui2-row
                v-if="animeSeason.length"
                eyebrow="NO. 02"
                title="Popular This Season"
                subtitle="Top rated series and films"
                :items="animeSeason"
                variant="poster"
                @open="openDetailsModal"
                @play="playItem"
              />
            </template>

            <template v-else>
              <!-- 2. CONTINUE WATCHING -->
              <ui2-row
                v-if="continueItems.length"
                eyebrow="YOUR QUEUE"
                title="Continue Watching"
                subtitle="Pick up right where you left off"
                :items="continueItems"
                variant="continue"
                @open="openDetailsModal"
                @play="playItem"
                @remove="removeContinue"
              />

              <!-- 3. FOR YOU -->
              <ui2-row
                v-if="forYouItems.length"
                eyebrow="FOR YOU · BECAUSE YOU WATCHED"
                :title="forYouSource?.title || 'Recommended For You'"
                subtitle="Titles with a similar mood, story and pace"
                :items="forYouItems"
                variant="poster"
                badge="100% Match"
                badge-tone="match"
                @open="openDetailsModal"
                @play="playItem"
              >
                <template #header-extra v-if="forYouChips.length">
                  <div class="ui2-chip-row">
                    <button
                      v-for="src in forYouChips"
                      :key="src.id || src.title"
                      class="ui2-chip"
                      :class="{ active: (forYouSource?.id || forYouSource?.title) === (src.id || src.title) }"
                      @click="forYouSource = src"
                    >
                      <img v-if="src.poster_path" class="ui2-chip-avatar" :src="imgUrl(src.poster_path, 'poster')" :alt="src.title" />
                      <span>{{ src.title }}</span>
                    </button>
                  </div>
                </template>
              </ui2-row>

              <!-- 4. TOP 10 -->
              <ui2-row
                v-if="top10Items.length"
                eyebrow="NO. 01"
                title="Top 10 on CapsStream"
                subtitle="The most watched titles right now"
                :items="top10Items"
                variant="top10"
                @open="openDetailsModal"
                @play="playItem"
              />

              <!-- 5. REPEATING ROWS -->
              <ui2-row
                v-for="(row, rIdx) in catalogRows"
                :key="row.title + '-' + rIdx"
                :eyebrow="'NO. ' + String(rIdx + 2).padStart(2, '0')"
                :title="row.displayTitle || row.title"
                :subtitle="row.subtitle || ''"
                :items="row.items"
                :variant="row.landscape ? 'landscape' : 'poster'"
                :badge="row.landscape ? 'New release' : ''"
                :badge-tone="row.landscape ? 'red' : ''"
                @open="openDetailsModal"
                @play="playItem"
              />
            </template>
          </div>
        </template>
      </div>
    `,
    setup(props) {
      const { ui2State, setAmbientForItem, toggleWatchlist, playItem, openDetailsModal } = window.Ui2Shared;
      const imgUrl = window.imgUrl || ((p) => p || "");
      const loading = ref(true);
      const rawRows = ref([]);
      const heroIndex = ref(0);
      const forYouSource = ref(null);
      let heroTimer = null;

      const heroItems = computed(() => {
        if (props.mode === "anime") {
          const all = [];
          rawRows.value.forEach((r) => (r.items || []).forEach((i) => {
            if (i.type === "anime" || (i.genres || "").toLowerCase().includes("animation")) all.push(i);
          }));
          return all.slice(0, 6);
        }
        const heroRow = rawRows.value.find((r) => r.type === "hero");
        if (heroRow?.items?.length) return heroRow.items.slice(0, 6);
        const fallback = [];
        rawRows.value.forEach((r) => (r.items || []).forEach((i) => {
          if (i.backdrop_path && fallback.length < 6) fallback.push(i);
        }));
        return fallback;
      });

      const currentHero = computed(() => {
        const list = heroItems.value;
        const item = list[heroIndex.value] || list[0] || null;
        if (item) setAmbientForItem(item);
        return item;
      });

      const upNextItems = computed(() => {
        const list = heroItems.value;
        if (list.length <= 1) return [];
        const out = [];
        for (let offset = 1; offset <= Math.min(3, list.length - 1); offset++) {
          const idx = (heroIndex.value + offset) % list.length;
          out.push({ idx, item: list[idx] });
        }
        return out;
      });

      const inWatchlist = computed(() => {
        const h = currentHero.value;
        return h ? ui2State.watchlistIds.has(h.id || h.tmdb_id) : false;
      });

      const continueItems = computed(() => {
        const r = rawRows.value.find((x) => x.type === "continue");
        return r?.items || [];
      });

      const forYouChips = computed(() => {
        if (continueItems.value.length) return continueItems.value.slice(0, 6);
        const recRow = rawRows.value.find((x) => (x.title || "").toLowerCase().includes("because") || (x.title || "").toLowerCase().includes("discover"));
        return (recRow?.items || []).slice(0, 5);
      });

      const forYouItems = computed(() => {
        const recRow = rawRows.value.find((x) => (x.title || "").toLowerCase().includes("because") || (x.title || "").toLowerCase().includes("recommended"));
        if (recRow?.items?.length) return recRow.items;
        const top = rawRows.value.find((x) => (x.title || "").toLowerCase().includes("top rated"));
        return top?.items || [];
      });

      const top10Items = computed(() => {
        const t10 = rawRows.value.find((x) => x.type === "top10");
        if (t10?.items?.length) return t10.items.slice(0, 10);
        const top = rawRows.value.find((x) => (x.title || "").toLowerCase().includes("top rated"));
        return (top?.items || []).slice(0, 10);
      });

      const catalogRows = computed(() => {
        const mapped = [];
        const candidates = rawRows.value.filter((r) => r.type !== "hero" && r.type !== "continue" && r.type !== "top10");
        candidates.forEach((r, idx) => {
          const t = (r.title || "").toLowerCase();
          let displayTitle = r.title;
          let subtitle = "Curated from your library";
          let landscape = idx % 2 === 0;
          if (t === "series") {
            displayTitle = "Current & upcoming TV shows";
            subtitle = "Episodes & ongoing series";
            landscape = true;
          } else if (t === "recently added") {
            displayTitle = "Trending This Week";
            subtitle = "Fresh additions to your server";
            landscape = true;
          } else if (t === "top rated") {
            displayTitle = "Top Rated Masterpieces";
            subtitle = "Highest rated films & series";
            landscape = false;
          } else if (t.includes("sci-fi") || t.includes("science")) {
            displayTitle = "Sci-Fi Universes";
            subtitle = "Futures, galaxies & timelines";
            landscape = true;
          } else if (t.includes("action")) {
            displayTitle = "High-Octane Action";
            subtitle = "Adrenaline & spectacle";
            landscape = true;
          } else if (t.includes("animation") || t === "anime") {
            displayTitle = "Animated Worlds";
            subtitle = "Stylized stories & anime";
            landscape = false;
          }
          mapped.push({ ...r, displayTitle, subtitle, landscape });
        });
        return mapped;
      });

      const animeTrending = computed(() => heroItems.value);
      const animeSeason = computed(() => {
        const all = [];
        rawRows.value.forEach((r) => (r.items || []).forEach((i) => {
          if (i.type === "anime" || (i.genres || "").toLowerCase().includes("animation")) all.push(i);
        }));
        return all;
      });

      function jumpHero(idx) {
        heroIndex.value = idx;
        startHeroRotation();
      }

      function startHeroRotation() {
        if (heroTimer) clearInterval(heroTimer);
        const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduced) return;
        heroTimer = setInterval(() => {
          if (heroItems.value.length > 1) {
            heroIndex.value = (heroIndex.value + 1) % heroItems.value.length;
          }
        }, 8000);
      }

      async function removeContinue(item) {
        if (!item?.id) return;
        try {
          await window.API.del("/api/progress/" + item.id);
          rawRows.value = rawRows.value.map((r) =>
            r.type === "continue" ? { ...r, items: (r.items || []).filter((i) => i.id !== item.id) } : r
          );
        } catch (e) {}
      }

      onMounted(async () => {
        try {
          const data = await window.API.get("/api/home");
          rawRows.value = Array.isArray(data) ? data : [];
          if (forYouChips.value.length && !forYouSource.value) {
            forYouSource.value = forYouChips.value[0];
          }
          startHeroRotation();
        } catch (e) {
          window.addToast?.("Failed to load home feed", "error");
        } finally {
          loading.value = false;
        }
      });

      onUnmounted(() => {
        if (heroTimer) clearInterval(heroTimer);
      });

      return {
        loading, heroItems, currentHero, heroIndex, upNextItems, inWatchlist,
        continueItems, forYouChips, forYouSource, forYouItems, top10Items, catalogRows,
        animeTrending, animeSeason, jumpHero, removeContinue,
        imgUrl, playItem, openDetailsModal, toggleWatchlist,
      };
    },
  };

  window.Ui2Home = Ui2Home;
})();
