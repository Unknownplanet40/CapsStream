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
