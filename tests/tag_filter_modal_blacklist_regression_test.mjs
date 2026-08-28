import assert from "node:assert/strict";

import tagFilterModal from "../static/js/components/tagFilterModal.js";

function createComponent(overrides = {}) {
  const component = tagFilterModal();
  const toasts = [];

  Object.assign(component, {
    $store: {
      global: {
        settingsForm: {
          automation_slash_is_tag_separator: false,
        },
        showToast(message, duration) {
          toasts.push({ message, duration });
        },
      },
    },
  });

  Object.assign(component, overrides);
  return { component, toasts };
}

async function testDuplicateOnlyDeleteModeAddPreservesSelection() {
  const { component, toasts } = createComponent({
    tagBlacklistTags: ["alpha"],
    tagBlacklistInput: "alpha",
    selectedTagsForDeletion: ["alpha"],
    saveTagManagementPrefsState() {
      throw new Error("save should not run for duplicate-only path");
    },
  });

  const result = await component.addDeleteSelectionToBlacklist();

  assert.equal(result, false);
  assert.deepEqual(component.selectedTagsForDeletion, ["alpha"]);
  assert.deepEqual(component.tagBlacklistTags, ["alpha"]);
  assert.equal(component.tagBlacklistInput, "alpha");
  assert.equal(toasts.at(-1)?.message, "所选标签已在黑名单中");
}

async function testFailedPersistenceDoesNotLeaveOptimisticBlacklistState() {
  const { component } = createComponent({
    tagBlacklistTags: ["alpha"],
    tagBlacklistInput: "alpha",
    saveTagManagementPrefsState() {
      return Promise.resolve(null);
    },
  });

  const result = await component.mergeTagsIntoBlacklist(["beta"]);

  assert.equal(result, false);
  assert.deepEqual(component.tagBlacklistTags, ["alpha"]);
  assert.equal(component.tagBlacklistInput, "alpha");
}

async function testSuccessfulDeleteModeAddUpdatesBlacklistAndClearsSelection() {
  const { component, toasts } = createComponent({
    tagBlacklistTags: ["alpha"],
    tagBlacklistInput: "alpha",
    selectedTagsForDeletion: ["beta"],
    saveTagManagementPrefsState() {
      this.tagBlacklistTags = ["alpha", "beta"];
      this.tagBlacklistInput = "alpha, beta";
      return Promise.resolve({
        lock_tag_library: false,
        tag_blacklist: ["alpha", "beta"],
      });
    },
  });

  const result = await component.addDeleteSelectionToBlacklist();

  assert.equal(result, true);
  assert.deepEqual(component.tagBlacklistTags, ["alpha", "beta"]);
  assert.equal(component.tagBlacklistInput, "alpha, beta");
  assert.deepEqual(component.selectedTagsForDeletion, []);
  assert.equal(toasts.at(-1)?.message, "已将 1 个待删除标签加入黑名单");
}

await testDuplicateOnlyDeleteModeAddPreservesSelection();
await testFailedPersistenceDoesNotLeaveOptimisticBlacklistState();
await testSuccessfulDeleteModeAddUpdatesBlacklistAndClearsSelection();

console.log("tag_filter_modal_blacklist_regression_test: ok");
