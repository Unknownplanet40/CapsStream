const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const logoLoader = require(path.resolve(__dirname, "../static/js/logo-loader.js"));
const { logoLoaderState, isValidLogoUrl } = logoLoader;

test("isValidLogoUrl - accepts valid metadata image paths with allowed extensions", () => {
  assert.equal(isValidLogoUrl("/metadata/images/w500_test.png"), true);
  assert.equal(isValidLogoUrl("/metadata/images/w500_test.svg"), true);
  assert.equal(isValidLogoUrl("/metadata/images/w500_test.webp"), true);
  assert.equal(isValidLogoUrl("/metadata/images/logo.PNG"), true);
  assert.equal(isValidLogoUrl("/metadata/images/logo.png?v=2.5"), true);
});

test("isValidLogoUrl - rejects invalid prefixes, extensions, and traversal attempts", () => {
  assert.equal(isValidLogoUrl("images/logo.png"), false);
  assert.equal(isValidLogoUrl("https://example.com/logo.png"), false);
  assert.equal(isValidLogoUrl("/metadata/images/../evil.png"), false);
  assert.equal(isValidLogoUrl("/metadata/images\\evil.png"), false);
  assert.equal(isValidLogoUrl("/metadata/images/logo.jpg"), false);
  assert.equal(isValidLogoUrl("/metadata/images/logo.exe"), false);
  assert.equal(isValidLogoUrl(null), false);
  assert.equal(isValidLogoUrl(""), false);
  assert.equal(isValidLogoUrl(12345), false);
});

test("logoLoaderState - shows glinting logo when logo is present, decoded, and isInitialLoad is true", () => {
  const state = logoLoaderState({
    isInitialLoad: true,
    logoPath: "images/w500_logo.png",
    logoReady: true,
    isError: false,
    reducedMotion: false
  });
  assert.deepEqual(state, {
    showLogo: true,
    showSpinner: false,
    enableGlint: true
  });
});

test("logoLoaderState - falls back to spinner when no logo path is available", () => {
  const stateNoLogo = logoLoaderState({
    isInitialLoad: true,
    logoPath: null,
    logoReady: false,
    isError: false,
    reducedMotion: false
  });
  assert.deepEqual(stateNoLogo, {
    showLogo: false,
    showSpinner: true,
    enableGlint: false
  });

  const stateEmptyLogo = logoLoaderState({
    isInitialLoad: true,
    logoPath: "   ",
    logoReady: true,
    isError: false,
    reducedMotion: false
  });
  assert.deepEqual(stateEmptyLogo, {
    showLogo: false,
    showSpinner: true,
    enableGlint: false
  });
});

test("logoLoaderState - falls back to spinner while logo is still preloading", () => {
  const statePreloading = logoLoaderState({
    isInitialLoad: true,
    logoPath: "images/w500_logo.png",
    logoReady: false,
    isError: false,
    reducedMotion: false
  });
  assert.deepEqual(statePreloading, {
    showLogo: false,
    showSpinner: true,
    enableGlint: false
  });
});

test("logoLoaderState - falls back to spinner if logo preload errors or times out", () => {
  const stateError = logoLoaderState({
    isInitialLoad: true,
    logoPath: "images/w500_logo.png",
    logoReady: false,
    isError: true,
    reducedMotion: false
  });
  assert.deepEqual(stateError, {
    showLogo: false,
    showSpinner: true,
    enableGlint: false
  });
});

test("logoLoaderState - disables glint animation when reduced motion is preferred", () => {
  const stateReduced = logoLoaderState({
    isInitialLoad: true,
    logoPath: "images/w500_logo.png",
    logoReady: true,
    isError: false,
    reducedMotion: true
  });
  assert.deepEqual(stateReduced, {
    showLogo: true,
    showSpinner: false,
    enableGlint: false
  });
});

test("logoLoaderState - shows plain spinner when isInitialLoad is false (mid-playback stalls/seeks)", () => {
  const stateMidPlayback = logoLoaderState({
    isInitialLoad: false,
    logoPath: "images/w500_logo.png",
    logoReady: true,
    isError: false,
    reducedMotion: false
  });
  assert.deepEqual(stateMidPlayback, {
    showLogo: false,
    showSpinner: true,
    enableGlint: false
  });
});

test("logoLoaderState - slow logo preloading transition simulation", () => {
  // Step 1: Initial load started, logo fetching/preloading
  let s1 = logoLoaderState({ isInitialLoad: true, logoPath: "images/logo.png", logoReady: false, isError: false });
  assert.equal(s1.showSpinner, true);
  assert.equal(s1.showLogo, false);

  // Step 2: Logo finishes decoding
  let s2 = logoLoaderState({ isInitialLoad: true, logoPath: "images/logo.png", logoReady: true, isError: false });
  assert.equal(s2.showSpinner, false);
  assert.equal(s2.showLogo, true);
  assert.equal(s2.enableGlint, true);

  // Step 3: Video playing event fires -> isInitialLoad false
  let s3 = logoLoaderState({ isInitialLoad: false, logoPath: "images/logo.png", logoReady: true, isError: false });
  assert.equal(s3.showLogo, false);
  assert.equal(s3.showSpinner, true);
});
