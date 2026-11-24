from test_detail_modal_advanced_editor_contracts import run_detail_modal_runtime_check
from pathlib import Path
import subprocess
import pytest


def test_chat_management_request_ordering():
    result = subprocess.run(['node', 'tests/chat_list_requests_test.mjs'],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_field_draft_keeps_a_single_proxy_layer():
    """草稿追踪代理与 Alpine 响应式代理不能再互相包裹（详情页打开卡死回归）。"""
    result = subprocess.run(['node', 'tests/field_draft_proxy_layering_test.mjs'],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=60)
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
globalThis.__updateCard = async () => ({ success: false, status: 409, current_source_revision: '20:2' });
assert(!(await modal.saveChanges()), 'discarding the conflicting draft must not report a successful save');
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
modal.editingData.first_mes = 'temporary input';
modal.editingData.first_mes = '';
modal.editingData.char_name = 'temporary new name';
modal.editingData.char_name = 'Hero';
finish({ success: true, card: { id: 'hero.png', description: 'disk', ui_summary: 'disk-note',
  first_mes: 'new disk greeting', char_name: 'new disk name', source_revision: '20:2' } });
await loading;
assert(modal.editingData.description === (discard ? 'disk' : 'existing draft'), 'refresh must respect discard intent');
assert(modal.editingData.ui_summary === 'input after request' && modal.hasUnsavedChanges, 'new input must survive refresh');
assert(modal.editingData.first_mes === '' && modal.editingData.char_name === 'Hero',
  'edits reverted to the old baseline during this read must also survive');
modal.editingData.description = 'disk';
modal.editingData.ui_summary = 'disk-note';
assert(modal.hasUnsavedChanges, 'empty and reverted input must compare against the new disk baseline');
modal.editingData.first_mes = 'new disk greeting';
modal.editingData.char_name = 'new disk name';
assert(!modal.hasUnsavedChanges, 'retained drafts must compare against refreshed disk baselines');
""")


def test_first_detail_failure_stays_read_only_until_retry_establishes_draft():
    run_detail_modal_runtime_check("""
const assert = (value, message) => { if (!value) throw new Error(message); };
modal.$store = { global: { settingsForm: {}, loadTagViewPrefs: () => ({}), showToast() {} } };
let finish;
globalThis.__getCardDetail = () => new Promise(resolve => { finish = resolve; });
modal.openDetail({ id: 'a.png', filename: 'a.png', editOnOpen: true });
assert(!modal.hasDetailDraft && modal.detailLoading && !(await modal.saveChanges()), 'list projection is read-only');
finish({ success: false, msg: '读取失败' });
await new Promise(resolve => setTimeout(resolve, 0));
assert(modal.detailLoadError === '读取失败' && !modal.detailLoading && !modal.hasDetailDraft, 'failure stays locked');
const retry = modal.refreshActiveCardDetail('a.png');
assert(!modal.detailLoadError && modal.detailLoading && !(await modal.saveChanges()), 'retry stays locked');
finish({ success: true, card: { id: 'a.png', ui_summary: 'disk' } });
await retry;
assert(modal.hasDetailDraft && !modal.detailLoading && !modal.hasUnsavedChanges, 'editing needs a clean baseline');
modal.editingData.ui_summary = 'edited';
assert(modal.hasUnsavedChanges, 'the first edit after retry must be tracked');
""")


def test_version_switch_protects_version_edits_up_to_the_response():
    run_detail_modal_runtime_check(SETUP + """
modal.showDetail = true;
modal.activeCard.versions = [{ id: 'second.png', filename: 'second.png' }];
const second = { success: true, card: { id: 'second.png', description: 'second version' } };
let finish, calls = 0;
globalThis.__getCardDetail = () => new Promise(resolve => { calls++; finish = resolve; });
const decisions = [false, true, false, true];
globalThis.confirm = () => decisions.shift();
modal.editingData.ui_summary = 'first version note';
modal.editingData.source_link = 'shared draft';
await modal.switchVersion('second.png');
assert(!calls && modal.editingData.id === 'hero.png' && modal.hasUnsavedChanges, 'cancel keeps the old version');
const switching = modal.switchVersion('second.png');
modal.editingData.description = 'typed after discard confirmation';
finish(second);
await switching;
assert(modal.editingData.id === 'hero.png' && modal.editingData.description.includes('after discard'),
  'old confirmation must not discard later input');
const switchAgain = modal.switchVersion('second.png');
finish(second);
await switchAgain;
assert(!decisions.length && modal.editingData.id === 'second.png' && !modal.editingData.ui_summary,
  'explicit discard applies to the old version');
assert(modal.editingData.source_link === 'shared draft' && modal.hasUnsavedChanges, 'keep shared drafts');
""")


def test_selecting_current_bundle_version_cancels_an_older_switch_only():
    run_detail_modal_runtime_check(SETUP + """
modal.showDetail = true;
modal.activeCard.versions = [{id:'hero.png'}, {id:'second.png'}];
let finish;
globalThis.__getCardDetail = () => new Promise(resolve => { finish = resolve; });
const editorToken = modal.detailRequestToken;
const pending = modal.switchVersion('second.png');
await modal.switchVersion('hero.png');
finish({ success:true, card:{id:'second.png'} });
await pending;
assert(modal.editingData.id === 'hero.png' && modal.detailRequestToken === editorToken,
  'returning to the displayed version must supersede the pending switch without invalidating this editor');
""")


@pytest.mark.parametrize('choose_current', [False, True])
def test_setting_bundle_cover_keeps_current_file_until_editor_switch(choose_current):
    run_detail_modal_runtime_check(SETUP + f"const currentCover = {str(choose_current).lower()};" + """
const a = {id:'bundle/a.png',filename:'a.png',image_url:'a-image',source_revision:'10:1'};
const b = {id:'bundle/b.png',filename:'b.png',image_url:'b-image',source_revision:'20:3'};
const cover = currentCover ? {...a,source_revision:'30:2'} : b;
const oldLeader = currentCover ? b.id : a.id;
const versions = [a,b];
modal.showDetail = true;
modal.activeCard = {...a,id:oldLeader,is_bundle:true,bundle_dir:'bundle',versions};
modal.editingData = modal._normalizeEditingDataShape(a);
modal.originalDataJson = JSON.stringify(modal.editingData);
modal.editingRevision = a.source_revision;
modal.editingData.description = 'pending body';
const decisions = currentCover ? [true] : [true,false];
globalThis.confirm = () => decisions.shift();
globalThis.__setAsBundleCover = async () => ({success:true,new_image_url:'cover-image',
  updated_card:{...cover,versions,is_bundle:true,bundle_dir:'bundle',resource_folder:'shared'}});
let publication;
window.dispatchEvent = event => {
  if (event.type === 'card-updated') { publication=event.detail;modal._absorbExternalCardUpdate(publication); }
};
await modal.setAsBundleCover(cover.id);
assert(!decisions.length && publication.id === cover.id && publication._old_id === oldLeader,
  'publish the actual cover to the list');
assert(modal.editingData.id === a.id && modal.activeCard.id === cover.id && modal.activeCard.versions.length === 2,
  'list identity and selected file must remain independent');
assert(modal.activeCard.image_url === (currentCover ? 'cover-image' : 'a-image'), 'show the selected version cover');
assert(modal.editingData.resource_folder === 'shared', 'the shared folder can update for both versions');
let payload;
globalThis.__updateCard = async data => { payload=data;return {success:false}; };
await modal.saveChanges();
assert(payload.id === a.id && payload.new_filename === a.filename && payload.description === 'pending body'
  && payload.source_revision === (currentCover ? cover.source_revision : a.source_revision),
  'next save must carry the filename and disk revision for the selected version');
""")


@pytest.mark.parametrize('refresh_first', [False, True])
def test_detail_refresh_and_save_share_one_post_save_read(refresh_first):
    run_detail_modal_runtime_check(SETUP.replace(
        'modal.refreshActiveCardDetail = () => { refreshes++; };', '')
        + f"const refreshFirst = {str(refresh_first).lower()};" + """
modal.showDetail = true;
modal.ensureVisibleDetailTab = () => {};
modal.startAutoSave = () => {};
modal.editingData.ui_summary = 'submit';
let loads=[], finishSave;
globalThis.__getCardDetail = () => new Promise(resolve => loads.push(resolve));
globalThis.__updateCard = () => new Promise(resolve => { finishSave = resolve; });
const oldLoad = refreshFirst && modal.refreshActiveCardDetail('hero.png');
const saving = modal.saveChanges();
modal.editingData.ui_summary = 'typed during save';
const retry = modal.refreshActiveCardDetail('hero.png');
const tagsDeleted = modal.refreshActiveCardDetail('hero.png');
assert(modal.isSaving && loads.length === (refreshFirst ? 1 : 0), 'queue refreshes behind the active save');
if (refreshFirst) {
  loads.shift()({success:true,card:{id:'hero.png',ui_summary:'stale'}});
  await oldLoad;
  assert(modal.isSaving && modal.editingData.ui_summary === 'typed during save', 'never install an older response');
}
finishSave({success:true,canonical_ui:{id:'hero.png',ui_summary:'submit',source_revision:'20:2'}});
assert(await saving, 'save ack must reach the active draft');
assert(!modal.isSaving && loads.length === 1, 'unlock the editor and re-read disk once');
loads.shift()({success:true,card:{id:'hero.png',ui_summary:'submit',description:'updated elsewhere',source_revision:'20:2'}});
await Promise.all([retry,tagsDeleted]);
assert(modal.editingData.description === 'updated elsewhere' && modal.editingData.ui_summary === 'typed during save',
  'merge the refreshed disk state while retaining newer edits');
assert(modal.hasUnsavedChanges && modal.requestClose(), 'close is available after the save and refresh');
""")


@pytest.mark.parametrize('outcome', ['overwrite', 'discard', 'business_error', 'network_error'])
def test_refresh_waiters_follow_conflict_and_failure_reads(outcome):
    run_detail_modal_runtime_check(SETUP.replace(
        'modal.refreshActiveCardDetail = () => { refreshes++; };', '')
        + f"const outcome = '{outcome}';" + """
modal.ensureVisibleDetailTab = () => {};
modal.startAutoSave = () => {};
const reads = [], writes = [];
const turn = () => new Promise(resolve => setImmediate(resolve));
globalThis.__getCardDetail = id => new Promise(resolve => reads.push({id, resolve}));
globalThis.__updateCard = payload => new Promise((resolve, reject) => writes.push({payload, resolve, reject}));
globalThis.confirm = () => outcome === 'discard';
modal.editingData.ui_summary = 'my note';
const saving = modal.saveChanges();
let finished = 0;
const waitForDisk = () => modal.refreshActiveCardDetail('hero.png').then(loaded => {
  assert(loaded === true, 'the caller must receive the outcome of the actual disk read'); finished++;
});
const waiters = [waitForDisk(), waitForDisk()];
if (outcome === 'business_error') writes[0].resolve({success:false,msg:'offline'});
else if (outcome === 'network_error') writes[0].reject(new Error('disconnected'));
else writes[0].resolve({success:false,status:409,current_source_revision:'20:2'});
await turn();
if (outcome === 'overwrite') {
  assert(writes.length === 2 && writes[1].payload.source_revision === '20:2', 'retry with the latest disk revision');
  assert(modal.isSaving && !reads.length && !finished, 'retry still owns the original waiters and editor');
  waiters.push(waitForDisk());
  modal.editingData.ui_summary = 'typed during overwrite';
  writes[1].resolve({success:true,canonical_ui:{id:'hero.png',ui_summary:'my note',source_revision:'30:3'}});
  await turn();
} else if (outcome === 'discard') {
  assert(modal.isSaving && reads.length === 1 && !finished, 'the explicit reload owns the original read');
  waiters.push(waitForDisk());
}
assert(reads.length === 1 && reads[0].id === 'hero.png' && !finished, 'one read serves all callers after the writes');
modal.editingData.description = 'typed during read';
modal.editingData.scenario = 'a temporary scenario';
modal.editingData.scenario = '';
reads[0].resolve({success:true,card:{id:'hero.png',filename:'hero.png',char_name:'disk name',
  description:'disk body',scenario:'disk scenario',ui_summary:outcome === 'overwrite' ? 'my note' : 'disk note',source_revision:'30:3'}});
assert((await saving) === (outcome === 'overwrite'), 'only a successful write reports success');
await Promise.all(waiters);
assert(!modal.isSaving && reads.length === 1 && finished === waiters.length, 'all refreshes observe the shared result');
assert(modal.editingData.char_name === 'disk name' && modal.editingData.description === 'typed during read',
  'read disk fields while retaining edits since the GET');
assert(modal.editingData.ui_summary === (outcome === 'discard' ? 'disk note' :
  outcome === 'overwrite' ? 'typed during overwrite' : 'my note'), 'preserve drafts except on explicit discard');
modal.editingData.description = 'disk body';
modal.editingData.ui_summary = outcome === 'overwrite' ? 'my note' : 'disk note';
assert(modal.editingData.scenario === '' && modal.hasUnsavedChanges, 'clearing during reload must survive conflict resolution');
modal.editingData.scenario = 'disk scenario';
assert(!modal.hasUnsavedChanges, 'the new disk baseline must be usable after every outcome');
""")


def test_each_independent_save_can_overwrite_one_conflict():
    run_detail_modal_runtime_check(SETUP + """
const revisions = [];
globalThis.confirm = () => false;
globalThis.__updateCard = async payload => {
  revisions.push(payload.source_revision);
  const attempt = revisions.length;
  if (attempt % 2 === 1) return {success:false,status:409,current_source_revision:(10 + attempt) + ':1'};
  return {success:true,canonical_ui:{id:'hero.png',ui_summary:payload.ui_summary,source_revision:(10 + attempt) + ':1'}};
};
for (const note of ['first', 'second']) {
  modal.editingData.ui_summary = note;
  assert(await modal.saveChanges(), 'each independent save must be allowed its own retry');
}
assert(revisions.join(',') === '10:1,11:1,12:1,13:1', 'each conflict retries once with its own revision');
""")


@pytest.mark.parametrize('end', ['close_before_ack', 'open_before_ack', 'close_during_read', 'open_during_read'])
def test_queued_refresh_cannot_follow_a_closed_or_replaced_editor(end):
    run_detail_modal_runtime_check(SETUP.replace(
        'modal.refreshActiveCardDetail = () => { refreshes++; };', '')
        + f"const end = '{end}';" + """
modal.ensureVisibleDetailTab = () => {};
modal.startAutoSave = () => {};
modal.loadTagViewPrefs = () => {};
let reads = [], finishSave, toasts = [], alerts = [];
modal.$store.global.showToast = message => toasts.push(message);
globalThis.alert = message => alerts.push(message);
globalThis.__getCardDetail = id => new Promise(resolve => reads.push({id, resolve}));
globalThis.__updateCard = () => new Promise(resolve => { finishSave = resolve; });
modal.editingData.ui_summary = 'old editor draft';
const saving = modal.saveChanges();
const queued = modal.refreshActiveCardDetail('hero.png');
const failure = {success:false,msg:'write failed'};
if (end.endsWith('during_read')) {
  finishSave(failure); await saving;
  assert(reads.length === 1, 'failed write must schedule the pending refresh');
}
if (end.startsWith('close')) modal.showDetail = false;
else modal.openDetail({id:'other.png',filename:'other.png'});
if (end.endsWith('before_ack')) {
  finishSave(failure); await saving;
  assert(!reads.some(read => read.id === 'hero.png') && !alerts.length, 'disregard old write failures and queued reads');
} else reads.find(read => read.id === 'hero.png').resolve({success:true,card:{id:'hero.png',ui_summary:'stale disk'}});
assert(!(await queued), 'a stale request must not report a completed refresh');
if (end.startsWith('open')) {
  reads.find(read => read.id === 'other.png').resolve({success:true,card:{id:'other.png',ui_summary:'new editor'}});
  await new Promise(resolve => setImmediate(resolve));
  assert(modal.editingData.id === 'other.png' && modal.editingData.ui_summary === 'new editor',
    'the old save and refresh must not affect the replacement editor');
} else assert(modal.editingData.ui_summary === 'old editor draft', 'closing cancels the old read');
assert(!toasts.length, 'the old operation must not report a result in a later editor');
""")
