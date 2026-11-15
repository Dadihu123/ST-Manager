"""通过真实 JS 组件验证触摸选择、特效与插件菜单行为。"""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(body):
    script = """
        import assert from 'node:assert/strict';
        import cardGrid from './static/js/components/cardGrid.js';
        import contextMenu from './static/js/components/contextMenu.js';
        import { ContributionRegistry } from './static/js/contributionRegistry.js';
        let touch = true;
        const listeners = {};
        const events = [];
        globalThis.window = {
          innerWidth:390, innerHeight:844,
          matchMedia:()=>({matches:touch}),
          addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
          dispatchEvent(event) { events.push(event); (listeners[event.type] || []).forEach(f=>f(event)); },
        };
        const store = {deviceType:'mobile', settingsForm:{card_effects_enabled:true},
          viewState:{selectedIds:[], lastSelectedId:null}};
        const grid = cardGrid();
        grid.$store = {global:store};
    """ + body
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_touch_long_press_selects_and_selection_mode_toggles_other_cards():
    run_node("""
        const a = {id:'a'}, b = {id:'b'};
        grid.showCardContextMenu({stmLongPress:true}, a);
        assert.deepEqual(grid.selectedIds, ['a']);
        assert.equal(events.length, 0);
        grid.handleCardClick({}, b);
        assert.deepEqual(grid.selectedIds, ['a', 'b']);
        grid.handleCardClick({}, a);
        assert.deepEqual(grid.selectedIds, ['b']);
        grid.handleCardClick({}, b);
        grid.handleCardClick({}, a);
        assert.equal(events.at(-1).type, 'open-detail');
        touch = false;
        grid.showCardContextMenu({clientX:10,clientY:20}, a);
        assert.equal(events.at(-1).type, 'show-context-menu');
    """)


def test_card_effects_require_desktop_pointer_and_enabled_setting():
    run_node("""
        assert.equal(grid.isCardEffectsEnabled(), false);
        store.deviceType = 'tablet';
        assert.equal(grid.isCardEffectsEnabled(), false);
        touch = false;
        store.deviceType = 'desktop';
        assert.equal(grid.isCardEffectsEnabled(), true);
        store.settingsForm.card_effects_enabled = false;
        assert.equal(grid.isCardEffectsEnabled(), false);
        store.settingsForm.card_effects_enabled = true;
        store.deviceType = 'mobile';
        assert.equal(grid.isCardEffectsEnabled(), false);
    """)


def test_empty_card_menu_stays_closed_but_folder_and_plugin_menus_work():
    run_node("""
        const menu = contextMenu();
        menu.$store = {global:store};
        let nodes = [];
        ContributionRegistry.menuTree = placement => placement === 'context.card' ? nodes : [];
        menu.init();
        const show = type => window.dispatchEvent(new CustomEvent('show-context-menu', {
          detail:{x:20,y:30,type,target:'a',targetCard:{id:'a'}},
        }));
        show('card');
        assert.equal(menu.visible, false);
        nodes = [{type:'separator'}, {type:'submenu',children:[]}];
        show('card');
        assert.equal(menu.visible, false);
        nodes = [{type:'action',label:'Plugin action',enabled:true}];
        show('card');
        assert.equal(menu.visible, true);
        nodes = [];
        window.dispatchEvent(new CustomEvent('contributions:changed'));
        assert.equal(menu.visible, false);
        show('folder');
        assert.equal(menu.visible, true);
    """)
