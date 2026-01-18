/**
 * static/js/state.js
 * 全局状态管理 (Alpine.store)
 */

import { 
    getServerStatus, 
    getSettings, 
    saveSettings, 
    performSystemAction, 
    triggerScan 
} from './api/system.js';

import { 
    updateCssVariable, 
    applyFont 
} from './utils/dom.js';

// 主题预设常量
const THEME_PRESETS = {
    blue:   { main: '#2563eb', hover: '#1d4ed8', light: '#60a5fa', faint: 'rgba(37, 99, 235, 0.3)' },
    purple: { main: '#7c3aed', hover: '#6d28d9', light: '#a78bfa', faint: 'rgba(124, 58, 237, 0.3)' },
    green:  { main: '#059669', hover: '#047857', light: '#34d399', faint: 'rgba(5, 150, 105, 0.3)' },
    red:    { main: '#dc2626', hover: '#b91c1c', light: '#f87171', faint: 'rgba(220, 38, 38, 0.3)' },
    orange: { main: '#ea580c', hover: '#c2410c', light: '#fb923c', faint: 'rgba(234, 88, 12, 0.3)' },
    pink:   { main: '#db2777', hover: '#be185d', light: '#f472b6', faint: 'rgba(219, 39, 119, 0.3)' },
};

export function initState() {
    Alpine.store('global', {
        // === 状态属性 ===
        isLoading: false,
        isSaving: false,
        showSettingsModal: false,
        
        // 模式: 'cards' | 'worldinfo'
        currentMode: 'cards',
        
        // 服务器状态
        serverStatus: { status: 'initializing', message: '', progress: 0, total: 0 },
        isDocker: false,
        _bootstrapped: false,

        // 界面状态
        isDarkMode: true,
        windowWidth: window.innerWidth,
        toastMessage: '',
        showToastState: false,
        toastTimer: null,
        _resizeTimer: null,

        // 移动端侧边栏状态
        mobileSidebarOpen: false,

        // 数据池 (供 Sidebar 和 Grid 共享)
        allTagsPool: [],
        sidebarTagsPool: [],
        globalTagsPool: [],
        categoryCounts: {},
        libraryTotal: 0,

        // 分页配置
        itemsPerPage: 20,

        // 世界书共享状态
        wiList: [], // 世界书列表数据
        wiSearchQuery: '', // 搜索关键词
        wiFilterType: 'all', // 筛选类型: 'all', 'global', 'resource', 'embedded'
        wiCurrentPage: 1,
        wiTotalItems: 0,
        wiTotalPages: 1,
        
        // 设置表单
        settingsForm: { 
            cards_dir: 'data/library/characters',
            default_sort: 'date_desc', 
            st_url: 'http://127.0.0.1:8000', 
            st_username: '',
            st_password: '',
            st_auth_type: 'basic', 
            host: '127.0.0.1',
            port: 5000,
            items_per_page: 0,
            items_per_page_wi: 0,
            theme_accent: 'blue',
            auto_save_enabled: false,
            auto_save_interval: 3, 
            dark_mode: true,
            font_style: 'sans', 
            card_width: 220, 
            bg_url: '', 
            bg_opacity: 0.95, 
            bg_blur: 0,
            favorites_first: false,
            discord_token: '',
        },

        // === 集中管理的视图状态 ===
        viewState: {
            searchQuery: '',
            searchType: 'mix',
            filterCategory: '',
            filterTags: [],
            recursiveFilter: true,
            selectedIds: [],
            lastSelectedId: null,
            tagSearchQuery: '',
            draggedCards: [],   // 当前正在拖拽的卡片 ID 列表
            draggedFolder: null, // 当前正在拖拽的文件夹路径
            filterFavorites: false,// 是否只显示收藏
        },

        // === 文件夹模态框状态 ===
        folderModals: {
            // 重命名模态框
            rename: {
                visible: false,
                path: '',
                name: ''
            },
            // 新建子文件夹模态框
            createSub: {
                visible: false,
                parentPath: '',
                name: ''
            },
            // 新建根/一级文件夹模态框 (兼容 Sidebar 逻辑)
            createRoot: {
                visible: false,
                parent: '',
                name: ''
            }
        },

        // === 初始化逻辑 ===
        init() {
            this.checkServerStatus();
            this.loadUserPreferences();

            // 监听窗口大小变化
            window.addEventListener('resize', () => {
                this.windowWidth = window.innerWidth;
                clearTimeout(this._resizeTimer);
                this._resizeTimer = setTimeout(() => this.updateItemsPerPage(), 200);
            });

            // 全局防止浏览器默认打开图片
            window.addEventListener('dragover', e => e.preventDefault());
            window.addEventListener('drop', e => e.preventDefault());
        },

        // 轮询服务器状态，准备就绪后执行 bootstrap
        checkServerStatus() {
            getServerStatus()
                .then(res => {
                    this.serverStatus = res;
                    this.isDocker = !!res.is_docker;
                    if (res.status === 'ready') {
                        if (!this._bootstrapped) {
                            this._bootstrapped = true;
                            this.bootstrapOnce();
                        }
                    } else {
                        setTimeout(() => this.checkServerStatus(), 500);
                    }
                })
                .catch(() => {
                    setTimeout(() => this.checkServerStatus(), 1000);
                });
        },

        // 仅执行一次的启动逻辑 (加载设置)
        bootstrapOnce() {
            getSettings()
                .then(settings => {
                    const localSort = localStorage.getItem('st_manager_sort');
                    const localPerPage = localStorage.getItem('st_manager_per_page');
                    const localPerPageWi = localStorage.getItem('st_manager_per_page_wi');
                    
                    this.settingsForm = {
                        ...settings,
                        default_sort: localSort || settings.default_sort || 'date_desc',
                        st_auth_type: settings.st_auth_type || 'basic',
                        items_per_page: localPerPage ? parseInt(localPerPage) : (settings.items_per_page || 0),
                        items_per_page_wi: localPerPageWi ? parseInt(localPerPageWi) : (settings.items_per_page_wi || 0)
                    };

                    // 应用视觉设置
                    if (settings.theme_accent) this.applyTheme(settings.theme_accent);
                    this.isDarkMode = (settings.dark_mode !== undefined) ? settings.dark_mode : true;
                    this.applyDarkMode();
                    applyFont(this.settingsForm.font_style || 'sans');
                    
                    updateCssVariable('--card-min-width', (this.settingsForm.card_width || 220) + 'px');
                    
                    if (this.settingsForm.bg_url) {
                        this.updateBackgroundImage(this.settingsForm.bg_url);
                        updateCssVariable('--bg-blur', (this.settingsForm.bg_blur || 0) + 'px');
                        updateCssVariable('--bg-overlay-opacity', this.settingsForm.bg_opacity || 0.95);
                    } else {
                        this.updateBackgroundImage('');
                    }

                    this.updateItemsPerPage();

                    // 发出事件通知组件设置已加载 (代替原 app.js 直接调用 fetchCards)
                    window.dispatchEvent(new CustomEvent('settings-loaded'));
                })
                .catch(err => {
                    console.error("Bootstrap failed", err);
                    // 即使失败也发出事件，让 UI 尝试加载默认数据
                    window.dispatchEvent(new CustomEvent('settings-loaded'));
                });
        },

        // 加载本地存储的偏好 (UI 优先)
        loadUserPreferences() {
            const savedSort = localStorage.getItem('st_manager_sort');
            const savedPerPage = localStorage.getItem('st_manager_per_page');
            
            if (savedSort) this.settingsForm.default_sort = savedSort;
            if (savedPerPage) this.settingsForm.items_per_page = parseInt(savedPerPage);
        },

        // === 全局动作 ===

        // 切换深色模式
        toggleDarkMode() {
            this.isDarkMode = !this.isDarkMode;
            this.settingsForm.dark_mode = this.isDarkMode;
            this.applyDarkMode();
            this.saveSettings(false); // 静默保存
        },

        applyDarkMode() {
            if (this.isDarkMode) {
                document.documentElement.classList.remove('light-mode');
            } else {
                document.documentElement.classList.add('light-mode');
            }
        },

        // 应用主题色
        applyTheme(colorName) {
            const t = THEME_PRESETS[colorName] || THEME_PRESETS.blue;
            updateCssVariable('--accent-main', t.main);
            updateCssVariable('--accent-hover', t.hover);
            updateCssVariable('--accent-light', t.light);
            updateCssVariable('--accent-faint', t.faint);
            this.settingsForm.theme_accent = colorName;
        },

        // 更新背景图
        updateBackgroundImage(url) {
            if (!url) {
                updateCssVariable('--bg-image-url', 'none');
                updateCssVariable('--bg-overlay-opacity', '1'); 
            } else {
                updateCssVariable('--bg-image-url', `url('${url}')`);
                const opacity = this.settingsForm.bg_opacity !== undefined ? this.settingsForm.bg_opacity : 0.95;
                updateCssVariable('--bg-overlay-opacity', opacity);
            }
        },

        // 保存设置
        saveSettings(closeModal = true) {
            this.applyTheme(this.settingsForm.theme_accent);
            
            // 乐观更新 localStorage
            if (this.settingsForm.items_per_page) localStorage.setItem('st_manager_per_page', this.settingsForm.items_per_page);
            if (this.settingsForm.items_per_page_wi) localStorage.setItem('st_manager_per_page_wi', this.settingsForm.items_per_page_wi);
            if (this.settingsForm.default_sort) localStorage.setItem('st_manager_sort', this.settingsForm.default_sort);

            return saveSettings(this.settingsForm)
                .then(res => {
                    if (res.success) {
                        this.updateItemsPerPage();
                        // 触发事件让组件刷新
                        if (closeModal) {
                            window.dispatchEvent(new CustomEvent('settings-saved', { detail: { closeModal: true } }));
                        }
                    } else {
                        alert("保存失败: " + res.msg);
                    }
                    return res;
                });
        },

        // 计算每页项目数 (响应式)
        updateItemsPerPage() {
            const userSetting = parseInt(this.settingsForm.items_per_page) || 0;

            if (userSetting > 0) {
                this.itemsPerPage = Math.min(Math.max(userSetting, 10), 500);
            } else {
                const availableWidth = window.innerWidth - 300 - 48; // Sidebar + Padding
                const availableHeight = window.innerHeight - 64 - 60; // Header + Footer
                
                // 估算
                const cols = Math.floor(Math.max(1, availableWidth / 224));
                const rows = Math.floor(Math.max(1, availableHeight / 472));
                
                this.itemsPerPage = Math.max(20, Math.floor(cols * rows * 1.5));
            }
        },

        // 显示 Toast 通知
        showToast(msg, duration = 3000) {
            this.toastMessage = msg;
            this.showToastState = true;
            if (this.toastTimer) clearTimeout(this.toastTimer);
            this.toastTimer = setTimeout(() => {
                this.showToastState = false;
            }, duration);
        },

        // 执行系统操作 (打开文件夹等)
        systemAction(action) {
            performSystemAction(action)
                .then(res => {
                    if (!res.success && res.msg) alert(res.msg);
                    else if (res.msg) alert(res.msg);
                });
        },

        // 触发立即扫描
        scanNow() {
            if (!confirm("立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）")) return;
            this.isLoading = true;
            triggerScan()
                .then(res => {
                    if (!res.success) alert("触发扫描失败: " + (res.msg || 'unknown'));
                    else alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
                })
                .catch(err => alert("网络错误: " + err))
                .finally(() => { this.isLoading = false; });
        }
    });
}