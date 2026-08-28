import {
  buildBeautifyPreviewAssetUrl,
  deleteBeautifyPackage,
  getBeautifySettings,
  getBeautifyPackage,
  importBeautifyScreenshot,
  importBeautifyTheme,
  importBeautifyVariant,
  importBeautifyPackageAvatar,
  importGlobalBeautifyAvatar,
  importGlobalBeautifyWallpaper,
  importSharedPreviewWallpaperForBeautify,
  importBeautifyWallpaper,
  listBeautifyPackages,
  sendBeautifyThemeToSt,
  selectSharedPreviewWallpaperForBeautify,
  updateBeautifyPackageIdentities,
  updateBeautifySettings,
  updateBeautifyVariant,
} from "../api/beautify.js";
import sharedWallpaperPicker from "./sharedWallpaperPicker.js";

if (typeof window !== "undefined") {
  window.sharedWallpaperPicker = sharedWallpaperPicker;
}

function filterPackages(items, search, platformFilter) {
  const keyword = String(search || "")
    .trim()
    .toLowerCase();
  return (items || []).filter((item) => {
    const nameMatch =
      !keyword ||
      String(item.name || "")
        .toLowerCase()
        .includes(keyword);
    const platformMatch =
      platformFilter === "all" ||
      (item.platforms || []).includes(platformFilter);
    return nameMatch && platformMatch;
  });
}

export default function beautifyGrid() {
  return {
    isLoading: false,
    isActionLoading: false,
    pendingThemeSendTarget: null,
    globalCharacterName: "",
    globalUserName: "",
    packageCharacterName: "",
    packageUserName: "",

    get packages() {
      return this.$store.global.beautifyList || [];
    },

    set packages(val) {
      this.$store.global.beautifyList = Array.isArray(val) ? val : [];
      return true;
    },

    get beautifySearch() {
      return this.$store.global.beautifySearch || "";
    },

    set beautifySearch(val) {
      this.$store.global.beautifySearch = val;
      return true;
    },

    get platformFilter() {
      return this.$store.global.beautifyPlatformFilter || "all";
    },

    set platformFilter(val) {
      this.$store.global.beautifyPlatformFilter = val;
      return true;
    },

    get selectedPackageId() {
      return this.$store.global.beautifySelectedPackageId || "";
    },

    set selectedPackageId(val) {
      this.$store.global.beautifySelectedPackageId = val;
      return true;
    },

    get selectedVariantId() {
      return this.$store.global.beautifySelectedVariantId || "";
    },

    set selectedVariantId(val) {
      this.$store.global.beautifySelectedVariantId = val;
      return true;
    },

    get variantSelectionByDevice() {
      return this.$store.global.beautifyVariantSelectionByDevice || {};
    },

    set variantSelectionByDevice(val) {
      this.$store.global.beautifyVariantSelectionByDevice = val || {};
      return true;
    },

    get selectedWallpaperId() {
      return this.$store.global.beautifySelectedWallpaperId || "";
    },

    set selectedWallpaperId(val) {
      this.$store.global.beautifySelectedWallpaperId = val;
      return true;
    },

    get selectedVariantPlatform() {
      return this.$store.global.beautifyPreviewDevice || "pc";
    },

    set selectedVariantPlatform(val) {
      this.$store.global.beautifyPreviewDevice = val;
      return true;
    },

    get mobileFullscreenOpen() {
      return !!this.$store.global.beautifyMobileFullscreenOpen;
    },

    set mobileFullscreenOpen(val) {
      this.$store.global.beautifyMobileFullscreenOpen = !!val;
      return true;
    },

    get workspace() {
      return this.$store.global.beautifyWorkspace || "packages";
    },

    set workspace(val) {
      this.$store.global.beautifyWorkspace = val;
      return true;
    },

    get beautifyWorkspace() {
      return this.workspace;
    },

    set beautifyWorkspace(val) {
      this.workspace = val;
      return true;
    },

    get stageMode() {
      return this.$store.global.beautifyStageMode || "preview";
    },

    set stageMode(val) {
      this.$store.global.beautifyStageMode = val;
      return true;
    },

    get packageDetailCollapsed() {
      return !!this.$store.global.beautifyPackageDetailCollapsed;
    },

    set packageDetailCollapsed(val) {
      this.$store.global.beautifyPackageDetailCollapsed = !!val;
      return true;
    },

    get packageDetailDrawerOpen() {
      return !!this.$store.global.beautifyPackageDetailDrawerOpen;
    },

    set packageDetailDrawerOpen(val) {
      this.$store.global.beautifyPackageDetailDrawerOpen = !!val;
      return true;
    },

    get showMobileFullscreen() {
      return this.mobileFullscreenOpen && this.isMobileFullscreenEnabled();
    },

    get activeDetail() {
      return this.$store.global.beautifyActiveDetail || null;
    },

    get activePackage() {
      return this.activeDetail || null;
    },

    get activeVariant() {
      return this.$store.global.beautifyActiveVariant || null;
    },

    get activeWallpaper() {
      return this.$store.global.beautifyActiveWallpaper || null;
    },

    get screenshotOptions() {
      return Object.values(this.activeDetail?.screenshots || {});
    },

    get activeScreenshot() {
      return (
        this.activeDetail?.screenshots?.[
          this.$store.global.beautifySelectedScreenshotId
        ] ||
        this.screenshotOptions[0] ||
        null
      );
    },

    hasMobilePreviewContext() {
      return this.workspace === "settings" || !!this.activePackage;
    },

    requestPreviewReset() {
      this.$store.global.beautifyPreviewResetToken =
        Number(this.$store.global.beautifyPreviewResetToken || 0) + 1;
    },

    closeMobilePreviewAndReset() {
      this.closeMobileFullscreen();
      this.requestPreviewReset();
    },

    alignSettingsPreviewDeviceToViewport() {
      if (this.workspace !== "settings") {
        return;
      }
      this.selectedVariantPlatform = this.isMobileBeautifyViewport()
        ? "mobile"
        : "pc";
    },

    syncMobileFullscreenState() {
      this.alignSettingsPreviewDeviceToViewport();
      if (this.workspace === "packages" && this.activeVariant) {
        const previewPlatform = this.resolvePackagePreviewPlatform();
        const nextVariant =
          this.resolvePreferredVariantForDevice(previewPlatform) ||
          this.activeVariant;
        this.selectedVariantPlatform = previewPlatform;
        if (nextVariant) {
          this.applyActiveVariant(nextVariant, { preservePreviewDevice: true });
        } else {
          this.syncPreviewUnavailableState({ device: previewPlatform });
        }
      }
      if (this.isMobileBeautifyViewport()) {
        this.closePackageDetailDrawer();
      }
      if (this.mobileFullscreenOpen && !this.isMobileFullscreenEnabled()) {
        this.closeMobilePreviewAndReset();
      }
    },

    get filteredPackages() {
      return filterPackages(
        this.packages,
        this.beautifySearch,
        this.platformFilter,
      );
    },

    get hasPcVariant() {
      return (
        !!this.findVariantByPlatform("pc") ||
        !!this.findVariantByPlatform("dual")
      );
    },

    get hasMobileVariant() {
      return (
        !!this.findVariantByPlatform("mobile") ||
        !!this.findVariantByPlatform("dual")
      );
    },

    get hasDualVariant() {
      return !!this.findVariantByPlatform("dual");
    },

    get canPreviewDualTarget() {
      const detail = this.activeDetail;
      if (!detail?.variants) return false;
      if (this.findVariantByPlatform("dual", detail)) {
        return true;
      }
      if (this.isMobileBeautifyViewport()) {
        return !!this.findVariantForPreviewPlatform("mobile", detail);
      }
      return (
        !!this.findVariantForPreviewPlatform("pc", detail) ||
        !!this.findVariantForPreviewPlatform("mobile", detail)
      );
    },

    get wallpaperOptions() {
      const variant = this.activeVariant;
      const detail = this.activeDetail;
      if (!variant || !detail) return [];
      return (variant.wallpaper_ids || [])
        .map((id) => detail.wallpapers?.[id])
        .filter(Boolean);
    },

    get variantOptions() {
      const detail = this.activeDetail;
      if (!detail?.variants) return [];
      return Object.values(detail.variants).map((variant) => ({
        ...variant,
        label:
          String(variant?.name || variant?.theme_name || '').trim() ||
          `${variant.platform || 'pc'} · ${variant.id}`,
      }));
    },

    compatibleVariantOptions(device = this.selectedVariantPlatform) {
      return this.variantOptions.filter((variant) =>
        this.isVariantCompatibleWithDevice(variant, device),
      );
    },

    mergeSharedWallpaperIntoStore(wallpaper) {
      if (!wallpaper?.id) return;
      const current = Array.isArray(this.$store.global.sharedWallpapers)
        ? this.$store.global.sharedWallpapers.filter(
            (entry) => entry?.id !== wallpaper.id,
          )
        : [];
      current.push(wallpaper);
      this.$store.global.sharedWallpapers = current;
    },

    prunePackageSharedWallpapersFromStore(packageId) {
      const resolvedPackageId = String(packageId || "").trim();
      if (!resolvedPackageId) return;

      const globalStore = this.$store.global;
      const current = Array.isArray(globalStore.sharedWallpapers)
        ? globalStore.sharedWallpapers
        : [];
      const removedIds = current
        .filter(
          (item) =>
            item?.source_type === "package_embedded" &&
            String(item?.origin_package_id || "").trim() === resolvedPackageId,
        )
        .map((item) => item.id)
        .filter(Boolean);
      if (!removedIds.length) return;

      globalStore.sharedWallpapers = current.filter(
        (item) => !removedIds.includes(item?.id),
      );

      if (
        globalStore.settingsForm &&
        removedIds.includes(globalStore.settingsForm.manager_wallpaper_id)
      ) {
        globalStore.settingsForm.manager_wallpaper_id = "";
        if (
          typeof globalStore.updateBackgroundImage === "function" &&
          typeof globalStore.resolveManagerBackgroundUrl === "function"
        ) {
          globalStore.updateBackgroundImage(
            globalStore.resolveManagerBackgroundUrl(),
          );
        }
      }

      if (
        globalStore.beautifyGlobalSettings &&
        removedIds.includes(globalStore.beautifyGlobalSettings.preview_wallpaper_id)
      ) {
        globalStore.beautifyGlobalSettings = {
          ...globalStore.beautifyGlobalSettings,
          preview_wallpaper_id: "",
          wallpaper: null,
        };
      }
    },

    normalizePackageDetailRailState() {
      this.closePackageDetailDrawer();
    },

    init() {
      this.$watch("$store.global.currentMode", (mode) => {
        if (mode === "beautify") {
          this.fetchPackages();
          this.fetchGlobalSettings();
        } else if (this.mobileFullscreenOpen) {
          this.closePackageDetailDrawer();
          this.closeMobilePreviewAndReset();
        } else {
          this.closePackageDetailDrawer();
          this.closeMobileFullscreen();
        }
      });

      this.$watch("$store.global.beautifySearch", () => {
        if (this.$store.global.currentMode === "beautify") {
          this.ensureSelectedPackageStillVisible();
        }
      });

      this.$watch("$store.global.beautifyPlatformFilter", () => {
        if (this.$store.global.currentMode === "beautify") {
          this.ensureSelectedPackageStillVisible();
        }
      });

      window.addEventListener("refresh-beautify-list", () => {
        if (this.$store.global.currentMode === "beautify") {
          this.fetchPackages();
        }
      });

      if (typeof window !== "undefined" && window?.addEventListener) {
        window.addEventListener("resize", () => {
          this.syncMobileFullscreenState();
        });
      }

      window.stUploadBeautifyThemeFiles = (files) =>
        this.handleThemeFiles(files);
      if (this.$store.global.currentMode === "beautify") {
        this.fetchPackages();
        this.fetchGlobalSettings();
      }
    },

    syncGlobalSettingsFields() {
      const globalSettings = this.$store.global.beautifyGlobalSettings || {};
      const identities = globalSettings.identities || {};
      this.globalCharacterName = identities.character?.name || "";
      this.globalUserName = identities.user?.name || "";
    },

    syncPackageIdentityFields() {
      const identities = this.activeDetail?.identity_overrides || {};
      this.packageCharacterName = identities.character?.name || "";
      this.packageUserName = identities.user?.name || "";
    },

    async fetchGlobalSettings() {
      try {
        const res = await getBeautifySettings();
        if (!res?.success) {
          throw new Error(res?.error || "加载全局设置失败");
        }
        this.$store.global.beautifyGlobalSettings = res.item || null;
        this.syncGlobalSettingsFields();
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      }
    },

    async fetchPackages() {
      this.isLoading = true;
      try {
        const res = await listBeautifyPackages();
        this.packages = res.items || [];
        if (!this.selectedPackageId && this.packages.length) {
          await this.selectPackage(this.packages[0].id);
        } else if (this.selectedPackageId) {
          const loaded = await this.selectPackage(this.selectedPackageId, {
            preserveSelection: true,
          });
          if (!loaded) {
            if (this.packages.length) {
              await this.selectPackage(this.packages[0].id);
            } else {
              this.selectedPackageId = "";
              this.$store.global.beautifyActiveDetail = null;
              this.$store.global.beautifyActiveVariant = null;
              this.$store.global.beautifyActiveWallpaper = null;
              this.selectedVariantId = "";
              this.selectedWallpaperId = "";
              this.$store.global.beautifySelectedScreenshotId = "";
            }
          }
        }
      } catch (error) {
        this.$store.global.showToast(`加载美化库失败: ${error}`, 3000);
      } finally {
        this.isLoading = false;
      }
    },

    async selectPackage(packageId, options = {}) {
      const targetId = String(packageId || "").trim();
      if (!targetId) return false;
      const res = await getBeautifyPackage(targetId);
      if (!res?.success || !res.item) {
        return false;
      }

      this.normalizePackageDetailRailState(targetId);

      this.selectedPackageId = targetId;
      this.$store.global.beautifyActiveDetail = res.item;
      this.syncPackageIdentityFields();

      const preserveSelection = !!options.preserveSelection;
      const preferCompatibleSelection = !!options.preferCompatibleSelection;
      const previewPlatform = this.resolvePackagePreviewPlatform(res.item);
      let nextVariant = null;
      if (
        preserveSelection &&
        this.selectedVariantId &&
        res.item.variants?.[this.selectedVariantId]
      ) {
        const preservedVariant = res.item.variants[this.selectedVariantId];
        if (!preferCompatibleSelection) {
          nextVariant = preservedVariant;
        } else {
          nextVariant = this.isVariantCompatibleWithDevice(
            preservedVariant,
            previewPlatform,
          )
            ? preservedVariant
            : this.resolvePreferredVariantForDevice(previewPlatform, res.item) ||
              preservedVariant;
        }
      } else {
        nextVariant =
          this.resolvePreferredVariantForDevice(previewPlatform, res.item) ||
          Object.values(res.item.variants || {})[0] ||
          null;
      }

      this.applyActiveVariant(nextVariant);

      const nextScreenshotId = preserveSelection
        ? this.$store.global.beautifySelectedScreenshotId
        : "";
      this.$store.global.beautifySelectedScreenshotId =
        nextScreenshotId && res.item.screenshots?.[nextScreenshotId]
          ? nextScreenshotId
          : Object.values(res.item.screenshots || {})[0]?.id || "";
      return true;
    },

    resolveDefaultVariant(detail) {
      if (!detail || !detail.variants) return null;
      const previewPlatform = this.resolvePackagePreviewPlatform(detail);
      return (
        this.resolvePreferredVariantForDevice(previewPlatform, detail) ||
        Object.values(detail.variants)[0] ||
        null
      );
    },

    resolvePackagePreviewPlatform(detail = this.activeDetail) {
      if (!detail || !detail.variants) {
        return "pc";
      }

      const currentPlatform = this.selectedVariantPlatform;
      const isMobileViewport = this.isMobileBeautifyViewport();
      const hasPc = !!this.findVariantForPreviewPlatform("pc", detail);
      const hasMobile = !!this.findVariantForPreviewPlatform("mobile", detail);
      const hasDual = !!this.findVariantByPlatform("dual", detail);

      if (currentPlatform === "dual" && hasDual) {
        return "dual";
      }
      if (currentPlatform === "dual" && hasPc) {
        return "pc";
      }
      if (isMobileViewport && hasMobile) {
        return "mobile";
      }
      if (currentPlatform === "mobile" && hasMobile) {
        return "mobile";
      }
      if (currentPlatform === "mobile" && isMobileViewport) {
        return "mobile";
      }
      if (currentPlatform === "pc" && isMobileViewport && !hasMobile) {
        return "mobile";
      }
      if (currentPlatform === "pc" && hasPc) {
        return "pc";
      }
      if (hasMobile && !hasPc) {
        return "mobile";
      }
      if (isMobileViewport && hasPc && !hasMobile) {
        return "mobile";
      }
      if (hasPc && !hasMobile) {
        return "pc";
      }
      if (hasDual) {
        return "dual";
      }
      if (hasMobile) {
        return "mobile";
      }
      return "pc";
    },

    findVariantForPreviewPlatform(platform, detail = this.activeDetail) {
      if (platform === "dual") {
        return this.findVariantByPlatform("dual", detail);
      }
      return (
        this.findVariantByPlatform(platform, detail) ||
        this.findVariantByPlatform("dual", detail)
      );
    },

    resolveRememberedVariant(device, detail = this.activeDetail) {
      const variantId = this.variantSelectionByDevice?.[device] || "";
      const variant = detail?.variants?.[variantId] || null;
      if (!variant) return null;

      if (device === "pc") {
        return ["pc", "dual"].includes(variant.platform) ? variant : null;
      }
      if (device === "mobile") {
        return ["mobile", "dual"].includes(variant.platform) ? variant : null;
      }
      if (device === "dual") {
        return variant.platform === "dual" ? variant : null;
      }
      return null;
    },

    resolvePreferredVariantForDevice(
      device,
      detail = this.activeDetail,
    ) {
      const selectedVariant = detail?.variants?.[this.selectedVariantId] || null;
      if (selectedVariant && this.isVariantCompatibleWithDevice(selectedVariant, device)) {
        return selectedVariant;
      }

      return (
        this.resolveRememberedVariant(device, detail) ||
        this.compatibleVariantOptions(device)[0] ||
        null
      );
    },

    resolvePreferredVariantForDualTarget(detail = this.activeDetail) {
      const dualVariant = this.findVariantByPlatform("dual", detail);
      if (dualVariant) {
        return dualVariant;
      }

      if (this.isMobileBeautifyViewport()) {
        return this.resolvePreferredVariantForDevice("mobile", detail);
      }

      return (
        this.resolvePreferredVariantForDevice("pc", detail) ||
        this.resolvePreferredVariantForDevice("mobile", detail)
      );
    },

    recordVariantSelectionForDevice(device, variantId) {
      const next = {
        ...(this.variantSelectionByDevice || {}),
        [device]: variantId,
      };
      this.variantSelectionByDevice = next;
    },

    refreshVariantSelectionForPlatformChange(variantId, platform) {
      const resolvedVariantId = String(variantId || '').trim();
      if (!resolvedVariantId) return;

      const next = { ...(this.variantSelectionByDevice || {}) };
      const previousPcSelection = next.pc;
      const previousMobileSelection = next.mobile;
      Object.keys(next).forEach((device) => {
        if (next[device] === resolvedVariantId) {
          delete next[device];
        }
      });

      if (platform === 'dual') {
        if (previousPcSelection) {
          next.pc = previousPcSelection;
        }
        if (previousMobileSelection) {
          next.mobile = previousMobileSelection;
        }
        next.dual = resolvedVariantId;
      } else if (platform === 'pc' || platform === 'mobile') {
        next[platform] = resolvedVariantId;
      }

      this.variantSelectionByDevice = next;
    },

    isVariantCompatibleWithDevice(
      variant,
      device = this.selectedVariantPlatform,
    ) {
      const platform = String(variant?.platform || "");
      if (device === "dual") {
        if (this.isMobileBeautifyViewport()) {
          return platform === "mobile" || platform === "dual";
        }
        return platform === "pc" || platform === "mobile" || platform === "dual";
      }
      if (device === "mobile") {
        return platform === "mobile" || platform === "dual";
      }
      if (device === "pc") {
        return platform === "pc" || platform === "dual";
      }
      return false;
    },

    setPreviewUnavailable(reason = "") {
      this.$store.global.beautifyPreviewUnavailableReason = String(reason || "");
    },

    clearPreviewUnavailable() {
      this.setPreviewUnavailable("");
    },

    syncPreviewUnavailableState(options = {}) {
      const workspace = options.workspace || this.workspace;
      if (workspace === "settings") {
        this.clearPreviewUnavailable();
        return false;
      }

      const variant = options.variant || this.activeVariant;
      const device = options.device || this.selectedVariantPlatform;
      if (!variant) {
        this.clearPreviewUnavailable();
        return false;
      }

      if (!this.isVariantCompatibleWithDevice(variant, device)) {
        this.setPreviewUnavailable(
          device === "mobile"
            ? "当前变体仅支持 PC 预览，请切换到支持移动端预览的变体。"
            : "当前预览目标没有可用变体。",
        );
        return true;
      }

      this.clearPreviewUnavailable();
      return false;
    },

    selectVariant(variantId) {
      const detail = this.activeDetail;
      const variant = detail?.variants?.[variantId] || null;
      if (!variant) return;
      this.applyActiveVariant(variant, { preservePreviewDevice: true });

      this.syncPreviewUnavailableState({ variant });
      if (variant.platform === "dual") {
        this.recordVariantSelectionForDevice("dual", variant.id);
        return;
      }
      this.recordVariantSelectionForDevice(variant.platform, variant.id);
    },

    applyActiveVariant(variant, options = {}) {
      if (!variant) {
        this.$store.global.beautifyActiveVariant = null;
        this.$store.global.beautifyActiveWallpaper = null;
        this.selectedVariantId = "";
        this.selectedWallpaperId = "";
        this.clearPreviewUnavailable();
        return;
      }

      this.selectedVariantId = variant.id;
      this.$store.global.beautifyActiveVariant = variant;

      const wallpaper = this.resolveActiveWallpaper(variant);
      this.$store.global.beautifyActiveWallpaper = wallpaper;
      this.selectedWallpaperId = wallpaper?.id || "";

      if (!options.preservePreviewDevice) {
        this.selectedVariantPlatform = this.resolvePackagePreviewPlatform();
      }

      this.syncPreviewUnavailableState({ variant });
    },

    canSendActiveVariantToST() {
      if (!this.selectedPackageId || !this.activeVariant) {
        return false;
      }
      return !!String(this.activeVariant?.theme_data?.name || "").trim();
    },

    getActiveVariantSendToSTTitle() {
      if (!this.activeVariant) {
        return "请先选择一个可发送的主题变体";
      }
      if (!String(this.activeVariant?.theme_data?.name || "").trim()) {
        return "当前变体主题缺少 name，无法发送到 ST";
      }
      return "发送当前主题到 ST，并自动切换为该主题；同名主题会覆盖 ST 中现有内容";
    },

    applyActiveVariantSentState(lastSentToSt) {
      const packageId = String(
        this.pendingThemeSendTarget?.packageId || this.selectedPackageId || "",
      ).trim();
      const variantId = String(
        this.pendingThemeSendTarget?.variantId || this.activeVariant?.id || "",
      ).trim();

      if (this.$store.global.beautifyActiveVariant?.id === variantId) {
        this.$store.global.beautifyActiveVariant.last_sent_to_st = lastSentToSt;
      }

      if (
        this.activeDetail?.id === packageId &&
        variantId &&
        this.activeDetail?.variants?.[variantId]
      ) {
        this.activeDetail.variants[variantId].last_sent_to_st = lastSentToSt;
      }
    },

    async sendActiveThemeToST() {
      if (!this.canSendActiveVariantToST()) {
        this.$store.global.showToast(this.getActiveVariantSendToSTTitle(), 2400);
        return;
      }

      const packageId = this.selectedPackageId;
      const variantId = this.activeVariant.id;

      this.isActionLoading = true;
      this.pendingThemeSendTarget = { packageId, variantId };
      try {
        const res = await sendBeautifyThemeToSt({
          package_id: packageId,
          variant_id: variantId,
        });
        if (!res?.success) {
          throw new Error(res?.error || '发送主题到 ST 失败');
        }
        this.applyActiveVariantSentState(res.last_sent_to_st);
        this.$store.global.showToast("主题已发送到 ST 并设为当前主题", 2200, "card-send");
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.pendingThemeSendTarget = null;
        this.isActionLoading = false;
      }
    },

    resolveActiveWallpaper(variant) {
      const detail = this.activeDetail;
      if (!detail || !variant) return null;
      const allowedWallpaperIds = Array.isArray(variant.wallpaper_ids)
        ? variant.wallpaper_ids
        : [];
      if (
        this.selectedWallpaperId &&
        allowedWallpaperIds.includes(this.selectedWallpaperId) &&
        detail.wallpapers?.[this.selectedWallpaperId]
      ) {
        return detail.wallpapers[this.selectedWallpaperId];
      }
      const persistedWallpaperId = String(
        variant.selected_wallpaper_id || "",
      ).trim();
      if (
        persistedWallpaperId &&
        allowedWallpaperIds.includes(persistedWallpaperId) &&
        detail.wallpapers?.[persistedWallpaperId]
      ) {
        return detail.wallpapers[persistedWallpaperId];
      }
      const nextWallpaperId = allowedWallpaperIds[0];
      return nextWallpaperId
        ? detail.wallpapers?.[nextWallpaperId] || null
        : null;
    },

    findVariantByPlatform(platform, detail = this.activeDetail) {
      if (!detail || !detail.variants) return null;
      return (
        Object.values(detail.variants).find(
          (variant) => variant.platform === platform,
        ) || null
      );
    },

    async previewPlatform(platform) {
      if (platform === "dual") {
        const variant = this.resolvePreferredVariantForDualTarget();
        this.selectedVariantPlatform = "dual";
        if (variant) {
          this.applyActiveVariant(variant, { preservePreviewDevice: true });
          this.syncPreviewUnavailableState({ variant, device: "dual" });
          return;
        }

        this.setPreviewUnavailable("当前预览目标没有可用变体。");
        return;
      }

      const variant = this.resolvePreferredVariantForDevice(platform);
      if (variant) {
        this.applyActiveVariant(variant);
        this.selectedVariantPlatform = platform;
        this.syncPreviewUnavailableState({ variant, device: platform });
        return;
      }

      const dualVariant = this.findVariantByPlatform("dual");
      if (dualVariant && ["pc", "mobile", "dual"].includes(platform)) {
        this.applyActiveVariant(dualVariant);
        this.selectedVariantPlatform = platform === "dual" ? "dual" : platform;
        this.syncPreviewUnavailableState({
          variant: dualVariant,
          device: this.selectedVariantPlatform,
        });
        return;
      }

      this.setPreviewUnavailable("当前预览目标没有可用变体。");
    },

    isMobileBeautifyViewport() {
      const reactiveWidth = Number(this.$store?.global?.windowWidth);
      if (Number.isFinite(reactiveWidth) && reactiveWidth > 0) {
        return reactiveWidth <= 900;
      }

      if (typeof window === "undefined") return false;
      return Number(window.innerWidth || 0) <= 900;
    },

    isMobileFullscreenEnabled() {
      return this.hasMobilePreviewContext() && this.isMobileBeautifyViewport();
    },

    openMobileFullscreen(mode = this.stageMode) {
      const nextMode = mode === "screenshot" ? "screenshot" : "preview";
      this.stageMode = nextMode;
      this.mobileFullscreenOpen = true;
    },

    closeMobileFullscreen() {
      this.mobileFullscreenOpen = false;
    },

    switchBeautifyWorkspace(workspace) {
      this.closePackageDetailDrawer();
      if (this.mobileFullscreenOpen) {
        this.closeMobilePreviewAndReset();
      } else {
        this.closeMobileFullscreen();
      }
      this.workspace = workspace === "settings" ? "settings" : "packages";
      if (this.workspace === "settings") {
        this.alignSettingsPreviewDeviceToViewport();
        this.stageMode = "preview";
        this.syncPreviewUnavailableState({ workspace: "settings" });
        this.fetchGlobalSettings();
        return;
      }
      const previewPlatform = this.resolvePackagePreviewPlatform();
      const nextVariant = this.resolvePreferredVariantForDevice(previewPlatform);
      if (nextVariant) {
        this.applyActiveVariant(nextVariant);
        this.selectedVariantPlatform = previewPlatform;
        this.syncPreviewUnavailableState({
          variant: nextVariant,
          device: previewPlatform,
        });
        return;
      }
      this.selectedVariantPlatform = previewPlatform;
      this.syncPreviewUnavailableState({ device: previewPlatform });
    },

    setStageMode(mode) {
      const nextMode = mode === "screenshot" ? "screenshot" : "preview";
      if (this.isMobileFullscreenEnabled()) {
        this.openMobileFullscreen(nextMode);
        return;
      }
      this.stageMode = nextMode;
    },

    togglePackageDetailCollapsed() {
      if (this.workspace !== "packages" || !this.activePackage) {
        return;
      }
      const nextCollapsed = !this.packageDetailCollapsed;
      this.packageDetailCollapsed = nextCollapsed;
      if (!nextCollapsed) {
        this.packageDetailDrawerOpen = false;
      }
    },

    openPackageDetailDrawer() {
      if (this.workspace !== "packages" || !this.activePackage) {
        return;
      }
      this.packageDetailDrawerOpen = true;
    },

    closePackageDetailDrawer() {
      this.packageDetailDrawerOpen = false;
    },

    selectScreenshot(screenshotId) {
      this.$store.global.beautifySelectedScreenshotId = screenshotId || "";
      this.stageMode = "screenshot";
      if (this.isMobileFullscreenEnabled()) {
        this.mobileFullscreenOpen = true;
      }
    },

    async selectWallpaper(wallpaperId) {
      if (!this.selectedPackageId || !this.selectedVariantId) return;
      const wallpaper = this.activeDetail?.wallpapers?.[wallpaperId] || null;
      if (!wallpaper) return;

      this.isActionLoading = true;
      try {
        const res = await updateBeautifyVariant({
          package_id: this.selectedPackageId,
          variant_id: this.selectedVariantId,
          selected_wallpaper_id: wallpaper.id,
        });
        if (!res?.success) {
          throw new Error(res?.error || "更新壁纸失败");
        }

        const nextVariant = {
          ...(this.activeVariant || {}),
          ...(res.item || {}),
          selected_wallpaper_id: wallpaper.id,
        };
        this.$store.global.beautifyActiveVariant = nextVariant;
        if (this.activeDetail?.variants?.[this.selectedVariantId]) {
          this.activeDetail.variants[this.selectedVariantId] = nextVariant;
        }
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
        return;
      } finally {
        this.isActionLoading = false;
      }

      this.$store.global.beautifyActiveWallpaper = wallpaper;
      this.selectedWallpaperId = wallpaper?.id || "";
    },

    async selectGlobalWallpaper(wallpaperId) {
      const resolvedWallpaperId = String(wallpaperId || "").trim();
      if (!resolvedWallpaperId) return;

      const draftCharacterName = this.globalCharacterName;
      const draftUserName = this.globalUserName;
      this.isActionLoading = true;
      try {
        const res =
          await selectSharedPreviewWallpaperForBeautify(resolvedWallpaperId);
        if (!res?.success) {
          throw new Error(res?.msg || res?.error || "选择全局壁纸失败");
        }
        await this.fetchGlobalSettings();
        this.globalCharacterName = draftCharacterName;
        this.globalUserName = draftUserName;
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    cycleWallpaper() {
      const options = this.wallpaperOptions;
      if (!options.length) return;
      const currentIndex = options.findIndex(
        (item) => item.id === this.selectedWallpaperId,
      );
      const next =
        options[(currentIndex + 1 + options.length) % options.length];
      this.selectWallpaper(next.id);
    },

    async handleScreenshotFiles(fileList) {
      const files = Array.from(fileList || []).filter(Boolean);
      if (!files.length || !this.selectedPackageId) {
        this.$store.global.showToast("请先选择一个美化包后再导入截图", 2400);
        return;
      }

      this.isActionLoading = true;
      try {
        const hadSelection = !!this.$store.global.beautifySelectedScreenshotId;
        let firstImportedScreenshotId = "";
        for (const file of files) {
          const res = await importBeautifyScreenshot(
            file,
            this.selectedPackageId,
          );
          if (!res?.success) {
            throw new Error(res?.error || "导入截图失败");
          }
          if (!firstImportedScreenshotId) {
            firstImportedScreenshotId = res.screenshot?.id || "";
          }
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        if (!hadSelection && firstImportedScreenshotId) {
          this.selectScreenshot(firstImportedScreenshotId);
        }
        this.$store.global.showToast(`已导入 ${files.length} 张截图`, 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handleThemeFiles(fileList) {
      const files = Array.from(fileList || []).filter((file) =>
        String(file.name || "")
          .toLowerCase()
          .endsWith(".json"),
      );
      if (!files.length) {
        this.$store.global.showToast("请选择 theme JSON 文件", 2200);
        return;
      }

      this.isActionLoading = true;
      try {
        let lastPackageId = "";
        for (const file of files) {
          const res = await importBeautifyTheme(file);
          if (!res?.success) {
            throw new Error(res?.error || "导入主题失败");
          }
          lastPackageId = res.package?.id || lastPackageId;
        }
        await this.fetchPackages();
        if (lastPackageId) {
          await this.selectPackage(lastPackageId);
        }
        this.$store.global.showToast(`已导入 ${files.length} 个主题`, 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handleVariantFiles(fileList) {
      const files = Array.from(fileList || []).filter((file) =>
        String(file.name || "")
          .toLowerCase()
          .endsWith(".json"),
      );
      if (!files.length || !this.selectedPackageId) {
        this.$store.global.showToast("请先选择一个美化包后再导入变体", 2400);
        return;
      }

      this.isActionLoading = true;
      try {
        let lastVariantId = "";
        for (const file of files) {
          const res = await importBeautifyVariant(file, this.selectedPackageId);
          if (!res?.success) {
            throw new Error(res?.error || "导入变体失败");
          }
          lastVariantId = res.variant?.id || lastVariantId;
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        if (lastVariantId) {
          this.selectVariant(lastVariantId);
        }
        this.$store.global.showToast(`已导入 ${files.length} 个变体`, 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handleWallpaperFiles(fileList) {
      const file = Array.from(fileList || [])[0];
      if (!file || !this.selectedPackageId || !this.selectedVariantId) {
        this.$store.global.showToast("请先选择一个变体后再导入壁纸", 2400);
        return;
      }

      this.isActionLoading = true;
      try {
        const res = await importBeautifyWallpaper(
          file,
          this.selectedPackageId,
          this.selectedVariantId,
        );
        if (!res?.success) {
          throw new Error(res?.error || "导入壁纸失败");
        }
        this.mergeSharedWallpaperIntoStore(res.wallpaper || null);
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        this.selectWallpaper(res.wallpaper?.id || "");
        this.$store.global.showToast("壁纸已导入并绑定到当前变体", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handleGlobalWallpaperFiles(fileList) {
      const file = Array.from(fileList || [])[0];
      if (!file) return;

      const draftCharacterName = this.globalCharacterName;
      const draftUserName = this.globalUserName;
      this.isActionLoading = true;
      try {
        const res = await importSharedPreviewWallpaperForBeautify(file);
        if (!res?.success) {
          throw new Error(res?.msg || res?.error || "上传全局壁纸失败");
        }
        this.mergeSharedWallpaperIntoStore(res.item || null);
        await this.fetchGlobalSettings();
        this.globalCharacterName = draftCharacterName;
        this.globalUserName = draftUserName;
        this.$store.global.showToast("全局壁纸已更新", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handleGlobalAvatarFile(target, fileList) {
      const file = Array.from(fileList || [])[0];
      if (!file) return;

      const draftCharacterName = this.globalCharacterName;
      const draftUserName = this.globalUserName;
      this.isActionLoading = true;
      try {
        const res = await importGlobalBeautifyAvatar(file, target);
        if (!res?.success) {
          throw new Error(res?.error || "上传全局头像失败");
        }
        const currentSettings = this.$store.global.beautifyGlobalSettings || {};
        const currentIdentities = currentSettings.identities || {};
        this.$store.global.beautifyGlobalSettings = {
          ...currentSettings,
          identities: {
            ...currentIdentities,
            [target]: {
              ...(currentIdentities[target] || {}),
              ...(res.identity || {}),
            },
          },
        };
        this.globalCharacterName = draftCharacterName;
        this.globalUserName = draftUserName;
        this.$store.global.showToast("全局头像已更新", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async handlePackageAvatarFile(target, fileList) {
      const file = Array.from(fileList || [])[0];
      if (!file || !this.selectedPackageId) {
        this.$store.global.showToast("请先选择一个美化包后再上传头像", 2400);
        return;
      }

      const draftCharacterName = this.packageCharacterName;
      const draftUserName = this.packageUserName;
      this.isActionLoading = true;
      try {
        const res = await importBeautifyPackageAvatar(
          file,
          this.selectedPackageId,
          target,
        );
        if (!res?.success) {
          throw new Error(res?.error || "上传包头像失败");
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        this.packageCharacterName = draftCharacterName;
        this.packageUserName = draftUserName;
        this.$store.global.showToast("包级头像已更新", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async saveGlobalSettings() {
      this.isActionLoading = true;
      try {
        const res = await updateBeautifySettings({
          character_name: this.globalCharacterName,
          user_name: this.globalUserName,
        });
        if (!res?.success) {
          throw new Error(res?.error || "保存全局设置失败");
        }
        this.$store.global.beautifyGlobalSettings = res.item || null;
        this.syncGlobalSettingsFields();
        this.$store.global.showToast("全局设置已保存", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async savePackageIdentityOverrides() {
      if (!this.selectedPackageId) return;

      this.isActionLoading = true;
      try {
        const res = await updateBeautifyPackageIdentities({
          package_id: this.selectedPackageId,
          character_name: this.packageCharacterName,
          user_name: this.packageUserName,
        });
        if (!res?.success) {
          throw new Error(res?.error || "保存包级资料失败");
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        this.$store.global.showToast("包级资料已保存", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async clearGlobalWallpaper() {
      this.isActionLoading = true;
      try {
        const res = await updateBeautifySettings({ clear_wallpaper: true });
        if (!res?.success) {
          throw new Error(res?.error || "清除全局壁纸失败");
        }
        this.$store.global.beautifyGlobalSettings = res.item || null;
        this.syncGlobalSettingsFields();
        this.$store.global.showToast("全局壁纸已清除", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async clearGlobalCharacterAvatar() {
      this.isActionLoading = true;
      try {
        const res = await updateBeautifySettings({
          clear_character_avatar: true,
        });
        if (!res?.success) {
          throw new Error(res?.error || "清除角色头像失败");
        }
        this.$store.global.beautifyGlobalSettings = res.item || null;
        this.syncGlobalSettingsFields();
        this.$store.global.showToast("角色头像已清除", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async clearGlobalUserAvatar() {
      this.isActionLoading = true;
      try {
        const res = await updateBeautifySettings({ clear_user_avatar: true });
        if (!res?.success) {
          throw new Error(res?.error || "清除用户头像失败");
        }
        this.$store.global.beautifyGlobalSettings = res.item || null;
        this.syncGlobalSettingsFields();
        this.$store.global.showToast("用户头像已清除", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async clearPackageCharacterAvatar() {
      if (!this.selectedPackageId) return;

      this.isActionLoading = true;
      try {
        const res = await updateBeautifyPackageIdentities({
          package_id: this.selectedPackageId,
          clear_character_avatar: true,
        });
        if (!res?.success) {
          throw new Error(res?.error || "清除角色头像失败");
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        this.$store.global.showToast("包级角色头像已清除", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async clearPackageUserAvatar() {
      if (!this.selectedPackageId) return;

      this.isActionLoading = true;
      try {
        const res = await updateBeautifyPackageIdentities({
          package_id: this.selectedPackageId,
          clear_user_avatar: true,
        });
        if (!res?.success) {
          throw new Error(res?.error || "清除用户头像失败");
        }
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
        });
        this.$store.global.showToast("包级用户头像已清除", 2200);
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async updateCurrentVariantPlatform(platform) {
      if (!this.selectedPackageId || !this.selectedVariantId) return;
      this.isActionLoading = true;
      try {
        const variantId = this.selectedVariantId;
        const res = await updateBeautifyVariant({
          package_id: this.selectedPackageId,
          variant_id: variantId,
          platform,
        });
        if (!res?.success) {
          throw new Error(res?.error || "更新端类型失败");
        }
        this.refreshVariantSelectionForPlatformChange(variantId, platform);
        await this.selectPackage(this.selectedPackageId, {
          preserveSelection: true,
          preferCompatibleSelection: true,
        });
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    async removeCurrentPackage() {
      if (!this.selectedPackageId) return;
      if (!confirm("确定删除当前美化包吗？库内主题和壁纸会一起移除。")) return;
      const removedPackageId = this.selectedPackageId;
      this.isActionLoading = true;
      try {
        const res = await deleteBeautifyPackage(removedPackageId);
        if (!res?.success) {
          throw new Error(res?.error || "删除失败");
        }
        this.prunePackageSharedWallpapersFromStore(removedPackageId);
        if (this.mobileFullscreenOpen) {
          this.closeMobilePreviewAndReset();
        } else {
          this.closeMobileFullscreen();
        }
        this.selectedPackageId = "";
        this.$store.global.beautifyActiveDetail = null;
        this.$store.global.beautifyActiveVariant = null;
        this.$store.global.beautifyActiveWallpaper = null;
        await this.fetchPackages();
      } catch (error) {
        this.$store.global.showToast(String(error.message || error), 3200);
      } finally {
        this.isActionLoading = false;
      }
    },

    wallpaperPreviewUrl(relativePath) {
      return buildBeautifyPreviewAssetUrl(relativePath);
    },

    supportsPlatform(item, platform) {
      return (
        (item?.platforms || []).includes(platform) ||
        (item?.platforms || []).includes("dual")
      );
    },

    ensureSelectedPackageStillVisible() {
      const stillVisible = this.filteredPackages.some(
        (item) => item.id === this.selectedPackageId,
      );
      if (!stillVisible && this.filteredPackages.length) {
        this.selectPackage(this.filteredPackages[0].id);
      }
    },
  };
}
