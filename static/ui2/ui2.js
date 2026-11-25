/* CapsStream New UI 2.0 — Loader & Root Shell */
(function () {
  const SUB_MODULES = [
    "/static/ui2/ui2-shared.js",
    "/static/ui2/ui2-home.js",
    "/static/ui2/ui2-details.js",
    "/static/ui2/ui2-views.js",
    "/static/ui2/ui2-settings.js",
  ];

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      const v = window.__CAPS_VER__ || "";
      s.src = v ? `${src}?v=${encodeURIComponent(v)}` : src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function registerUi2Shell() {
    const app = window.__capsApp;
    if (!app) return;
    const { computed, onMounted, onUnmounted } = Vue;
    const { ui2State, Ui2Card, Ui2Row } = window.Ui2Shared;

    app.component("ui2-card", Ui2Card);
    app.component("ui2-row", Ui2Row);

    const Ui2Shell = {
      name: "Ui2Shell",
      components: {
        Ui2Home: window.Ui2Home,
        Ui2Discover: window.Ui2Discover,
        Ui2Library: window.Ui2Library,
        Ui2Search: window.Ui2Search,
        Ui2PersonPage: window.Ui2PersonPage,
        Ui2DetailsModal: window.Ui2DetailsModal,
        Ui2DetailsPage: window.Ui2DetailsPage,
        Ui2SettingsModal: window.Ui2SettingsModal,
      },
      template: `
        <div class="ui2-shell">
          <!-- Ambient Background Glow -->
          <div class="ui2-ambient" v-if="ui2State.ambientEnabled && !isPlayerRoute" :style="{ opacity: ui2State.ambientIntensity / 100 }">
            <div class="ui2-ambient-orb orb-a" :style="{ background: ui2State.ambientColors[0] }"></div>
            <div class="ui2-ambient-orb orb-b" :style="{ background: ui2State.ambientColors[1] }"></div>
          </div>

          <!-- Floating Pill Nav -->
          <header class="ui2-nav-wrap" v-if="!isSystemRoute">
            <a class="ui2-brand" href="#/" @click.prevent="navigate('home')">
              <img src="/static/img/new-logo.png" alt="" width="24" height="24" style="width:24px;height:24px;border-radius:7px;object-fit:cover" />
              <span class="ui2-brand-word">CapsStream</span>
            </a>

            <nav class="ui2-nav-pills" aria-label="Primary navigation">
              <button
                v-for="tab in navTabs"
                :key="tab.id"
                class="ui2-nav-pill"
                :class="{ active: ui2State.view === tab.id && !isPlayerRoute }"
                @click="navigate(tab.id)"
              >
                <i :class="tab.icon"></i>
                <span>{{ tab.label }}</span>
              </button>
            </nav>

            <div class="ui2-nav-right">
              <button class="ui2-search-trigger" aria-label="Open search" @click="ui2State.searchOpen = true">
                <i class="ph-bold ph-magnifying-glass"></i>
                <span>Search</span>
                <kbd class="ui2-kbd">Ctrl K</kbd>
              </button>
              <button class="ui2-icon-btn" aria-label="Settings" title="Settings" @click="ui2State.settingsOpen = true">
                <i class="ph-bold ph-sliders-horizontal"></i>
              </button>
            </div>
          </header>

          <!-- Main Content -->
          <main class="ui2-main">
            <router-view v-if="isSystemRoute" />
            <ui2-home v-else-if="ui2State.view === 'home'" mode="home" />
            <ui2-home v-else-if="ui2State.view === 'anime'" mode="anime" />
            <ui2-discover v-else-if="ui2State.view === 'discover'" />
            <ui2-library v-else-if="ui2State.view === 'library'" />
            <ui2-details-page v-else-if="ui2State.view === 'detail'" />
            <ui2-person-page v-else-if="ui2State.view === 'person'" />
          </main>

          <!-- Modals & Overlays -->
          <ui2-details-modal />
          <ui2-search />
          <ui2-settings-modal />

          <!-- Toast Container -->
          <div class="toast-container" id="toast-container">
            <div v-for="toast in store.toasts" :key="toast.id" class="toast-card" :class="toast.type || 'info'">
              <div class="toast-card-body">{{ toast.message }}</div>
            </div>
          </div>
        </div>
      `,
      setup() {
        const store = window.store;
        const route = VueRouter.useRoute();
        const router = VueRouter.useRouter();

        const isPlayerRoute = computed(() => route.path.startsWith("/watch"));
        const isSystemRoute = computed(() =>
          route.path.startsWith("/watch") || route.path.startsWith("/profiles") || route.path.startsWith("/setup")
        );

        const navTabs = [
          { id: "home", label: "Home", icon: "ph-bold ph-house" },
          { id: "anime", label: "Anime", icon: "ph-bold ph-sparkle" },
          { id: "discover", label: "Discover", icon: "ph-bold ph-compass" },
          { id: "library", label: "Library", icon: "ph-bold ph-books" },
        ];

        function navigate(id) {
          ui2State.view = id;
          if (route.path !== "/") router.push("/");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }

        function onKeyDown(e) {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            ui2State.searchOpen = !ui2State.searchOpen;
          } else if (e.key === "Escape") {
            if (ui2State.searchOpen) ui2State.searchOpen = false;
            else if (ui2State.detailItem) ui2State.detailItem = null;
            else if (ui2State.settingsOpen) ui2State.settingsOpen = false;
          }
        }

        onMounted(() => window.addEventListener("keydown", onKeyDown));
        onUnmounted(() => window.removeEventListener("keydown", onKeyDown));

        return { store, ui2State, isPlayerRoute, isSystemRoute, navTabs, navigate };
      },
    };

    app.component("ui2-shell", Ui2Shell);
    if (window.store) {
      window.store.ui2Loaded = true;
    }
  }

  Promise.all(SUB_MODULES.map(loadScript))
    .then(registerUi2Shell)
    .catch((err) => console.error("[UI2] Failed to load modules:", err));
})();
