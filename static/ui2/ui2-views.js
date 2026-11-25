/* CapsStream New UI 2.0 — Discover, Library, Search Overlay & Person/Studio Page */
(function () {
  const { ref, computed, onMounted } = Vue;

  const Ui2Discover = {
    name: "Ui2Discover",
    template: `
      <div class="ui2-page">
        <div class="ui2-row-header" style="margin-bottom:14px">
          <div>
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>FILTER BY GENRE</div>
            <h1 class="ui2-row-title" style="font-size:1.85rem">Discover</h1>
          </div>
          <div class="ui2-row-arrows">
            <button class="ui2-arrow-btn" aria-label="Scroll genres left" @click="scrollGenres(-320)"><i class="ph-bold ph-caret-left"></i></button>
            <button class="ui2-arrow-btn" aria-label="Scroll genres right" @click="scrollGenres(320)"><i class="ph-bold ph-caret-right"></i></button>
          </div>
        </div>

        <div class="ui2-chip-row" ref="genreRowRef" style="margin-bottom:26px">
          <button class="ui2-chip" :class="{ active: activeGenre === '' }" @click="activeGenre = ''">All Genres</button>
          <button v-for="g in genres" :key="g" class="ui2-chip" :class="{ active: activeGenre === g }" @click="activeGenre = g">{{ g }}</button>
        </div>

        <div v-if="loading" class="ui2-grid">
          <div v-for="n in 12" :key="n" class="ui2-shimmer" style="aspect-ratio:2/3"></div>
        </div>

        <div v-else class="ui2-grid">
          <ui2-card
            v-for="item in filteredItems"
            :key="item.id || item.tmdb_id"
            :item="item"
            variant="poster"
            @open="openDetailsModal"
            @play="playItem"
          />
        </div>
      </div>
    `,
    setup() {
      const { openDetailsModal, playItem } = window.Ui2Shared;
      const loading = ref(true);
      const items = ref([]);
      const genres = ref([]);
      const activeGenre = ref("");
      const genreRowRef = ref(null);

      const filteredItems = computed(() => {
        if (!activeGenre.value) return items.value;
        const g = activeGenre.value.toLowerCase();
        return items.value.filter((i) => String(i.genres || "").toLowerCase().includes(g));
      });

      function scrollGenres(delta) {
        genreRowRef.value?.scrollBy({ left: delta, behavior: "smooth" });
      }

      onMounted(async () => {
        try {
          const [lib, gList] = await Promise.all([
            window.API.get("/api/library"),
            window.API.get("/api/genres"),
          ]);
          items.value = Array.isArray(lib) ? lib : (lib?.items || []);
          genres.value = Array.isArray(gList) ? gList : [];
        } catch (e) {}
        finally { loading.value = false; }
      });

      return { loading, genres, activeGenre, filteredItems, genreRowRef, scrollGenres, openDetailsModal, playItem };
    },
  };

  const Ui2Library = {
    name: "Ui2Library",
    template: `
      <div class="ui2-page">
        <div class="ui2-lib-head">
          <div>
            <span class="ui2-green-pill"><i class="ph-bold ph-check-circle"></i> PERSONAL COLLECTION & TRACKERS</span>
            <h1 style="font-size:2.2rem;font-weight:800;letter-spacing:-0.03em;margin:0 0 6px">My Library</h1>
            <p style="color:var(--ui2-text-muted);margin:0">Track watched titles, watchlist, and local collections</p>
          </div>

          <div class="ui2-stat-tiles">
            <div class="ui2-stat-tile"><div class="ui2-stat-val">{{ watchedCount }}</div><div class="ui2-stat-lbl">Watched</div></div>
            <div class="ui2-stat-tile"><div class="ui2-stat-val">{{ watchlistItems.length }}</div><div class="ui2-stat-lbl">Watchlist</div></div>
            <div class="ui2-stat-tile"><div class="ui2-stat-val">{{ allItems.length }}</div><div class="ui2-stat-lbl">Collection</div></div>
            <div class="ui2-stat-tile"><div class="ui2-stat-val">{{ episodeCount }}</div><div class="ui2-stat-lbl">Episodes</div></div>
            <button class="ui2-btn-red-outline" @click="syncTrackers">
              <i class="ph-bold ph-arrows-clockwise"></i> Sync Trackers
            </button>
          </div>
        </div>

        <!-- Status Tabs & Filters -->
        <div class="ui2-lib-controls">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button v-for="st in statusTabs" :key="st.id" class="ui2-chip" :class="{ active: status === st.id }" @click="status = st.id">
              {{ st.label }} ({{ st.count }})
            </button>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button v-for="tp in typeTabs" :key="tp.id" class="ui2-chip" :class="{ active: mediaType === tp.id }" @click="mediaType = tp.id">
              {{ tp.label }}
            </button>
          </div>
        </div>

        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:26px">
          <input v-model="query" class="ui2-input" style="flex:1;min-width:220px" placeholder="Search titles in library…" />
          <select v-model="sourceFilter" class="ui2-input">
            <option value="all">Sources: All Collections</option>
          </select>
          <select v-model="sortBy" class="ui2-input">
            <option value="recent">Recently Added</option>
            <option value="title">Title A–Z</option>
            <option value="rating">Top Rated</option>
          </select>
        </div>

        <div v-if="!filtered.length" style="text-align:center;padding:72px 20px">
          <div style="width:64px;height:64px;border-radius:999px;background:rgba(34,197,94,0.14);color:#4ADE80;display:grid;place-items:center;font-size:1.8rem;margin:0 auto 14px">
            <i class="ph-bold ph-check"></i>
          </div>
          <h3 style="margin:0 0 6px;font-size:1.25rem">Your {{ statusLabel }} Library is Empty</h3>
          <p style="color:var(--ui2-text-muted);margin:0">Titles you mark as {{ status }} or add to your collection will appear here.</p>
        </div>

        <div v-else class="ui2-grid">
          <ui2-card
            v-for="item in filtered"
            :key="item.id || item.tmdb_id"
            :item="item"
            variant="poster"
            @open="openDetailsModal"
            @play="playItem"
          />
        </div>
      </div>
    `,
    setup() {
      const { openDetailsModal, playItem } = window.Ui2Shared;
      const allItems = ref([]);
      const watchlistItems = ref([]);
      const status = ref("all");
      const mediaType = ref("all");
      const query = ref("");
      const sourceFilter = ref("all");
      const sortBy = ref("recent");

      const watchedItems = computed(() => allItems.value.filter((i) => i.watched || (i.progress_percent || 0) >= 90));
      const watchedCount = computed(() => watchedItems.value.length);
      const episodeCount = computed(() => allItems.value.filter((i) => i.type === "series" || i.type === "anime").length);

      const statusTabs = computed(() => [
        { id: "all", label: "All Status", count: allItems.value.length },
        { id: "watched", label: "Watched", count: watchedCount.value },
        { id: "watchlist", label: "Watchlist", count: watchlistItems.value.length },
        { id: "collection", label: "Collection", count: allItems.value.length },
      ]);
      const typeTabs = [
        { id: "all", label: "All Types" },
        { id: "movie", label: "Movies" },
        { id: "series", label: "TV Shows" },
        { id: "anime", label: "Episodes" },
      ];
      const statusLabel = computed(() => statusTabs.value.find((s) => s.id === status.value)?.label || "Watched");

      const filtered = computed(() => {
        let list = status.value === "watched" ? watchedItems.value : status.value === "watchlist" ? watchlistItems.value : allItems.value;
        if (mediaType.value !== "all") list = list.filter((i) => i.type === mediaType.value);
        if (query.value.trim()) {
          const q = query.value.toLowerCase();
          list = list.filter((i) => String(i.title || "").toLowerCase().includes(q));
        }
        if (sortBy.value === "title") list = [...list].sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
        if (sortBy.value === "rating") list = [...list].sort((a, b) => (b.rating || 0) - (a.rating || 0));
        return list;
      });

      function syncTrackers() {
        window.addToast?.("Trackers synced with local library", "success");
      }

      onMounted(async () => {
        try {
          const [lib, favs] = await Promise.all([
            window.API.get("/api/library"),
            window.API.get("/api/favorites"),
          ]);
          allItems.value = Array.isArray(lib) ? lib : (lib?.items || []);
          watchlistItems.value = Array.isArray(favs) ? favs : [];
        } catch (e) {}
      });

      return {
        allItems, watchlistItems, watchedCount, episodeCount, statusTabs, typeTabs,
        status, statusLabel, mediaType, query, sourceFilter, sortBy, filtered,
        syncTrackers, openDetailsModal, playItem,
      };
    },
  };

  const Ui2Search = {
    name: "Ui2Search",
    template: `
      <div class="ui2-overlay-backdrop" v-if="ui2State.searchOpen" @click.self="ui2State.searchOpen = false">
        <div class="ui2-search-inner">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>SEARCH</div>
            <button class="ui2-icon-btn" aria-label="Close search" @click="ui2State.searchOpen = false">
              <i class="ph-bold ph-x"></i>
            </button>
          </div>

          <h2 class="ui2-search-heading">What are we watching <span class="muted">tonight?</span></h2>

          <div class="ui2-search-box">
            <i class="ph-bold ph-magnifying-glass" style="font-size:1.2rem;color:var(--ui2-text-muted)"></i>
            <input
              ref="inputRef"
              v-model="q"
              placeholder="Search anime, movies, TV shows, actors, studios…"
              @input="onSearch"
            />
            <span class="ui2-kbd">ESC</span>
          </div>

          <!-- Suggestion Chips -->
          <div class="ui2-chip-row" style="margin-bottom:28px">
            <button v-for="s in suggestions" :key="s" class="ui2-chip" @click="q = s; onSearch()">{{ s }}</button>
          </div>

          <!-- Live Search Results -->
          <div v-if="q.trim()" style="margin-bottom:32px">
            <div class="ui2-mono" style="font-size:0.72rem;color:var(--ui2-text-muted);margin-bottom:14px">RESULTS ({{ results.length }})</div>
            <div class="ui2-grid" style="grid-template-columns:repeat(auto-fill,minmax(145px,1fr))">
              <ui2-card
                v-for="item in results"
                :key="item.id || item.tmdb_id"
                :item="item"
                variant="poster"
                @open="openFromSearch"
                @play="playFromSearch"
              />
            </div>
          </div>

          <!-- Trending Stars & Directors -->
          <div>
            <div class="ui2-eyebrow"><span class="ui2-eyebrow-dash"></span>PEOPLE & CREATORS</div>
            <h3 style="margin:0 0 16px;font-size:1.15rem">Trending Stars & Directors</h3>
            <div class="ui2-scroller">
              <div
                v-for="p in stars"
                :key="p.name"
                style="flex:0 0 130px;text-align:center;cursor:pointer"
                @click="openPerson(p)"
              >
                <div style="width:96px;height:96px;border-radius:999px;overflow:hidden;margin:0 auto 10px;border:1px solid var(--ui2-border);background:var(--ui2-surface)">
                  <img v-if="p.profile" :src="'https://image.tmdb.org/t/p/w185' + p.profile" :alt="p.name" style="width:100%;height:100%;object-fit:cover" />
                </div>
                <div style="font-weight:600;font-size:0.84rem">{{ p.name }}</div>
                <div style="font-size:0.72rem;color:var(--ui2-text-muted)">{{ p.knownFor }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `,
    setup() {
      const { ui2State, openDetailsModal, playItem } = window.Ui2Shared;
      const q = ref("");
      const results = ref([]);
      const inputRef = ref(null);
      const suggestions = ["Sci-Fi", "Anime", "2024", "Action", "Thriller", "4K", "Comedy", "Drama"];
      const stars = [
        { name: "Denis Villeneuve", knownFor: "Director · Sci-Fi", kind: "DIRECTOR" },
        { name: "Christopher Nolan", knownFor: "Director · Thriller", kind: "DIRECTOR" },
        { name: "Makoto Shinkai", knownFor: "Director · Anime", kind: "DIRECTOR" },
        { name: "Hayao Miyazaki", knownFor: "Director · Animation", kind: "DIRECTOR" },
        { name: "A24", knownFor: "Studio · Independent", kind: "STUDIO" },
      ];

      let debounce = null;
      function onSearch() {
        clearTimeout(debounce);
        if (!q.value.trim()) { results.value = []; return; }
        debounce = setTimeout(async () => {
          try {
            const res = await window.API.get("/api/search?q=" + encodeURIComponent(q.value.trim()));
            results.value = Array.isArray(res) ? res : (res?.results || []);
          } catch (e) {}
        }, 180);
      }

      function openFromSearch(item) {
        ui2State.searchOpen = false;
        openDetailsModal(item);
      }
      function playFromSearch(item) {
        ui2State.searchOpen = false;
        playItem(item);
      }
      function openPerson(p) {
        ui2State.searchOpen = false;
        ui2State.personTarget = p;
        ui2State.view = "person";
      }

      return { ui2State, q, results, inputRef, suggestions, stars, onSearch, openFromSearch, playFromSearch, openPerson };
    },
  };

  const Ui2PersonPage = {
    name: "Ui2PersonPage",
    template: `
      <div class="ui2-page" v-if="person">
        <button class="ui2-btn-glass" style="margin-bottom:24px" @click="ui2State.view = 'home'">
          <i class="ph-bold ph-arrow-left"></i> Back
        </button>

        <div style="display:flex;align-items:center;gap:22px;flex-wrap:wrap;margin-bottom:32px">
          <div style="width:92px;height:92px;border-radius:18px;background:var(--ui2-surface);border:1px solid var(--ui2-border);display:grid;place-items:center;font-size:2rem;overflow:hidden">
            <img v-if="person.profile" :src="'https://image.tmdb.org/t/p/w185' + person.profile" :alt="person.name" width="92" height="92" style="width:100%;height:100%;object-fit:cover" />
            <i v-else class="ph-bold ph-television"></i>
          </div>
          <div>
            <span class="ui2-card-badge red" style="position:static;display:inline-block;margin-bottom:8px">{{ person.kind || 'TELEVISION NETWORK' }}</span>
            <h1 style="margin:0 0 6px;font-size:2rem;font-weight:800">{{ person.name }}</h1>
            <div style="display:flex;gap:14px;align-items:center;color:var(--ui2-text-muted);font-size:0.85rem">
              <span>{{ items.length }} titles in library</span>
              <a href="https://www.themoviedb.org" target="_blank" rel="noopener" style="color:#fff;text-decoration:none">Official Website ↗</a>
            </div>
          </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:20px">
          <h2 class="ui2-row-title">Catalogue & Releases</h2>
          <div style="display:flex;gap:10px;align-items:center">
            <button class="ui2-chip" :class="{ active: filter === 'all' }" @click="filter = 'all'">All</button>
            <button class="ui2-chip" :class="{ active: filter === 'series' }" @click="filter = 'series'">TV Shows</button>
            <select v-model="sort" class="ui2-input">
              <option value="rating">Top Rated</option>
              <option value="year">Newest</option>
            </select>
          </div>
        </div>

        <div class="ui2-grid">
          <ui2-card
            v-for="item in displayed"
            :key="item.id || item.tmdb_id"
            :item="item"
            variant="poster"
            @open="openDetailsModal"
            @play="playItem"
          />
        </div>
      </div>
    `,
    setup() {
      const { ui2State, openDetailsModal, playItem } = window.Ui2Shared;
      const person = computed(() => ui2State.personTarget);
      const items = ref([]);
      const filter = ref("all");
      const sort = ref("rating");

      const displayed = computed(() => {
        let list = items.value;
        if (filter.value === "series") list = list.filter((i) => i.type === "series" || i.type === "anime");
        if (sort.value === "year") return [...list].sort((a, b) => (b.year || 0) - (a.year || 0));
        return [...list].sort((a, b) => (b.rating || 0) - (a.rating || 0));
      });

      onMounted(async () => {
        if (!person.value?.name) return;
        try {
          const res = await window.API.get("/api/search?q=" + encodeURIComponent(person.value.name));
          items.value = Array.isArray(res) ? res : (res?.results || []);
        } catch (e) {}
      });

      return { ui2State, person, items, filter, sort, displayed, openDetailsModal, playItem };
    },
  };

  window.Ui2Discover = Ui2Discover;
  window.Ui2Library = Ui2Library;
  window.Ui2Search = Ui2Search;
  window.Ui2PersonPage = Ui2PersonPage;
})();
