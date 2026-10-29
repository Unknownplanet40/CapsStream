/**
 * Verification check for Seasonal Banner System:
 * 1. Extended seasons: Halloween, Christmas, New Year, Valentine's Day, Easter/Spring, Summer
 * 2. Strict genre matching & exclusion checks (e.g. no horror in Christmas, no family in Halloween)
 * 3. Vue template compilation checks
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const appJsPath = path.join(__dirname, '../../static/js/app.js');
const appJsContent = fs.readFileSync(appJsPath, 'utf8');

const configMatch = appJsContent.match(/const SEASONAL_CONFIGS = (\[[\s\S]*?\n\]);/);
assert(configMatch, "Could not find SEASONAL_CONFIGS in static/js/app.js");

const getActiveSeasonMatch = appJsContent.match(/function getActiveSeason\([\s\S]*?\n\}/);
assert(getActiveSeasonMatch, "Could not find getActiveSeason function in static/js/app.js");

const sandbox = {};
const fnCode = `
  ${configMatch[0]}
  ${getActiveSeasonMatch[0]}
  sandbox.SEASONAL_CONFIGS = SEASONAL_CONFIGS;
  sandbox.getActiveSeason = getActiveSeason;
`;
new Function('sandbox', fnCode)(sandbox);

const { getActiveSeason, SEASONAL_CONFIGS } = sandbox;

console.log("Running Extended Seasonal Banner Verification Checks...\n");

// Check 1: Seasonal Configs length
assert.strictEqual(SEASONAL_CONFIGS.length, 6, "Expected 6 seasonal configurations");
console.log("PASS: 6 seasonal configs configured (Halloween, Christmas, New Year, Valentine's Day, Easter, Summer).");

// Check 2: Date detection checks across all 6
assert.strictEqual(getActiveSeason("auto", new Date("2026-10-20")).id, "halloween");
assert.strictEqual(getActiveSeason("auto", new Date("2026-12-15")).id, "christmas");
assert.strictEqual(getActiveSeason("auto", new Date("2026-12-31")).id, "newyear");
assert.strictEqual(getActiveSeason("auto", new Date("2027-01-02")).id, "newyear"); // year wrap-around
assert.strictEqual(getActiveSeason("auto", new Date("2026-02-14")).id, "valentines");
assert.strictEqual(getActiveSeason("auto", new Date("2026-04-05")).id, "easter");
assert.strictEqual(getActiveSeason("auto", new Date("2026-07-20")).id, "summer");
console.log("PASS: Accurate calendar date detection for all 6 events, including year wrap-around for New Year.");

// Check 3: Strict genre rules
const christmas = SEASONAL_CONFIGS.find(s => s.id === "christmas");
assert(christmas.excludeGenres.includes("horror"), "Christmas must strictly exclude horror");
assert(christmas.excludeGenres.includes("thriller"), "Christmas must strictly exclude thriller");

const halloween = SEASONAL_CONFIGS.find(s => s.id === "halloween");
assert(halloween.includeGenres.includes("horror"), "Halloween must include horror");
assert(halloween.excludeGenres.includes("family"), "Halloween must exclude family/kids");

console.log("PASS: Strict genre rules verified (Christmas excludes horror/thriller; Halloween focuses horror).");

// Check 4: Vue template compilation using bundled vendor vue runtime
const vuePath = path.join(__dirname, '../../static/vendor/vue.global.prod.js');
const vueCode = fs.readFileSync(vuePath, 'utf8');

const makeElement = (tag) => {
  let _html = '';
  return {
    tagName: tag,
    style: {},
    children: [],
    set innerHTML(val) {
      _html = val;
      const m = val.match(/foo="([^"]*)"/);
      this.children = m ? [{ getAttribute: () => m[1] }] : [];
    },
    get textContent() {
      return _html.replace(/<[^>]+>/g, '');
    }
  };
};

const windowMock = {
  addEventListener: () => {},
  removeEventListener: () => {},
  location: { href: 'http://localhost/' },
  document: {
    createElement: makeElement,
    querySelector: () => null,
    querySelectorAll: () => [],
    head: makeElement('head'),
    body: makeElement('body'),
  }
};

const ctx = vm.createContext({
  window: windowMock,
  document: windowMock.document,
  console,
  setTimeout,
  clearTimeout,
});

vm.runInContext(vueCode, ctx);

const seasonalBannerTemplateMatch = appJsContent.match(/const SeasonalBanner = \{[\s\S]*?template: `([\s\S]*?)`,\s*\};/);
assert(seasonalBannerTemplateMatch, "Could not find SeasonalBanner template");

const seasonalRender = ctx.Vue.compile(seasonalBannerTemplateMatch[1]);
assert.strictEqual(typeof seasonalRender, 'function', 'SeasonalBanner.template compiles to render function');
console.log("PASS: SeasonalBanner Vue template compiled successfully.");

const homePageTemplateMatch = appJsContent.match(/const HomePage = \{[\s\S]*?template: `([\s\S]*?)`,\s*\r?\n\s*setup/);
assert(homePageTemplateMatch, "Could not find HomePage template");

const homeRender = ctx.Vue.compile(homePageTemplateMatch[1]);
assert.strictEqual(typeof homeRender, 'function', 'HomePage.template compiles to render function');
console.log("PASS: HomePage Vue template compiled successfully.");

console.log("\nAll Seasonal Banner tests passed successfully!");
