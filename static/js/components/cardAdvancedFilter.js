/**
 * static/js/components/cardAdvancedFilter.js
 * 角色卡高级筛选抽屉组件
 */

export default function cardAdvancedFilter() {
  return {
    get showCardAdvancedFilterDrawer() {
      return this.$store.global.showCardAdvancedFilterDrawer;
    },

    get cardAdvancedFilterDraft() {
      return (
        this.$store.global.cardAdvancedFilterDraft ||
        this.$store.global.getDefaultCardAdvancedFilterDraft()
      );
    },

    get draft() {
      return this.cardAdvancedFilterDraft;
    },

    get activeSection() {
      return this.$store.global.cardAdvancedFilterActiveSection || "basic";
    },

    get validationMessage() {
      return (
        this.$store.global.cardAdvancedFilterValidationState?.message || ""
      );
    },

    get statItems() {
      return this.$store.global.getCardAdvancedFilterStatItems();
    },

    get isCardsMode() {
      return this.$store.global.currentMode === "cards";
    },

    get cardAdvancedFilterCount() {
      return this.$store.global.getCardAdvancedFilterCount();
    },

    get sectionItems() {
      return [
        {
          key: "basic",
          label: "基础筛选",
          active: true,
        },
        {
          key: "time",
          label: "时间筛选",
          active: !!(
            this.draft.importDateFrom ||
            this.draft.importDateTo ||
            this.draft.modifiedDateFrom ||
            this.draft.modifiedDateTo
          ),
        },
        {
          key: "numeric",
          label: "数值筛选",
          active: this.draft.tokenMin !== "" || this.draft.tokenMax !== "",
        },
        {
          key: "tags",
          label: "标签条件",
          active: this.tagIncludeCount > 0 || this.tagExcludeCount > 0,
        },
      ];
    },

    get tagIncludeCount() {
      return Array.isArray(this.$store.global.viewState.filterTags)
        ? this.$store.global.viewState.filterTags.length
        : 0;
    },

    get tagExcludeCount() {
      return Array.isArray(this.$store.global.viewState.excludedTags)
        ? this.$store.global.viewState.excludedTags.length
        : 0;
    },

    get tagSummary() {
      if (!this.tagIncludeCount && !this.tagExcludeCount) {
        return "当前未设置标签条件";
      }

      const summaryParts = [];

      if (this.tagIncludeCount) {
        summaryParts.push(`包含 ${this.tagIncludeCount} 个标签`);
      }

      if (this.tagExcludeCount) {
        summaryParts.push(`排除 ${this.tagExcludeCount} 个标签`);
      }

      return summaryParts.join("，");
    },

    requestClose() {
      this.$store.global.closeCardAdvancedFilterDrawer();
    },

    clearDraft() {
      this.$store.global.clearCardAdvancedFilterDraft();
    },

    clearTagFilters() {
      this.$store.global.viewState.filterTags = [];
      this.$store.global.viewState.excludedTags = [];
      this.syncValidationState();
      window.dispatchEvent(new CustomEvent("refresh-card-list"));
    },

    setSection(section) {
      this.$store.global.setCardAdvancedFilterSection(section);
    },

    isSectionActive(section) {
      return this.activeSection === section;
    },

    applyFilters() {
      const result = this.$store.global.applyCardAdvancedFilterDraft();
      if (result && result.success === false && result.section) {
        this.$store.global.setCardAdvancedFilterSection(result.section);
      }
    },

    syncValidationState() {
      this.$store.global.syncCardAdvancedFilterValidationState();
    },

    handleRecursiveFilterChange(event) {
      if (!event?.target?.checked || this.draft.recursiveFilter !== true) {
        this.draft.allDirsOnlyWithFilters = false;
      }
      this.syncValidationState();
    },

    setCardAdvancedFilterTagEditSource(source) {
      this.$store.global.setCardAdvancedFilterTagEditSource(source);
    },

    openTagFilterEditor() {
      this.setCardAdvancedFilterTagEditSource("card-advanced-filter");
      this.$store.global.closeCardAdvancedFilterDrawer(false);
      window.dispatchEvent(new CustomEvent("open-tag-filter-modal"));
    },
  };
}
