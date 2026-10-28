const fs = require('fs');
const assert = require('assert');
const vm = require('vm');

const vueCode = fs.readFileSync('./static/vendor/vue.global.prod.js', 'utf8');

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

const window = {
  addEventListener: () => {},
  removeEventListener: () => {},
  document: {
    createElement: makeElement,
    createTextNode: () => ({}),
  }
};
const ctx = { window, document: window.document, console };
vm.createContext(ctx);
vm.runInContext(vueCode, ctx);

const appJs = fs.readFileSync('./static/js/app.js', 'utf8');

// Test 1: SuggestModal template
const suggestMatch = appJs.match(/const SuggestModal = \{([\s\S]*?)\r?\n\};\r?\n\r?\n\/\/ ─── Player Page/);
assert(suggestMatch, 'SuggestModal definition found in app.js');

vm.runInContext('const VueRouter = { useRouter: () => ({ push: () => {} }) }; const API = { get: async () => [] }; const imgUrl = () => ""; window.SuggestModal = {' + suggestMatch[1] + '};', ctx);
const suggestTemplate = ctx.window.SuggestModal.template;
assert(suggestTemplate, 'SuggestModal has template string');

console.log('Compiling SuggestModal template...');
const suggestRender = ctx.Vue.compile(suggestTemplate);
assert.strictEqual(typeof suggestRender, 'function', 'SuggestModal.template compiles to a render function');
console.log('PASS: SuggestModal template compiled successfully.');

// Test 2: App template
const appMatch = appJs.match(/const App = \{([\s\S]*?)\r?\n\};\r?\n\r?\n\/\/ ─── Mount App/);
assert(appMatch, 'App definition found in app.js');

vm.runInContext('const MediaCard = {}, TvContentRow = {}, ScanProgressWidget = {}, ShortcutsModal = {}, SuggestModal = {}; window.App = {' + appMatch[1] + '};', ctx);
const appTemplate = ctx.window.App.template;
assert(appTemplate, 'App has template string');

console.log('Compiling App template...');
const appRender = ctx.Vue.compile(appTemplate);
assert.strictEqual(typeof appRender, 'function', 'App.template compiles to a render function');
console.log('PASS: App template compiled successfully.');

// Test 3: ProfilesPage template
const profilesMatch = appJs.match(/const ProfilesPage = \{([\s\S]*?)\r?\n\};\r?\n\r?\n\/\/ ─── Setup Wizard Page/);
assert(profilesMatch, 'ProfilesPage definition found in app.js');

vm.runInContext('window.ProfilesPage = {' + profilesMatch[1] + '};', ctx);
const profilesTemplate = ctx.window.ProfilesPage.template;
assert(profilesTemplate, 'ProfilesPage has template string');
assert(profilesTemplate.includes('presetAvatars'), 'ProfilesPage template includes presetAvatars grid');

console.log('Compiling ProfilesPage template...');
const profilesRender = ctx.Vue.compile(profilesTemplate);
assert.strictEqual(typeof profilesRender, 'function', 'ProfilesPage.template compiles to a render function');
console.log('PASS: ProfilesPage template compiled successfully.');

// Test 4: RequestsPage template
const requestsMatch = appJs.match(/const RequestsPage = \{([\s\S]*?)\r?\n\};\r?\n\r?\n\/\/ ─── Router/);
assert(requestsMatch, 'RequestsPage definition found in app.js');

vm.runInContext('window.RequestsPage = {' + requestsMatch[1] + '};', ctx);
const requestsTemplate = ctx.window.RequestsPage.template;
assert(requestsTemplate, 'RequestsPage has template string');
assert(requestsTemplate.includes('req-dialogue-thread'), 'RequestsPage template includes req-dialogue-thread container');

console.log('Compiling RequestsPage template...');
const requestsRender = ctx.Vue.compile(requestsTemplate);
assert.strictEqual(typeof requestsRender, 'function', 'RequestsPage.template compiles to a render function');
console.log('PASS: RequestsPage template compiled successfully.');

// Test 5: DetailPage template with delete confirmation modal
const detailMatch = appJs.match(/const DetailPage = \{([\s\S]*?)\r?\n\};\r?\n\r?\n\/\/ ─── Settings Search Index/);
assert(detailMatch, 'DetailPage definition found in app.js');

vm.runInContext('const TrailerModal = {}; window.DetailPage = {' + detailMatch[1] + '};', ctx);
const detailTemplate = ctx.window.DetailPage.template;
assert(detailTemplate, 'DetailPage has template string');
assert(detailTemplate.includes('media-delete-modal-card'), 'DetailPage template includes media-delete-modal-card');
assert(detailTemplate.includes('media-delete-files-empty'), 'DetailPage template includes media-delete-files-empty');

console.log('Compiling DetailPage template...');
const detailRender = ctx.Vue.compile(detailTemplate);
assert.strictEqual(typeof detailRender, 'function', 'DetailPage.template compiles to a render function');
console.log('PASS: DetailPage template compiled successfully.');
