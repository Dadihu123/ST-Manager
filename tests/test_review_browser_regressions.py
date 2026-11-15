"""真实 Chromium 的 history、组件关闭与 Blob 行为；未安装浏览器时跳过。"""

import functools
import http.server
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    playwright = pytest.importorskip('playwright.sync_api')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        ('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except playwright.Error as exc:
            server.shutdown()
            pytest.skip(f'Chromium 未安装: {exc}')
        tab = browser.new_page()
        tab.goto(f'http://127.0.0.1:{server.server_port}/')
        yield tab
        browser.close()
    server.shutdown()
    server.server_close()


def test_async_sentinel_cleanup_does_not_close_new_layer(page):
    page.evaluate("""async () => {
      const vs = await import('/static/js/utils/viewStack.js');
      vs.install();
      window.testState = {a: true, b: false, closed: []};
      const s = window.testState;
      vs.register({key:'a', isActive:()=>s.a, close:()=>{s.a=false; s.closed.push('a')}});
      vs.register({key:'b', isActive:()=>s.b, close:()=>{s.b=false; s.closed.push('b')}});
      vs.closeTop();
      s.b = true; vs.sync();
    }""")
    page.wait_for_function('history.state?.__viewStack && testState.b')
    page.wait_for_timeout(100)
    assert page.evaluate('testState.closed') == ['a']
    page.evaluate('history.back()')
    page.wait_for_function('!testState.b')
    assert page.evaluate('testState.closed') == ['a', 'b']


def test_native_back_does_not_create_history_entries(page):
    assert page.evaluate("""async () => {
      window.stmHost = {};
      const bridge = await import('/static/js/utils/hostBridge.js');
      const vs = await import('/static/js/utils/viewStack.js');
      bridge.installHostBridge({getMode:()=> 'cards'});
      const before = history.length;
      let open = true;
      vs.register({key:'a',isActive:()=>open,close:()=>open=false});
      window.__stmHostBack();
      return before === history.length && !open;
    }""")


def test_real_editors_keep_unsaved_changes_and_close_child_first(page):
    result = page.evaluate("""async () => {
      const layout = (await import('/static/js/components/layout.js')).default();
      const detail = (await import('/static/js/components/detailModal.js')).default();
      const wi = (await import('/static/js/components/wiEditor.js')).default();
      const preset = (await import('/static/js/components/presetEditor.js')).default();
      const components = {detailModal:detail, wiEditor:wi, presetEditor:preset};
      document.body.innerHTML = Object.keys(components).map(n=>`<div x-data="${n}"></div>`).join('');
      window.Alpine = {$data:el=>components[el.getAttribute('x-data')]};
      const global = {deviceType:'desktop',currentMode:'cards'};
      layout.$store = {global};
      Object.values(components).forEach(c=> c.$store = {global});
      Object.defineProperty(detail, 'hasUnsavedChanges', {get:()=>true});
      wi.hasEditorUnsavedChanges = ()=>true;
      Object.defineProperty(preset, 'isDirty', {get:()=>true});
      window.confirm = ()=>false;
      layout._installBackGestureSupport();
      detail.showDetail = true;
      window.__stmHostBack();
      const detailKept = detail.showDetail;
      detail.showDetail = false;
      wi.showFullScreenWI = true;
      wi.showHelpModal = true;
      window.__stmHostBack();
      const wiChildOnly = wi.showFullScreenWI && !wi.showHelpModal;
      window.__stmHostBack();
      const wiKept = wi.showFullScreenWI;
      wi.showFullScreenWI = false;
      preset.showPresetEditor = true;
      window.__stmHostBack();
      return {detailKept, wiChildOnly, wiKept, presetKept:preset.showPresetEditor};
    }""")
    assert all(result.values()), result


def test_native_blob_export_survives_immediate_revoke(page):
    page.evaluate("""async () => {
      window.saved = null;
      window.stmHost = {saveBase64File:(bytes,name,mime)=>{window.saved={bytes,name,mime};return true}};
      const dl = await import('/static/js/utils/download.js');
      dl.installNativeDownloads();
      const url = URL.createObjectURL(new Blob(['中文 export'],{type:'application/json'}));
      const link = document.createElement('a'); link.href=url; link.download='测试.json';
      document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    }""")
    page.wait_for_function('window.saved !== null')
    result = page.evaluate('saved')
    import base64
    assert base64.b64decode(result['bytes']).decode() == '中文 export'
    assert result['name'] == '测试.json'
    assert result['mime'] == 'application/json'


def test_private_resources_browse_inside_app_without_system_requests(page):
    result = page.evaluate("""async () => {
      const detail = (await import('/static/js/components/detailModal.js')).default();
      detail.$store = {global:{canOpenSystemFileManager:false}};
      detail.mobilePanel = 'image'; detail.tab = 'basic'; detail.mobileNavOpen = true;
      const chats = (await import('/static/js/components/chatGrid.js')).default();
      const rollback = (await import('/static/js/components/rollbackModal.js')).default();
      const settings = (await import('/static/js/components/settingsModal.js')).default();
      for (const component of [chats,rollback,settings]) component.$store = detail.$store;
      window.fetch = () => { throw new Error('no system-directory request allowed'); };
      detail.browseResourceFolder();
      detail.openResourceFolder(); detail.openCardLocation(); detail.openBackupFolder();
      chats.openChatFolder({file_path:'/data/private/chat.jsonl'});
      rollback.openBackupFolder(); settings.openTrashFolder(); settings.systemAction('open_folder');
      return {tab:detail.tab,panel:detail.mobilePanel,nav:detail.mobileNavOpen};
    }""")
    assert result == {'tab': 'resources', 'panel': 'content', 'nav': False}


def test_user_db_download_waits_for_native_completion_and_returns_filename(page):
    page.evaluate("""async () => {
      window.exportResult = null;
      window.stmHost = {saveBase64FileAsync:(id,bytes,name,mime)=>{window.saveRequest={id,bytes,name,mime}}};
      const api = await import('/static/js/api/system.js');
      window.fetch = async url => {
        if (url !== '/api/user-db-backup/export?download=1') throw new Error('expected download request');
        return new Response('{"schema_version":1}', {headers:{
          'Content-Type':'application/json', 'Content-Disposition':'attachment; filename="backup.json"'}});
      };
      api.exportUserDbBackup({download:true}).then(result=>window.exportResult=result);
    }""")
    page.wait_for_function('!!window.saveRequest')
    assert page.evaluate('exportResult') is None
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('host:download-result',
      {detail:{id:saveRequest.id,success:true}}))""")
    page.wait_for_function('!!window.exportResult')
    assert page.evaluate('exportResult') == {'success': True, 'file_name': 'backup.json'}


def test_long_press_preserves_editing_and_deduplicates_late_menu(page):
    page.evaluate("""async () => {
      window.matchMedia = () => ({matches:true});
      const lp = await import('/static/js/utils/longPress.js');
      lp.installLongPressContextMenu();
      document.body.innerHTML = '<div data-long-press-menu><textarea></textarea><span id="menu">card</span></div>';
      window.count = 0;
      const menu = document.querySelector('#menu');
      menu.addEventListener('contextmenu', e=>{count++;e.preventDefault()});
      window.touch = el=>el.dispatchEvent(new TouchEvent('touchstart', {
        bubbles:true, touches:[new Touch({identifier:1,target:el,clientX:123,clientY:234})]}));
      const input = document.querySelector('textarea');
      touch(input);
      window.inputPrevented = !input.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
      input.dispatchEvent(new TouchEvent('touchend',{bubbles:true}));
      touch(menu);
    }""")
    page.wait_for_function('count === 1')
    page.evaluate("""() => {
      const menu = document.querySelector('#menu');
      menu.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
      menu.dispatchEvent(new TouchEvent('touchend',{bubbles:true}));
      menu.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}));
    }""")
    assert page.evaluate('inputPrevented') is False
    assert page.evaluate('count') == 1


def test_cancelled_android_directory_authorization_prevents_save(page):
    result = page.evaluate("""async () => {
      const {authorizeAndroidDirectories} = await import('/static/js/utils/androidStorage.js');
      let saved = false;
      window.stmHost = {requestStorageAccess:(id, paths)=> {
        setTimeout(()=>window.dispatchEvent(new CustomEvent('host:storage-result',
          {detail:{id,success:false}})), 0);
      }};
      try { await authorizeAndroidDirectories({cards_dir:'/storage/emulated/0/cards'}); saved=true; }
      catch (error) { return !saved && error.message.includes('原配置已保留'); }
      return false;
    }""")
    assert result


@pytest.fixture
def chat_reader(page):
    page.evaluate("""async () => {
      window.stmHost = {};
      const layout = (await import('/static/js/components/layout.js')).default();
      const reader = (await import('/static/js/components/chatGrid.js')).default();
      const global = {deviceType:'mobile', currentMode:'chats', viewState:{}};
      layout.$store = reader.$store = {global};
      reader.$nextTick = callback => callback();
      document.body.innerHTML = '<div x-data="chatGrid"></div>';
      window.Alpine = {$data:() => reader};
      layout._installBackGestureSupport();
      reader.detailOpen = true;
      reader.activeChat = {id:'test-chat', messages:[]};
      window.reader = reader;
      window.readerGlobal = global;
    }""")
    return page


def test_chat_reader_back_cleans_up_before_leaving_chat_workspace(chat_reader):
    result = chat_reader.evaluate("""() => {
      const token = reader.readerPageRequestToken;
      reader.detailSearchQuery = 'unfinished search';
      reader.readerScrollIdleTimer = setTimeout(()=>{}, 10000);
      reader.bindPickerSearch = 'stale card';
      const depthBefore = window.__stmViewStack().depth;
      window.__stmHostBack();
      const closed = !reader.detailOpen && reader.activeChat === null &&
        reader.readerPageRequestToken === token + 1 && !reader.readerScrollIdleTimer &&
        !reader.detailSearchQuery && !reader.bindPickerSearch;
      const stayedInChats = readerGlobal.currentMode === 'chats';
      window.__stmHostBack();
      return {depthBefore, closed, stayedInChats, nextMode:readerGlobal.currentMode};
    }""")
    assert result == {'depthBefore': 1, 'closed': True, 'stayedInChats': True, 'nextMode': 'cards'}


@pytest.mark.parametrize('field,value,cleared_field', [
    ('readerViewSettingsOpen', True, 'readerViewSettingsOpen'),
    ('regexConfigOpen', True, 'regexConfigStatus'),
    ('regexHelpOpen', True, 'regexHelpOpen'),
    ('editingFloor', 2, 'editingMessageDraft'),
    ('bindPickerOpen', True, 'bindPickerSearch'),
    ('regexRulePickerOpen', True, 'regexRulePickerSearch'),
    ('regexPresetPickerOpen', True, 'regexPresetPickerSearch'),
    ('readerDeleteConfirmOpen', True, 'readerDeleteTarget'),
])
def test_chat_reader_back_closes_actual_child_and_clears_its_state(chat_reader, field, value, cleared_field):
    result = chat_reader.evaluate("""({field,value,cleared}) => {
      if (cleared !== field) reader[cleared] = 'stale child state';
      reader[field] = value;
      const before = window.__stmViewStack().depth;
      window.__stmHostBack();
      return {before, childClosed:!reader[field], cleaned:!reader[cleared],
        readerKept:reader.detailOpen, mode:readerGlobal.currentMode};
    }""", {'field': field, 'value': value, 'cleared': cleared_field})
    assert result == {'before': 2, 'childClosed': True, 'cleaned': True, 'readerKept': True, 'mode': 'chats'}


def test_chat_reader_children_follow_visual_priority_and_visibility(chat_reader):
    result = chat_reader.evaluate("""() => {
      reader.regexConfigOpen = reader.regexHelpOpen = reader.readerDeleteConfirmOpen = true;
      window.__stmHostBack();
      const confirmFirst = !reader.readerDeleteConfirmOpen && reader.regexHelpOpen && reader.regexConfigOpen;
      window.__stmHostBack();
      const helpSecond = !reader.regexHelpOpen && reader.regexConfigOpen && reader.detailOpen;
      readerGlobal.currentMode = 'cards';
      const hiddenIgnored = window.__stmViewStack().depth === 0 && !window.__stmHostBack();
      readerGlobal.currentMode = 'chats';
      reader.regexConfigOpen = false;
      reader.readerMobilePanel = 'search';
      window.__stmHostBack();
      const mobilePanelClosed = !reader.readerMobilePanel && reader.detailOpen;
      reader.readerMobilePanel = 'search';
      readerGlobal.deviceType = 'desktop';
      const desktopPanelIgnored = window.__stmViewStack().depth === 1;
      reader.detailOpen = false;
      reader.regexHelpOpen = true;
      return {confirmFirst, helpSecond, hiddenIgnored, mobilePanelClosed, desktopPanelIgnored,
        closedReaderChildrenIgnored:window.__stmViewStack().depth === 0};
    }""")
    assert all(result.values()), result


@pytest.fixture
def settings_modal(page):
    page.evaluate("""async () => {
      window.stmHost = {};
      const layout = (await import('/static/js/components/layout.js')).default();
      const settings = (await import('/static/js/components/settingsModal.js')).default();
      const global = {deviceType:'mobile',currentMode:'cards', showSettingsModal:false,
        settingsForm:{cards_dir:'data/library/characters'}, isDarkMode:true};
      layout.$store = settings.$store = {global};
      settings.$watch = () => {};
      settings.init();
      settings.openSettings();
      layout._installBackGestureSupport();
      window.settings = settings;
    }""")
    return page


def test_settings_back_dismisses_discard_confirmation_and_preserves_edits(settings_modal):
    result = settings_modal.evaluate("""() => {
      settings.settingsForm.cards_dir = '/storage/custom-cards';
      window.__stmHostBack();
      const prompted = settings.showDiscardConfirm && settings.showSettingsModal;
      window.__stmHostBack();
      return {prompted, dismissed:!settings.showDiscardConfirm, kept:settings.showSettingsModal,
        cards:settings.settingsForm.cards_dir, dirty:settings.isSettingsDirty};
    }""")
    assert result == {'prompted': True, 'dismissed': True, 'kept': True,
                      'cards': '/storage/custom-cards', 'dirty': True}


@pytest.mark.parametrize('child', ['showSettingsHelpModal', 'settingsNavOpen'])
def test_settings_back_closes_child_then_settings(settings_modal, child):
    result = settings_modal.evaluate("""child => {
      settings[child] = true;
      window.__stmHostBack();
      const childOnly = !settings[child] && settings.showSettingsModal;
      window.__stmHostBack();
      return childOnly && !settings.showSettingsModal;
    }""", child)
    assert result


def test_plugin_page_request_keeps_settings_unsaved_confirmation(settings_modal):
    assert settings_modal.evaluate("""() => {
      settings.settingsNavOpen = true;
      settings.settingsForm.cards_dir = '/storage/custom-cards';
      window.dispatchEvent(new CustomEvent('settings:request-close',
        {detail:{reason:'plugin-page-surface'}}));
      return settings.showDiscardConfirm && settings.showSettingsModal && settings.settingsNavOpen;
    }""")


@pytest.mark.parametrize('success,message', [(True, ''), (False, '已取消保存'), (False, '保存导出文件失败')])
def test_native_export_waits_for_actual_save_result(page, success, message):
    page.evaluate("""async () => {
      window.exportResult = 'pending';
      window.toasts = [];
      window.stmHost = {saveBase64FileAsync:(id,bytes,name,mime)=>{
        window.saveRequest = {id,bytes,name,mime};
      }};
      const dl = await import('/static/js/utils/download.js');
      const url = URL.createObjectURL(new Blob(['export payload'],{type:'application/octet-stream'}));
      dl.downloadFileFromApi({url, method:'GET', defaultFilename:'export.zip', successMessage:'已导出',
        showToast:message=>toasts.push(message)}).then(()=>exportResult='saved',
          error=>exportResult=error.message);
    }""")
    page.wait_for_function('window.saveRequest !== undefined')
    assert page.evaluate('exportResult') == 'pending'
    assert page.evaluate('toasts') == []
    page.evaluate("""() => window.dispatchEvent(new CustomEvent('host:download-result',
      {detail:{id:'unrelated-download',success:true}}))""")
    assert page.evaluate('exportResult') == 'pending'
    page.evaluate("""({success,message}) => window.dispatchEvent(new CustomEvent('host:download-result',
      {detail:{id:saveRequest.id,success,message}}))""", {'success': success, 'message': message})
    page.wait_for_function("exportResult !== 'pending'")
    assert page.evaluate('exportResult') == ('saved' if success else message)
    assert page.evaluate('toasts') == (['已导出'] if success else [])


def test_native_host_facade_is_unavailable_to_sandbox_and_same_origin_children(page):
    result = page.evaluate("""async () => {
      const moduleUrl = '/static/js/utils/nativeHost.js';
      const source = await (await fetch(moduleUrl)).text();
      const {installNativeHost} = await import(moduleUrl);
      const sent = [];
      window.stmNative = {postMessage:message=>sent.push(JSON.parse(message))};
      const installed = installNativeHost();
      window.stmHost.requestStorageAccess('trusted-storage', '[]');
      window.stmHost.saveBase64FileAsync('trusted-download','eA==','test.txt','text/plain');
      const children = [];
      for (const sandboxed of [true, false]) {
        children.push(await new Promise(resolve => {
          const frame = document.createElement('iframe');
          if (sandboxed) frame.setAttribute('sandbox', 'allow-scripts');
          const id = 'child-' + sandboxed;
          const onMessage = event => {
            if (event.source !== frame.contentWindow || event.data?.id !== id) return;
            window.removeEventListener('message', onMessage);
            resolve(event.data);
          };
          window.addEventListener('message', onMessage);
          frame.srcdoc = '<script type="module">' + source + `
            let calls = 0;
            window.stmNative = {postMessage:()=>calls++};
            const installed = installNativeHost();
            parent.postMessage({action:'storage',id:'forged',pathsJson:'[]'}, '*');
            parent.postMessage({id:${JSON.stringify(id)},installed,
              hostType:typeof window.stmHost,calls}, '*');
          <` + '/script>';
          document.body.append(frame);
        }));
      }
      return {installed, sent:sent.map(message=>message.action), children};
    }""")
    assert result['installed'] is True
    assert result['sent'] == ['storage', 'download']
    for child in result['children']:
        assert child['installed'] is False
        assert child['hostType'] == 'undefined'
        assert child['calls'] == 0


def test_all_modal_roots_use_real_component_back_paths(page):
    result = page.evaluate("""async () => {
      window.stmHost = {};
      const cases = [
        ['batchImportModal','showBatchImportModal'], ['automationModal','showAutomationModal'],
        ['commandPalette','open'], ['moveCardsModal','showMoveCardsModal'], ['rollbackModal','showRollbackModal'],
        ['pluginJobPanel','showPluginJobPanel'], ['importModal','showImportUrlModal'],
        ['batchTagModal','showBatchTagModal'], ['wiDetailPopup','showWiDetailModal'],
        ['presetDetailReader','showModal'], ['presetVersionMergeModal','showModal'],
        ['worldbookUpdate','show'], ['sourceUpdateMonitor','visible'], ['forumThreadPreview','visible'],
        ['gachaDraw','showGachaModal'], ['executeRulesMobileModal','showExecuteRulesModal'],
        ['tagFilterModal','showTagFilterModal'], ['advancedEditor','showAdvancedModal'],
        ['largeEditor','showLargeEditor'], ['largeEditor','showMarkdownModal'], ['largeEditor','showLargePreview'],
        ['folderOperations','showCreateFolder'], ['folderOperations','folderRenameModal.visible'],
        ['folderOperations','folderCreateSubModal.visible'], ['pluginManager','updateConfirm'],
      ];
      const components = {};
      const global = {deviceType:'mobile',currentMode:'cards',viewState:{selectedIds:[]},
        settingsForm:{}, folderModals:{createRoot:{visible:false},rename:{visible:false},createSub:{visible:false}}};
      for (const name of new Set(cases.map(([name])=>name))) {
        const component = (await import('/static/js/components/' + name + '.js')).default();
        component.$store = {global};
        component.$nextTick = callback=>callback();
        component.$refs = {};
        components[name] = component;
      }
      document.body.innerHTML = Object.keys(components).map(name=>`<div x-data="${name === 'presetDetailReader' ? name+'()' : name}"></div>`).join('');
      window.Alpine = {$data:el=>components[el.getAttribute('x-data').replace('()','')], store:()=>global};
      const layout = (await import('/static/js/components/layout.js')).default();
      layout.$store = {global};
      layout._installBackGestureSupport();
      const get = (c,path)=>path.split('.').reduce((value,key)=>value[key],c);
      const set = (c,path,value)=>{
        const keys = path.split('.');const key = keys.pop();
        keys.reduce((owner,part)=>owner[part],c)[key] = value;
      };
      const results = [];
      for (const [name,field] of cases) {
        const component = components[name];
        set(component,field,field === 'updateConfirm' ? {pluginId:'test'} : true);
        if (name === 'batchImportModal') {component.importItems=[{name:'test'}];component.batchId='pending';}
        if (name === 'forumThreadPreview') component.thread = {id:'test'};
        if (name === 'commandPalette') component.query = 'stale search';
        const before = window.__stmViewStack();
        const handled = window.__stmHostBack();
        results.push({name,field,depth:before.depth,handled,closed:!get(component,field),
          errors:before.registered.filter(layer=>layer.error)});
      }
      return {results, batchCleaned:!components.batchImportModal.batchId && !components.batchImportModal.importItems.length,
        commandCleaned:!components.commandPalette.query, forumCleaned:components.forumThreadPreview.thread===null};
    }""")
    for modal in result['results']:
        assert modal['depth'] == 1 and modal['handled'] and modal['closed'], modal
        assert modal['errors'] == [], modal
    assert result['batchCleaned'] and result['commandCleaned'] and result['forumCleaned']


def test_modal_child_back_respects_parent_and_layout_visibility(page):
    result = page.evaluate("""async () => {
      window.stmHost = {};
      const specs = [
        ['advancedEditor','showAdvancedModal','showDeleteConfirm',true,'mobile'],
        ['advancedEditor','showAdvancedModal','showMobileSidebar',true,'mobile'],
        ['automationModal','showAutomationModal','showConfirmModal',true,'mobile'],
        ['automationModal','showAutomationModal','showCreateModal',true,'mobile'],
        ['automationModal','showAutomationModal','showHelpModal',true,'mobile'],
        ['automationModal','showAutomationModal','showMobileSidebar',true,'mobile'],
        ['automationModal','showAutomationModal','openActionMenuKey','action-1','mobile'],
        ['batchImportModal','showBatchImportModal','openConflictActionKey',0,'mobile'],
        ['moveCardsModal','showMoveCardsModal','categoryMenuOpen',true,'mobile'],
        ['importModal','showImportUrlModal','categoryMenuOpen',true,'mobile'],
        ['detailModal','showDetail','mobileNavOpen',true,'mobile'],
        ['detailModal','showDetail','showHelpModal',true,'mobile'],
        ['detailModal','showDetail','showGreetingListModal',true,'mobile'],
        ['detailModal','showDetail','showSetResourceFolderModal',true,'mobile'],
        ['detailModal','showDetail','showRenameResourceFolderModal',true,'mobile'],
        ['detailModal','showDetail','showSkinGallery',true,'mobile'],
        ['detailModal','showDetail','skinGalleryPreviewPath','skin.png','mobile'],
        ['detailModal','showDetail','mainImagePreviewUrl','main.png','mobile'],
        ['detailModal','showDetail','personaPreviewField','personality','mobile'],
        ['wiEditor','showFullScreenWI','showHelpModal',true,'mobile'],
        ['wiEditor','showFullScreenWI','showWiSortMenu',true,'mobile'],
        ['wiEditor','showFullScreenWI','showFindReplaceModal',true,'mobile'],
        ['wiEditor','showFullScreenWI','showTaggedImportModal',true,'mobile'],
        ['wiEditor','showFullScreenWI','showEntryHistoryModal',true,'mobile'],
        ['wiDetailPopup','showWiDetailModal','showMobileSidebar',true,'mobile'],
        ['wiDetailPopup','showWiDetailModal','activeEntry',{uid:'1'},'mobile'],
        ['wiDetailPopup','showWiDetailModal','showWiSortMenu',true,'mobile'],
        ['presetEditor','showPresetEditor','showMobileSidebar',true,'mobile'],
        ['presetEditor','showPresetEditor','showMobilePromptDetailView',true,'mobile'],
        ['presetEditor','showPresetEditor','showMobileHeaderMoreMenu',true,'mobile'],
        ['presetDetailReader','showModal','showMobileSidebar',true,'mobile'],
        ['presetDetailReader','showModal','showMobileDetailView',true,'mobile'],
        ['presetDetailReader','showModal','showMobileMoreMenu',true,'mobile'],
        ['tagFilterModal','showTagFilterModal','isWorkspaceHelpOpen',true,'mobile'],
        ['tagFilterModal','showTagFilterModal','isMobileToolsOpen',true,'mobile'],
        ['tagFilterModal','showTagFilterModal','isGovernanceDrawerOpen',true,'desktop'],
      ];
      const components = {};
      const global = {deviceType:'mobile',currentMode:'cards',viewState:{},settingsForm:{}};
      for (const name of new Set(specs.map(([name])=>name))) {
        const c = (await import('/static/js/components/'+name+'.js')).default();
        c.$store={global};c.$nextTick=callback=>callback();c.$refs={};components[name]=c;
      }
      document.body.innerHTML=Object.keys(components).map(name=>`<div x-data="${name}"></div>`).join('');
      window.Alpine={$data:el=>components[el.getAttribute('x-data')], store:()=>global};
      const layout=(await import('/static/js/components/layout.js')).default();
      layout.$store={global};layout._installBackGestureSupport();
      const results=[];
      for (const [name,parent,child,value,device] of specs) {
        const c=components[name];global.deviceType=device;
        c[parent]=true;c[child]=value;
        const before=window.__stmViewStack();
        window.__stmHostBack();
        const childOnly=c[parent] && !c[child];
        c[parent]=false;c[child]=value;
        const hiddenIgnored=window.__stmViewStack().depth===0;
        c[child]=null;
        results.push({name,child,depth:before.depth,childOnly,hiddenIgnored});
      }
      const advanced=components.advancedEditor;
      advanced.showAdvancedModal=advanced.showMobileSidebar=true;
      global.deviceType='desktop';
      const desktopDepth=window.__stmViewStack().depth;
      window.__stmHostBack();
      return {results,desktopDepth,desktopClosedEditor:!advanced.showAdvancedModal};
    }""")
    for child in result['results']:
        assert child['depth'] == 2 and child['childOnly'] and child['hiddenIgnored'], child
    assert result['desktopDepth'] == 1 and result['desktopClosedEditor']


@pytest.mark.parametrize('index', [0, 1])
def test_batch_import_conflict_menu_back_keeps_batch_and_items(page, index):
    result = page.evaluate("""async index => {
      window.stmHost = {};
      const batch = (await import('/static/js/components/batchImportModal.js')).default();
      const global = {deviceType:'mobile', currentMode:'cards', viewState:{}, settingsForm:{}};
      batch.$store={global};
      document.body.innerHTML='<div x-data="batchImportModal"></div>';
      window.Alpine={$data:()=>batch, store:()=>global};
      const layout=(await import('/static/js/components/layout.js')).default();
      layout.$store={global};layout._installBackGestureSupport();
      batch.openModal('batch-123', [
        {filename:'first.png', status:'conflict'}, {filename:'second.png', status:'conflict'}
      ], 'target');
      batch.toggleConflictActionMenu(index);
      const before=JSON.stringify(batch.importItems);
      const depth=window.__stmViewStack().depth;
      const handled=window.__stmHostBack();
      const preserved=batch.showBatchImportModal && batch.batchId==='batch-123' &&
        batch.targetCategory==='target' && JSON.stringify(batch.importItems)===before;
      const menuClosed=batch.openConflictActionKey===null;
      const parentDepth=window.__stmViewStack().depth;
      window.__stmHostBack();
      return {depth,handled,preserved,menuClosed,parentDepth,
        cancelled:!batch.showBatchImportModal && batch.batchId===null && !batch.importItems.length};
    }""", index)
    assert result == {'depth': 2, 'handled': True, 'preserved': True, 'menuClosed': True,
                      'parentDepth': 1, 'cancelled': True}


def test_navigation_and_local_menu_back_checks_actual_visible_container(page):
    result = page.evaluate("""async () => {
      window.stmHost={};
      const names=['header','sidebar','entryDock','wiEditor'];
      const components={};
      const global={deviceType:'desktop',currentMode:'cards',visibleSidebar:true,viewState:{selectedIds:['one']}};
      for (const name of names) {
        const c=(await import('/static/js/components/'+name+'.js')).default();
        c.$store={global};c.$refs={};c.$nextTick=callback=>callback();components[name]=c;
      }
      components.entryDock.overflow=[{id:'one'}];
      components['header-batch-actions']={showBatchActionsMenu:false,showRuleMenu:false,showSourceUpdateMenu:false};
      components['wi-editor-tools']={showWiEditorToolsMenu:false};
      document.body.innerHTML=Object.keys(components).map(name=>
        `<div ${names.includes(name)?'x-data':'data-back-scope'}="${name}"></div>`).join('');
      window.Alpine={$data:el=>components[el.getAttribute('x-data')||el.getAttribute('data-back-scope')]};
      const layout=(await import('/static/js/components/layout.js')).default();
      layout.$store={global};layout._installBackGestureSupport();
      const checks=[];
      components.sidebar.moduleMenuOpen=true;
      window.__stmHostBack();checks.push(!components.sidebar.moduleMenuOpen && global.visibleSidebar);
      components.entryDock.overflowOpen=true;
      window.__stmHostBack();checks.push(!components.entryDock.overflowOpen);
      const actions=components['header-batch-actions'];
      actions.showBatchActionsMenu=actions.showRuleMenu=true;
      window.__stmHostBack();checks.push(!actions.showRuleMenu && actions.showBatchActionsMenu);
      global.viewState.selectedIds=[];
      checks.push(window.__stmViewStack().depth===0);
      actions.showBatchActionsMenu=false;
      const wi=components.wiEditor, tools=components['wi-editor-tools'];
      wi.showFullScreenWI=true;wi.wiEditorActionRailMode='compact';tools.showWiEditorToolsMenu=true;
      window.__stmHostBack();checks.push(!tools.showWiEditorToolsMenu && wi.showFullScreenWI);
      tools.showWiEditorToolsMenu=true;wi.wiEditorActionRailMode='expanded';
      checks.push(window.__stmViewStack().depth===1);
      wi.showFullScreenWI=false;checks.push(window.__stmViewStack().depth===0);
      global.deviceType='mobile';global.visibleSidebar=false;components.header.showMobileMenu=true;
      window.__stmHostBack();checks.push(!components.header.showMobileMenu);
      components.entryDock.expanded=true;components.entryDock.overflow=[];
      checks.push(window.__stmViewStack().depth===0);
      return checks;
    }""")
    assert all(result), result


def test_automation_back_preserves_unsaved_rules_and_cancel_confirmation(page):
    assert page.evaluate("""async () => {
      window.stmHost={};
      const editor=(await import('/static/js/components/automationModal.js')).default();
      editor.$nextTick=callback=>callback();
      const global={deviceType:'desktop',currentMode:'cards'};
      editor.$store={global};editor.showAutomationModal=true;
      Object.defineProperty(editor,'isDirty',{get:()=>true});
      document.body.innerHTML='<div x-data="automationModal"></div>';
      window.Alpine={$data:()=>editor};
      const layout=(await import('/static/js/components/layout.js')).default();
      layout.$store={global};layout._installBackGestureSupport();
      window.__stmHostBack();
      const prompted=editor.showConfirmModal && editor.showAutomationModal;
      window.__stmHostBack();
      return prompted && !editor.showConfirmModal && editor.showAutomationModal && editor.isDirty;
    }""")
