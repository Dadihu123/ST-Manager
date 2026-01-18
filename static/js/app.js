/**
 * static/js/app.js
 * 前端主入口文件
 */

// 1. 导入全局状态初始化
import { initState } from './state.js';

// 2. 导入 UI 组件
import layout from './components/layout.js';
import header from './components/header.js';
import sidebar from './components/sidebar.js';
import cardGrid from './components/cardGrid.js';
import wiGrid from './components/wiGrid.js';
import detailModal from './components/detailModal.js';
import wiEditor from './components/wiEditor.js';
import advancedEditor from './components/advancedEditor.js';
import rollbackModal from './components/rollbackModal.js';
import settingsModal from './components/settingsModal.js';
import largeEditor from './components/largeEditor.js';
import tagPicker from './components/tagPicker.js';
import tagFilterModal from './components/tagFilterModal.js';
import batchTagModal from './components/batchTagModal.js';
import importModal from './components/importModal.js';
import contextMenu from './components/contextMenu.js';
import folderOperations from './components/folderOperations.js';
import wiDetailPopup from './components/wiDetailPopup.js';
import resourceManager from './components/resourceManager.js';

// 3. 监听 Alpine 初始化事件
const registerComponents = () => {
    
    // A. 初始化全局 Store ($store.global)
    initState();

    // B. 注册所有 Alpine 组件 (x-data)
    Alpine.data('layout', layout);
    Alpine.data('header', header);
    Alpine.data('sidebar', sidebar);
    Alpine.data('cardGrid', cardGrid);
    Alpine.data('wiGrid', wiGrid);
    Alpine.data('detailModal', detailModal);
    Alpine.data('wiEditor', wiEditor);
    Alpine.data('advancedEditor', advancedEditor);
    Alpine.data('rollbackModal', rollbackModal);
    Alpine.data('settingsModal', settingsModal);
    Alpine.data('largeEditor', largeEditor);
    Alpine.data('tagPicker', tagPicker);
    Alpine.data('tagFilterModal', tagFilterModal);
    Alpine.data('batchTagModal', batchTagModal);
    Alpine.data('importModal', importModal);
    Alpine.data('contextMenu', contextMenu);
    Alpine.data('folderOperations', folderOperations);
    Alpine.data('wiDetailPopup', wiDetailPopup);
    Alpine.data('resourceManager', resourceManager);

    console.log("✅ ST Manager Frontend: Modules Loaded & Alpine Initialized");
};

// 检查 Alpine 是否已存在
if (window.Alpine) {
    // 如果 app.js 加载晚了，Alpine 已经就绪，直接注册
    registerComponents();
} else {
    // 如果 app.js 加载早，等待 Alpine 初始化事件
    document.addEventListener('alpine:init', registerComponents);
}

// 4. 全局错误处理 (可选)
window.addEventListener('unhandledrejection', (event) => {
    console.warn("Unhandled Promise Rejection:", event.reason);
});