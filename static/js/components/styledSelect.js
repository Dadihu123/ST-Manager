/**
 * Shared themed select behavior.
 *
 * The hidden native select remains the source of truth for Alpine bindings,
 * browser form events, and dynamically rendered options. This component only
 * supplies the themed trigger/listbox presentation.
 */
export default function styledSelect() {
  return {
    value: '',
    options: [],
    open: false,
    disabled: false,
    _optionsObserver: null,

    init() {
      this.syncOptions();
      this.syncExternalValue(this.$refs.source?.value ?? '');

      if (this.$refs.source && typeof MutationObserver !== 'undefined') {
        this._optionsObserver = new MutationObserver(() => this.syncOptions());
        this._optionsObserver.observe(this.$refs.source, {
          attributes: true,
          childList: true,
          characterData: true,
          subtree: true,
        });
      }
    },

    destroy() {
      this._optionsObserver?.disconnect();
      this._optionsObserver = null;
    },

    syncOptions() {
      const source = this.$refs.source;
      if (!source) return;

      this.options = Array.from(source.options).map((option, index, allOptions) => {
        const group = option.parentElement?.tagName === 'OPTGROUP'
          ? option.parentElement
          : null;
        const previousOption = allOptions[index - 1];
        const previousGroup = previousOption?.parentElement?.tagName === 'OPTGROUP'
          ? previousOption.parentElement
          : null;
        const groupLabel = group?.label?.trim() || '';

        return {
          key: `${option.value}-${index}`,
          value: String(option.value),
          label: option.textContent.trim(),
          disabled: option.disabled,
          hidden: option.hidden,
          groupLabel,
          groupStart: Boolean(groupLabel && group !== previousGroup),
        };
      });
      this.disabled = source.disabled;
    },

    syncExternalValue(nextValue) {
      const normalizedValue = nextValue == null ? '' : String(nextValue);
      if (this.value !== normalizedValue) this.value = normalizedValue;
      if (this.$refs.source && this.$refs.source.value !== normalizedValue) {
        this.$refs.source.value = normalizedValue;
      }
      this.disabled = Boolean(this.$refs.source?.disabled);
    },

    selectedOptionLabel() {
      const selected = this.options.find(
        (option) => String(this.value) === option.value && !option.hidden,
      );
      return selected?.label || this.$refs.source?.selectedOptions?.[0]?.textContent?.trim() || '请选择';
    },

    toggle() {
      if (this.disabled) return;
      if (this.open) {
        this.closeMenu();
      } else {
        this.openMenu();
      }
    },

    openMenu() {
      if (this.disabled) return;
      this.syncOptions();
      this.open = true;
      this.$nextTick(() => {
        const selected = this.$refs.menu?.querySelector('[aria-selected="true"]');
        const first = this.$refs.menu?.querySelector('button:not([disabled])');
        (selected || first)?.focus();
      });
    },

    closeMenu(focusTrigger = false) {
      if (!this.open) return;
      this.open = false;
      if (focusTrigger) this.$nextTick(() => this.$refs.trigger?.focus());
    },

    selectOption(option, dispatch = true) {
      if (!option || option.disabled || this.disabled) return;
      this.value = option.value;
      this.open = false;

      const source = this.$refs.source;
      if (source) {
        source.value = option.value;
        if (dispatch) {
          source.dispatchEvent(new Event('input', { bubbles: true }));
          source.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }

      this.$nextTick(() => this.$refs.trigger?.focus());
    },

    visibleOptionButtons() {
      return Array.from(this.$refs.menu?.querySelectorAll('button[role="option"]') || [])
        .filter((button) => !button.disabled && button.offsetParent !== null);
    },

    moveOption(event, direction) {
      const buttons = this.visibleOptionButtons();
      if (!buttons.length) return;
      const currentIndex = buttons.indexOf(event.currentTarget);
      const nextIndex = Math.max(
        0,
        Math.min(buttons.length - 1, currentIndex + direction),
      );
      buttons[nextIndex]?.focus();
    },

    focusOption(index) {
      const buttons = this.visibleOptionButtons();
      if (!buttons.length) return;
      buttons[Math.max(0, Math.min(buttons.length - 1, index))]?.focus();
    },
  };
}
