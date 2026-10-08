/**
 * CapsStream - Player Logo Loader Module
 * Pure state logic and logo URL validation for the initial playback load screen.
 */
(function (root, factory) {
  if (typeof module === "object" && typeof module.exports === "object") {
    module.exports = factory();
  } else {
    var exports = factory();
    root.CapsLogoLoader = exports;
    root.logoLoaderState = exports.logoLoaderState;
    root.isValidLogoUrl = exports.isValidLogoUrl;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ALLOWED_EXTS = [".png", ".svg", ".webp"];

  /**
   * Validate that the resolved logo URL starts with /metadata/images/
   * and ends with an allowed image extension without path traversal.
   *
   * @param {string} url
   * @returns {boolean}
   */
  function isValidLogoUrl(url) {
    if (!url || typeof url !== "string") return false;
    var trimmed = url.trim();
    if (!trimmed.startsWith("/metadata/images/")) return false;
    if (trimmed.includes("..") || trimmed.includes("\\")) return false;

    // Check extension before query params or hash
    var cleanPath = trimmed.split("?")[0].split("#")[0].toLowerCase();
    return ALLOWED_EXTS.some(function (ext) {
      return cleanPath.endsWith(ext);
    });
  }

  /**
   * Pure state function determining whether to render the glinting logo or the plain spinner.
   *
   * @param {Object} params
   * @param {boolean} params.isInitialLoad - True only while player is initially loading media
   * @param {string|null} params.logoPath - Raw or normalized logo path
   * @param {boolean} params.logoReady - True once logo has decoded successfully
   * @param {boolean} params.isError - True if preload errored or timed out
   * @param {boolean} params.reducedMotion - True if client prefers reduced motion
   * @returns {{ showLogo: boolean, showSpinner: boolean, enableGlint: boolean }}
   */
  function logoLoaderState(params) {
    var isInitialLoad = Boolean(params && params.isInitialLoad);
    var logoPath = params && params.logoPath ? String(params.logoPath).trim() : null;
    var logoReady = Boolean(params && params.logoReady);
    var isError = Boolean(params && params.isError);
    var reducedMotion = Boolean(params && params.reducedMotion);

    // If not initial load, or no logo path, or error occurred, or logo not decoded yet:
    // always fall back to the spinner
    if (!isInitialLoad || !logoPath || isError || !logoReady) {
      return {
        showLogo: false,
        showSpinner: true,
        enableGlint: false
      };
    }

    return {
      showLogo: true,
      showSpinner: false,
      enableGlint: !reducedMotion
    };
  }

  return {
    ALLOWED_EXTS: ALLOWED_EXTS,
    isValidLogoUrl: isValidLogoUrl,
    logoLoaderState: logoLoaderState
  };
});
