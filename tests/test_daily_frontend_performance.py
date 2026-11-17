from test_detail_modal_advanced_editor_contracts import run_detail_modal_runtime_check
from pathlib import Path
import subprocess
import pytest


def test_chat_management_request_ordering():
    result = subprocess.run(['node', 'tests/chat_list_requests_test.mjs'],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


SETUP = """
const assert = (value, message) => { if (!value) throw new Error(message); };
modal.$store = { global: { showToast() {}, setTagTaxonomy() {} } };
modal.activeCard = { id: 'hero.png', filename: 'hero.png', is_bundle: false };
modal.editingData = modal._normalizeEditingDataShape({
  id: 'hero.png', filename: 'hero.png', char_name: 'Hero', ui_summary: 'original',
  source_link: 'keep', resource_folder: 'assets', source_revision: '10:1',
  character_book: { entries: [{ content: 'worldbook' }] },
});
modal.originalDataJson = JSON.stringify(modal.editingData);
let refreshes = 0;
modal.refreshActiveCardDetail = () => { refreshes++; };
"""


def test_note_save_preserves_new_input_and_never_cleans_or_refreshes():
    run_detail_modal_runtime_check(SETUP + """
let resolveSave;
let submitted;
globalThis.__updateCard = payload => {
  submitted = payload;
  return new Promise(resolve => { resolveSave = resolve; });
};
modal.editingData.ui_summary = 'submitted';
const saving = modal.saveChanges();
assert(submitted.ui_only && submitted.ui_summary === 'submitted', 'must send a narrow patch');
assert(!('description' in submitted) && !('resource_folder' in submitted), 'must omit unchanged fields');
modal.editingData.ui_summary = 'newer draft';
resolveSave({ success: true, file_modified: false, new_id: 'hero.png', new_filename: 'hero.png',
  canonical_ui: { id: 'hero.png', ui_summary: 'submitted', source_revision: '10:1' },
  updated_card: { id: 'hero.png', ui_summary: 'submitted' } });
assert(await saving, 'save must succeed');
assert(modal.editingData.ui_summary === 'newer draft' && modal.hasUnsavedChanges, 'must retain newer input');
assert(!globalThis.__cleanCalls && !refreshes, 'note save must avoid cleaning and detail requests');
modal.editingData.ui_summary = 'submitted';
assert(!modal.hasUnsavedChanges, 'submitted value must be the new disk baseline');
modal.editingData.ui_summary = 'dirty';
globalThis.confirm = () => false;
assert(modal.requestClose() === false, 'close must still confirm unsaved drafts');
modal.editingData.ui_summary = 'submitted';
assert(!modal.hasUnsavedChanges, 'revert must restore synced state');
""")


def test_dirty_checks_and_direct_persistence_rebase_touch_only_changed_fields():
    run_detail_modal_runtime_check(SETUP + """
modal.editingData.character_book.entries[0].content = 'edited';
assert(modal.hasUnsavedChanges, 'nested edits must be tracked');
modal.editingData.character_book.entries[0].content = 'worldbook';
assert(!modal.hasUnsavedChanges, 'reverting nested edits must clear dirty state');
modal.editingData.ui_summary = 'draft';
modal.editingData.resource_folder = 'persisted-folder';
modal._syncPersistedBaseline(['resource_folder']);
assert(modal.hasUnsavedChanges, 'direct persistence must retain other drafts');
modal.editingData.ui_summary = 'original';
assert(!modal.hasUnsavedChanges, 'only the direct persisted field baseline must change');
const rawBook = { entries: [{ content: 'large untouched book' }] };
modal.editingData.character_book = rawBook;
modal._syncPersistedBaseline(['character_book']);
assert(!modal.hasUnsavedChanges, 'persisted nested boundary must be clean');
rawBook.toJSON = () => { throw new Error('dirty note check traversed an untouched worldbook'); };
modal.editingData.ui_summary = 'note';
assert(modal.hasUnsavedChanges, 'note should be dirty without reading worldbook');
modal.editingData.ui_summary = 'original';
assert(!modal.hasUnsavedChanges, 'note revert should not read worldbook');
""")


def test_failed_save_retains_draft_and_old_version_response_cannot_modify_new_editor():
    run_detail_modal_runtime_check(SETUP + """
globalThis.__updateCard = async () => ({ success: false, msg: 'temporary failure' });
modal.editingData.ui_summary = 'keep draft';
assert(!(await modal.saveChanges()) && modal.hasUnsavedChanges, 'failure must preserve draft');
let finish;
globalThis.__updateCard = () => new Promise(resolve => { finish = resolve; });
const saving = modal.saveChanges();
modal.detailRequestToken++;
modal.editingData = modal._normalizeEditingDataShape({ id: 'other.png', ui_summary: 'other' });
modal.originalDataJson = JSON.stringify(modal.editingData);
finish({ success: true, canonical_ui: { ui_summary: 'keep draft' } });
assert(!(await saving), 'response for old editor must be ignored');
assert(modal.editingData.ui_summary === 'other', 'old response must not cross versions');
""")


def test_detail_chats_are_lazy_and_identical_inflight_queries_coalesce():
    run_detail_modal_runtime_check(SETUP + """
let calls = 0;
let finish;
globalThis.__listChats = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
modal.loadTagViewPrefs = () => {};
modal._cleanupPendingAdvancedEditorHandlers = () => {};
modal.endBasicSplitResize = () => {};
modal.resetPersonaFieldState = () => {};
modal.openDetail({ id: 'hero.png', filename: 'hero.png' });
assert(calls === 0 && refreshes === 1, 'opening detail must not query chats');
modal.selectDetailTab('chats');
const pending = modal.fetchCardChats('hero.png');
assert(calls === 1, 'same inflight request must coalesce');
finish({ success: true, items: [{ id: 'chat' }] });
await pending;
assert(modal.cardChats[0].id === 'chat', 'chat response must populate the panel');
await modal.fetchCardChats('hero.png');
assert(calls === 1, 'same resolved query must be reused until invalidated');
""")


@pytest.mark.parametrize('continued_edit', [False, True])
def test_source_side_effects_rebase_fields_and_preserve_newer_input(continued_edit):
    run_detail_modal_runtime_check(SETUP + f"const continuedEdit = {str(continued_edit).lower()};" + """
modal.editingData.tags = ['old-tag'];
modal.editingData.creator = 'old-author';
modal._syncPersistedBaseline(['tags', 'creator']);
let rebase;
globalThis.__rebaseBaseline = (data, fields, canonical) => { rebase = { fields, canonical }; };
let finish;
globalThis.__updateCard = () => new Promise(resolve => { finish = resolve; });
modal.editingData.source_link = 'new-link';
const saving = modal.saveChanges();
if (continuedEdit) {
  modal.editingData.tags.push('newer-tag-draft');
  modal.editingData.creator = 'newer-author-draft';
}
finish({ success: true, new_id: 'hero.png', new_filename: 'hero.png',
  canonical_ui: { id: 'hero.png', source_link: 'new-link', source_revision: '20:2' },
  canonical_fields: { tags: ['fetched-tag'], creator: 'fetched-author' },
  updated_card: { id: 'hero.png', tags: ['fetched-tag'], creator: 'fetched-author', source_revision: '20:2' } });
assert(await saving, 'link save must succeed');
assert(rebase.fields.includes('tags') && rebase.fields.includes('creator'), 'snapshot baseline must include source side effects');
assert(rebase.canonical.tags[0] === 'fetched-tag' && rebase.canonical.creator === 'fetched-author',
  'snapshot baseline must represent server values even while newer input remains in the editor');
if (continuedEdit) {
  assert(modal.editingData.tags[1] === 'newer-tag-draft', 'newer nested edits must survive canonical tags');
  assert(modal.editingData.creator === 'newer-author-draft', 'newer author edit must survive');
  assert(modal.hasUnsavedChanges, 'newer input remains dirty');
  modal.editingData.tags = ['fetched-tag'];
  modal.editingData.creator = 'fetched-author';
}
assert(modal.editingData.tags[0] === 'fetched-tag' && modal.editingData.creator === 'fetched-author',
  'server side effects must be absorbed in the editor');
assert(!modal.hasUnsavedChanges && !refreshes, 'canonical fields must rebase without requesting detail');
modal.editingData.description = 'next body edit';
let submitted;
globalThis.__updateCard = async payload => { submitted = payload; return { success: false }; };
await modal.saveChanges();
assert(submitted.tags[0] === 'fetched-tag' && submitted.creator === 'fetched-author',
  'next full save must not replay values from before source actions');
assert(submitted.source_revision === '20:2', 'next full save uses the matching revision');
""")


def test_nonleader_save_does_not_absorb_leader_body_fields():
    run_detail_modal_runtime_check(SETUP + """
modal.activeCard = { id: 'bundle/main.png', is_bundle: true, bundle_dir: 'bundle' };
modal.editingData.id = 'bundle/old.png';
modal.editingData.tags = ['old-version-tag'];
modal.editingData.creator = 'old-version-author';
modal._syncPersistedBaseline(['tags', 'creator']);
modal.editingData.source_link = 'new-link';
globalThis.__updateCard = async () => ({ success: true, new_id: 'bundle/main.png',
  canonical_ui: { id: 'bundle/old.png', source_link: 'new-link', source_revision: '10:1' },
  canonical_fields: { tags: ['leader-tag'], creator: 'leader-author' },
  updated_card: { id: 'bundle/main.png', tags: ['leader-tag'], creator: 'leader-author' } });
assert(await modal.saveChanges(), 'nonleader UI save must succeed');
assert(modal.editingData.tags[0] === 'old-version-tag' && modal.editingData.creator === 'old-version-author',
  'leader fields must not enter the nonleader editor');
assert(!modal.hasUnsavedChanges, 'nonleader save must leave a clean target baseline');
""")


def test_note_save_does_not_treat_cached_body_projection_as_canonical():
    run_detail_modal_runtime_check(SETUP + """
modal.editingData.description = 'fresh detail content';
modal.editingData.creator = 'fresh detail author';
modal._syncPersistedBaseline(['description', 'creator']);
modal.editingData.ui_summary = 'new note';
globalThis.__updateCard = async () => ({ success: true, new_id: 'hero.png', new_filename: 'hero.png',
  canonical_ui: { id: 'hero.png', ui_summary: 'new note', source_revision: '10:1' }, canonical_fields: {},
  updated_card: { id: 'hero.png', description: 'older list projection', creator: 'older author' } });
assert(await modal.saveChanges(), 'note save must succeed');
assert(modal.editingData.description === 'fresh detail content' && modal.editingData.creator === 'fresh detail author',
  'unchanged body projection must not replace newer loaded detail');
assert(!modal.hasUnsavedChanges, 'note save must preserve clean body baselines');
""")


def test_explicit_conflict_discard_reloads_real_fields_and_baseline():
    run_detail_modal_runtime_check(SETUP.replace(
        'modal.refreshActiveCardDetail = () => { refreshes++; };', '') + """
modal.showDetail = true;
modal.ensureVisibleDetailTab = () => {};
modal.startAutoSave = () => {};
modal.editingData.description = 'discard draft';
modal.editingData.char_name = 'discard name';
modal.editingData.filename = 'discard-filename.png';
modal.editingData.character_book.entries[0].content = 'discard book draft';
globalThis.__getCardDetail = async () => ({ success: true, card: {
  id: 'hero.png', filename: 'hero.png', char_name: 'External name', description: 'external newer',
  source_revision: '20:2', character_book: null, extensions: {}, tags: ['external-tag'],
} });
globalThis.confirm = () => true;
await modal.handleSaveConflict({ status: 409, current_source_revision: '20:2' });
assert(modal.editingData.description === 'external newer', 'explicit discard must not resurrect the old draft');
assert(modal.editingData.char_name === 'External name' && modal.editingData.filename === 'hero.png',
  'discard must reload all file fields');
assert(!modal.editingData.character_book.entries.length, 'removed worldbook must not survive discard');
assert(modal.editingData.source_revision === '20:2' && !modal.hasUnsavedChanges,
  'external data and revision must establish the clean baseline together');
""")


@pytest.mark.parametrize('discard', [False, True])
def test_detail_refresh_preserves_input_typed_after_request(discard):
    run_detail_modal_runtime_check(SETUP.replace(
        'modal.refreshActiveCardDetail = () => { refreshes++; };', '')
        + f"const discard = {str(discard).lower()};" + """
modal.showDetail = true;
modal.ensureVisibleDetailTab = () => {};
modal.startAutoSave = () => {};
modal.editingData.description = 'existing draft';
let finish;
globalThis.__getCardDetail = () => new Promise(resolve => { finish = resolve; });
const loading = modal.refreshActiveCardDetail('hero.png', { preserveDraft: !discard });
modal.editingData.ui_summary = 'input after request';
finish({ success: true, card: { id: 'hero.png', description: 'disk', ui_summary: 'disk-note', source_revision: '20:2' } });
await loading;
assert(modal.editingData.description === (discard ? 'disk' : 'existing draft'), 'refresh must respect discard intent');
assert(modal.editingData.ui_summary === 'input after request' && modal.hasUnsavedChanges, 'new input must survive refresh');
modal.editingData.description = 'disk';
modal.editingData.ui_summary = 'disk-note';
assert(!modal.hasUnsavedChanges, 'retained drafts must compare against refreshed disk baselines');
""")
