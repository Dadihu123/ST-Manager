import { buildBeautifyPreviewAssetUrl } from "../api/beautify.js";
import {
  clearIsolatedHtml,
  renderIsolatedHtml,
} from "../runtime/renderRuntime.js";
import {
  buildBeautifyPreviewDocument,
  DEFAULT_PREVIEW_SCENE_ID,
  PREVIEW_SCENE_OPTIONS,
} from "./beautifyPreviewDocument.js";

function resolvePreviewRenderMinHeight(platform) {
  return platform === "mobile" ? 420 : 520;
}

function resolvePreviewIdentityValue(
  overrideIdentity = {},
  globalIdentity = {},
) {
  return {
    name: overrideIdentity.name || globalIdentity.name || "",
    avatarSrc: overrideIdentity.avatar_file
      ? buildBeautifyPreviewAssetUrl(overrideIdentity.avatar_file)
      : globalIdentity.avatar_file
        ? buildBeautifyPreviewAssetUrl(globalIdentity.avatar_file)
        : "",
  };
}

function resolveVariantWallpaper(
  detail = {},
  variant = {},
  selectedWallpaperId = "",
  activeWallpaper = null,
) {
  const allowedWallpaperIds = Array.isArray(variant?.wallpaper_ids)
    ? variant.wallpaper_ids
    : [];
  const resolveWallpaperById = (wallpaperId) => {
    const normalizedWallpaperId = String(wallpaperId || "").trim();
    if (!normalizedWallpaperId) {
      return null;
    }
    return detail?.wallpapers?.[normalizedWallpaperId] || null;
  };

  const resolveAllowedWallpaper = (wallpaperId) => {
    const normalizedWallpaperId = String(wallpaperId || "").trim();
    if (!normalizedWallpaperId) {
      return null;
    }
    if (!allowedWallpaperIds.includes(normalizedWallpaperId)) {
      return null;
    }
    return resolveWallpaperById(normalizedWallpaperId);
  };

  return (
    resolveWallpaperById(variant?.selected_wallpaper_id) ||
    resolveAllowedWallpaper(selectedWallpaperId) ||
    resolveAllowedWallpaper(activeWallpaper?.id)
  );
}

const MAX_PREVIEW_HOST_RETRIES = 3;
const SETTINGS_PREVIEW_DESKTOP_CHAT_WIDTH = 55;

function resolveSettingsPreviewTheme(platform) {
  if (platform === "mobile") {
    return {};
  }

  return {
    chat_width: SETTINGS_PREVIEW_DESKTOP_CHAT_WIDTH,
  };
}

function resolvePreviewShellPlatform(previewDevice, viewportWidth) {
  if (previewDevice === 'mobile') {
    return 'mobile';
  }
  if (previewDevice === 'dual') {
    return viewportWidth <= 900 ? 'mobile' : 'pc';
  }
  return 'pc';
}

export default function beautifyPreviewFrame() {
  return {
    isPreviewLoaded: false,
    previewHostRetryCount: 0,
    previewHostFrameRetryPending: false,
    previewHostObserver: null,

    get previewHostEl() {
      if (this.$refs?.previewHost) {
        return this.$refs.previewHost;
      }
      return this.$el?.querySelector(".beautify-preview-host") || null;
    },

    get previewShellMode() {
      return this.$store.global.beautifyPreviewDevice || "pc";
    },

    get previewScenes() {
      return PREVIEW_SCENE_OPTIONS;
    },

    get activePreviewScene() {
      const activeSceneId = this.$store.global.beautifyActiveScene;
      return (
        this.previewScenes.find((scene) => scene.id === activeSceneId) ||
        this.previewScenes.find((scene) => scene.id === DEFAULT_PREVIEW_SCENE_ID) ||
        this.previewScenes[0]
      );
    },

    get hasActiveDetail() {
      return Boolean(
        this.$store.global.beautifyActiveDetail ||
        this.$store.global.beautifyWorkspace === "settings",
      );
    },

    get isPreviewUnavailable() {
      return !!this.$store.global.beautifyPreviewUnavailableReason;
    },

    init() {
      this.startPreviewHostObserver();
      this.$watch("$store.global.beautifyPreviewResetToken", () => {
        this.resetPreview();
      });
      this.$watch("$store.global.beautifyActiveDetail", (detail) => {
        if (!detail) {
          if (this.$store.global.beautifyWorkspace !== "settings") {
            this.resetPreview();
            return;
          }
          if (this.isPreviewLoaded) {
            this.$nextTick(() => this.renderPreview());
          }
          return;
        }
        if (this.isPreviewLoaded) {
          this.$nextTick(() => this.renderPreview());
        }
      });
      this.$watch("$store.global.beautifyActiveVariant", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.beautifyActiveWallpaper", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.beautifyWorkspace", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.beautifyGlobalSettings", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.beautifyPreviewDevice", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.beautifyActiveScene", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
      this.$watch("$store.global.isDarkMode", () => {
        if (this.isPreviewLoaded) this.renderPreview();
      });
    },

    setPreviewScene(sceneId) {
      const normalizedSceneId = String(sceneId || "").trim();
      const nextScene = this.previewScenes.find(
        (scene) => scene.id === normalizedSceneId,
      );
      if (!nextScene) {
        return;
      }
      this.$store.global.beautifyActiveScene = nextScene.id;
    },

    startPreviewHostObserver() {
      if (
        this.previewHostObserver ||
        typeof MutationObserver === "undefined" ||
        !this.$el
      ) {
        return;
      }

      this.previewHostObserver = new MutationObserver(() => {
        if (!this.isPreviewLoaded || !this.previewHostEl) {
          return;
        }
        this.renderPreview();
      });

      this.previewHostObserver.observe(this.$el, {
        childList: true,
        subtree: true,
      });
    },

    loadPreview() {
      if (!this.hasActiveDetail) {
        return;
      }
      this.startPreviewHostObserver();
      this.previewHostRetryCount = 0;
      this.previewHostFrameRetryPending = false;
      this.isPreviewLoaded = true;
      this.$nextTick(() => this.renderPreview());
    },

    schedulePreviewHostFrameRetry() {
      if (this.previewHostFrameRetryPending || !this.isPreviewLoaded) {
        return;
      }

      this.previewHostFrameRetryPending = true;

      let finished = false;

      const onFrame = () => {
        if (finished) {
          return;
        }
        finished = true;
        this.previewHostFrameRetryPending = false;
        this.renderPreview();
      };

      if (typeof window !== "undefined") {
        if (typeof window.requestAnimationFrame === "function") {
          window.requestAnimationFrame(onFrame);
          if (typeof window.setTimeout === "function") {
            window.setTimeout(onFrame, 48);
          }
          return;
        }

        if (typeof window.setTimeout === "function") {
          window.setTimeout(onFrame, 16);
          return;
        }
      }

      onFrame();
    },

    resolvePreviewState() {
      const workspace = this.$store.global.beautifyWorkspace || "packages";
      const globalSettings = this.$store.global.beautifyGlobalSettings || {};
      const detail = this.$store.global.beautifyActiveDetail || {};
      const variant = this.$store.global.beautifyActiveVariant || {};
      const variantWallpaper = resolveVariantWallpaper(
        detail,
        variant,
        this.$store.global.beautifySelectedWallpaperId,
        this.$store.global.beautifyActiveWallpaper,
      );
      const globalWallpaper = globalSettings.wallpaper || {};
      const packageIdentities = detail.identity_overrides || {};
      const globalIdentities = globalSettings.identities || {};
      const useGlobalOnly = workspace === "settings";
      const reactiveWidth = Number(this.$store?.global?.windowWidth);
      const viewportWidth = Number.isFinite(reactiveWidth) && reactiveWidth > 0
        ? reactiveWidth
        : (typeof window !== 'undefined' ? Number(window.innerWidth || 0) : 0);
      const platform = resolvePreviewShellPlatform(
        this.previewShellMode,
        viewportWidth,
      );
      const resolvedWallpaperFile = useGlobalOnly
        ? globalWallpaper.file
        : variantWallpaper?.file || globalWallpaper.file;

      return {
        platform,
        themeMode: this.$store.global.isDarkMode ? 'dark' : 'light',
        theme: useGlobalOnly
          ? resolveSettingsPreviewTheme(platform)
          : variant.theme_data || {},
        activeScene: this.activePreviewScene?.id || DEFAULT_PREVIEW_SCENE_ID,
        detail: useGlobalOnly
          ? {}
          : {
              packageName: String(detail.name || '').trim(),
              tags: Array.isArray(detail.tags)
                ? detail.tags.map((tag) => String(tag || '').trim()).filter(Boolean).slice(0, 8)
                : [],
              notes: String(detail.notes || '').trim(),
            },
        wallpaperUrl: resolvedWallpaperFile
          ? buildBeautifyPreviewAssetUrl(resolvedWallpaperFile)
          : "",
        identities: {
          character: resolvePreviewIdentityValue(
            useGlobalOnly ? {} : packageIdentities.character || {},
            globalIdentities.character || {},
          ),
          user: resolvePreviewIdentityValue(
            useGlobalOnly ? {} : packageIdentities.user || {},
            globalIdentities.user || {},
          ),
        },
      };
    },

    renderPreview() {
      if (!this.isPreviewLoaded) {
        return;
      }

      if (this.isPreviewUnavailable) {
        return;
      }

      if (!this.hasActiveDetail) {
        return;
      }

      const host = this.previewHostEl;
      if (!host) {
        if (this.previewHostRetryCount < MAX_PREVIEW_HOST_RETRIES) {
          this.previewHostRetryCount += 1;
          this.$nextTick(() => this.renderPreview());
        } else {
          this.schedulePreviewHostFrameRetry();
        }
        return;
      }

      this.previewHostRetryCount = 0;
      this.previewHostFrameRetryPending = false;

      const state = this.resolvePreviewState();
      const documentHtml = buildBeautifyPreviewDocument(state);

      renderIsolatedHtml(host, {
        htmlPayload: documentHtml,
        minHeight: resolvePreviewRenderMinHeight(state.platform),
        fillHostHeight: true,
      });
    },

    resetPreview() {
      this.isPreviewLoaded = false;
      this.destroy();
    },

    destroy() {
      this.previewHostRetryCount = 0;
      this.previewHostFrameRetryPending = false;
      if (this.previewHostObserver) {
        this.previewHostObserver.disconnect();
        this.previewHostObserver = null;
      }
      const host = this.previewHostEl;
      if (host) {
        clearIsolatedHtml(host, { clearShadow: true });
      }
    },
  };
}
