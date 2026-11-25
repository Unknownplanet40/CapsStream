/* CapsStream New UI 2.0 — Settings Modal */
(function () {
  const { ref } = Vue;

  const Ui2SettingsModal = {
    name: "Ui2SettingsModal",
    template: `
      <div class="ui2-modal-backdrop" v-if="ui2State.settingsOpen" @click.self="ui2State.settingsOpen = false">
        <div class="ui2-modal" style="max-width:860px;overflow:hidden" role="dialog" aria-modal="true" aria-label="Settings">
          <button class="ui2-modal-close" aria-label="Close settings" @click="ui2State.settingsOpen = false">
            <i class="ph-bold ph-x"></i>
          </button>

          <div style="display:grid;grid-template-columns:220px 1fr;min-height:540px">
            <!-- Left Sidebar -->
            <aside style="background:rgba(255,255,255,0.02);border-right:1px solid var(--ui2-border);padding:24px 14px;display:flex;flex-direction:column;gap:6px">
              <div class="ui2-eyebrow" style="padding:0 10px 8px;margin:0"><span class="ui2-eyebrow-dash"></span>SETTINGS</div>
              <button
                v-for="sec in sections"
                :key="sec.id"
                class="ui2-nav-pill"
                style="width:100%;justify-content:flex-start"
                :class="{ active: activeSection === sec.id }"
                @click="activeSection = sec.id"
              >
                <i :class="sec.icon"></i>
                <span>{{ sec.label }}</span>
              </button>
            </aside>

            <!-- Right Panel -->
            <div style="padding:28px 30px;overflow-y:auto;max-height:85vh">
              <!-- Appearance Panel -->
              <div v-if="activeSection === 'appearance'">
                <h2 style="margin:0 0 18px;font-size:1.35rem">Appearance</h2>

                <!-- Enable New UI 2.0 Toggle -->
                <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-radius:14px;background:var(--ui2-surface);border:1px solid var(--ui2-border);margin-bottom:20px">
                  <div>
                    <div style="font-weight:700;display:flex;align-items:center;gap:8px">
                      <span>Enable New UI 2.0</span>
                      <span class="ui2-mono" style="font-size:0.65rem;padding:2px 8px;border-radius:999px;background:rgba(245,158,11,0.16);color:#fbbf24;border:1px solid rgba(245,158,11,0.35)">Experimental</span>
                    </div>
                    <div style="font-size:0.8rem;color:var(--ui2-text-muted)">Try the redesigned interface (Experimental: may be buggy or unstable)</div>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" :checked="store.ui2Enabled" @change="toggleUi2($event.target.checked)" />
                    <span class="toggle-slider"></span>
                  </label>
                </div>

                <!-- Theme Cards -->
                <div class="ui2-mono" style="font-size:0.7rem;color:var(--ui2-text-muted);margin-bottom:10px">THEME PRESETS</div>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:22px">
                  <button
                    v-for="t in themes"
                    :key="t.id"
                    @click="selectedTheme = t.id"
                    style="text-align:left;padding:10px;border-radius:12px;background:var(--ui2-surface);cursor:pointer;color:#fff;position:relative"
                    :style="{ border: selectedTheme === t.id ? '1.5px solid #fff' : '1px solid var(--ui2-border)' }"
                  >
                    <div style="height:36px;border-radius:8px;margin-bottom:8px" :style="{ background: t.preview }"></div>
                    <div style="font-size:0.82rem;font-weight:600">{{ t.name }}</div>
                    <i v-if="selectedTheme === t.id" class="ph-bold ph-check-circle" style="position:absolute;top:14px;right:14px;color:#fff"></i>
                  </button>
                </div>

                <!-- Background Grid -->
                <div class="ui2-mono" style="font-size:0.7rem;color:var(--ui2-text-muted);margin-bottom:10px">BACKGROUND</div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px">
                  <button
                    v-for="bg in backgrounds"
                    :key="bg"
                    class="ui2-chip"
                    :class="{ active: ui2State.bgPreset === bg }"
                    @click="setBgPreset(bg)"
                  >
                    {{ bg }}
                  </button>
                </div>

                <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <span>Show background</span>
                  <label class="toggle-switch">
                    <input type="checkbox" :checked="ui2State.ambientEnabled" @change="setShowBg($event.target.checked)" />
                    <span class="toggle-slider"></span>
                  </label>
                </div>

                <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <div>
                    <div>Low-Power Mode</div>
                    <div style="font-size:0.78rem;color:var(--ui2-text-muted)">Disables blur and ambient animations for low-end devices</div>
                  </div>
                  <label class="toggle-switch">
                    <input type="checkbox" :checked="ui2State.lowPower" @change="setLowPower($event.target.checked)" />
                    <span class="toggle-slider"></span>
                  </label>
                </div>

                <div v-if="store.profile" style="padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <div style="display:flex;align-items:center;justify-content:space-between">
                    <div>
                      <div>Content Warning Gate</div>
                      <div style="font-size:0.78rem;color:var(--ui2-text-muted)">Warn before viewing or playing flagged titles (per profile)</div>
                    </div>
                    <label class="toggle-switch">
                      <input type="checkbox" :checked="store.profile?.explicit_gate_enabled !== false" @change="setExplicitGate($event.target.checked)" />
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div v-if="store.profile?.explicit_gate_enabled !== false" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
                    <button
                      v-for="cat in warningCategories"
                      :key="cat.id"
                      class="ui2-chip"
                      :class="{ active: isWarningCatActive(cat.id) }"
                      @click="toggleWarningCat(cat.id)"
                    >
                      {{ cat.label }}
                    </button>
                  </div>
                </div>

                <div style="padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <div style="display:flex;justify-content:space-between;margin-bottom:8px">
                    <span>Background intensity</span>
                    <span class="ui2-mono" style="font-size:0.78rem">{{ ui2State.ambientIntensity }}%</span>
                  </div>
                  <input type="range" min="0" max="100" :value="ui2State.ambientIntensity" @input="setIntensity($event.target.value)" style="width:100%" />
                </div>
              </div>

              <!-- Playback Panel -->
              <div v-else-if="activeSection === 'playback'">
                <h2 style="margin:0 0 18px;font-size:1.35rem">Playback</h2>
                <div class="ui2-mono" style="font-size:0.7rem;color:var(--ui2-text-muted);margin-bottom:10px">DEFAULT QUALITY</div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">
                  <button v-for="q in ['4K','1080p','720p','480p','360p']" :key="q" class="ui2-chip" :class="{ active: quality === q }" @click="quality = q">
                    {{ q }}
                  </button>
                </div>

                <div class="ui2-mono" style="font-size:0.7rem;color:var(--ui2-text-muted);margin-bottom:10px">ACCENT COLOUR</div>
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px">
                  <button
                    v-for="c in ['#E50914','#38BDF8','#22C55E','#A855F7','#F59E0B']"
                    :key="c"
                    @click="accentColor = c"
                    style="width:28px;height:28px;border-radius:999px;cursor:pointer"
                    :style="{ background: c, border: accentColor === c ? '2px solid #fff' : '2px solid transparent' }"
                  ></button>
                  <input v-model="accentColor" class="ui2-input" style="width:110px;font-family:var(--ui2-font-mono)" />
                </div>

                <div style="display:flex;justify-content:space-between;padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <span>Autoplay next episode</span>
                  <label class="toggle-switch"><input type="checkbox" checked /><span class="toggle-slider"></span></label>
                </div>
                <div style="display:flex;justify-content:space-between;padding:12px 0;border-top:1px solid var(--ui2-border)">
                  <span>Skip intros & recaps</span>
                  <label class="toggle-switch"><input type="checkbox" checked /><span class="toggle-slider"></span></label>
                </div>
              </div>

              <!-- Other Sections (Library, Server, Security) -->
              <div v-else>
                <h2 style="margin:0 0 10px;font-size:1.35rem;text-transform:capitalize">{{ activeSection }}</h2>
                <p style="color:var(--ui2-text-muted);margin:0 0 18px">
                  Manage full {{ activeSection }} configuration in the classic settings view.
                </p>
                <button class="ui2-btn-primary" @click="openClassicSettings">
                  Open Full {{ activeSection }} Settings
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `,
    setup() {
      const { ui2State } = window.Ui2Shared;
      const store = window.store;
      const activeSection = ref("appearance");
      const selectedTheme = ref("crimson");
      const quality = ref("1080p");
      const accentColor = ref("#E50914");

      const sections = [
        { id: "appearance", label: "Appearance", icon: "ph ph-palette" },
        { id: "playback", label: "Playback", icon: "ph ph-play-circle" },
        { id: "library", label: "Library", icon: "ph ph-folder-open" },
        { id: "server", label: "Server", icon: "ph ph-hard-drives" },
        { id: "security", label: "Security", icon: "ph ph-shield-check" },
      ];
      const themes = [
        { id: "crimson", name: "Crimson Glass", preview: "linear-gradient(135deg,#18090c,#E50914)" },
        { id: "midnight", name: "Midnight Blue", preview: "linear-gradient(135deg,#09101d,#38BDF8)" },
        { id: "obsidian", name: "Obsidian Mono", preview: "linear-gradient(135deg,#0d0d10,#3f3f46)" },
      ];
      const backgrounds = ["Dark", "Onyx", "Ash", "Midnight", "Mood", "Galaxy", "Topography", "Snow", "Silk", "Light rays"];

      function toggleUi2(val) {
        store.ui2Enabled = !!val;
        try { localStorage.setItem("cs_ui2_enabled", val ? "true" : "false"); } catch (e) {}
        if (!val) ui2State.settingsOpen = false;
      }
      function setBgPreset(bg) {
        ui2State.bgPreset = bg;
        try { localStorage.setItem("cs_ui2_bg_preset", bg); } catch (e) {}
      }
      function setShowBg(val) {
        ui2State.ambientEnabled = !!val;
        try { localStorage.setItem("cs_ui2_bg_show", val ? "true" : "false"); } catch (e) {}
      }
      const warningCategories = [
        { id: "explicit", label: "Explicit / Sexual" },
        { id: "violence", label: "Violence & Gore" },
        { id: "flashing", label: "Flashing Lights" },
        { id: "self_harm", label: "Self-Harm" },
        { id: "substance", label: "Substance Abuse" },
        { id: "profanity", label: "Strong Language" },
      ];
      function isWarningCatActive(id) {
        const cats = store.profile?.content_warning_categories;
        return !Array.isArray(cats) || cats.includes(id);
      }
      async function toggleWarningCat(id) {
        if (!store.profile) return;
        const cur = Array.isArray(store.profile.content_warning_categories)
          ? [...store.profile.content_warning_categories]
          : warningCategories.map((c) => c.id);
        const idx = cur.indexOf(id);
        if (idx >= 0) cur.splice(idx, 1);
        else cur.push(id);
        try {
          const res = await fetch(`/api/profiles/${store.profile.id}/explicit-gate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ categories: cur }),
          }).then((r) => r.json());
          if (res && res.profile) store.profile = { ...store.profile, ...res.profile };
          else store.profile.content_warning_categories = cur;
        } catch (e) {}
      }

      function setLowPower(val) {
        ui2State.lowPower = !!val;
        document.documentElement.classList.toggle("cs-low-power", !!val);
        try { localStorage.setItem("cs_low_power", val ? "true" : "false"); } catch (e) {}
      }
      async function setExplicitGate(val) {
        if (!store.profile) return;
        try {
          const res = await fetch(`/api/profiles/${store.profile.id}/explicit-gate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: !!val }),
          }).then((r) => r.json());
          if (res && res.profile) store.profile = { ...store.profile, ...res.profile };
          else store.profile.explicit_gate_enabled = !!val;
        } catch (e) {}
      }
      function setIntensity(val) {
        ui2State.ambientIntensity = Number(val);
        try { localStorage.setItem("cs_ui2_bg_intensity", String(val)); } catch (e) {}
      }
      function openClassicSettings() {
        ui2State.settingsOpen = false;
        toggleUi2(false);
        window.__capsRouter?.push("/settings");
      }

      return {
        ui2State, store, activeSection, selectedTheme, quality, accentColor,
        sections, themes, backgrounds, warningCategories, isWarningCatActive, toggleWarningCat, toggleUi2, setBgPreset, setShowBg, setLowPower, setExplicitGate, setIntensity, openClassicSettings,
      };
    },
  };

  window.Ui2SettingsModal = Ui2SettingsModal;
})();
