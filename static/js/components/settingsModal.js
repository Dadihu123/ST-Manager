/**
 * static/js/components/settingsModal.js
 * 系统设置组件
 */

import { uploadBackground } from '../api/resource.js';
import { openTrash, emptyTrash, performSystemAction, triggerScan } from '../api/system.js';
import { updateCssVariable, applyFont as applyFontDom } from '../utils/dom.js';

export default function settingsModal() {
    return {
        // === 本地状态 ===
        activeSettingTab: 'general',
        allowedAbsRootsText: '',

        get settingsForm() { return this.$store.global.settingsForm; },
        get showSettingsModal() { 
            return this.$store.global.showSettingsModal; 
        },
        set showSettingsModal(val) { 
            this.$store.global.showSettingsModal = val; 
        },

        updateCssVariable,
        
        applyFont(type) {
            // 1. 更新全局状态 (这会让按钮的高亮 :class 重新计算)
            this.$store.global.settingsForm.font_style = type;
            
            // 2. 应用 CSS 样式 (改变视觉字体)
            applyFontDom(type);
        },

        // 1. 应用主题 (调用全局 Store 的 action)
        applyTheme(color) {
            this.$store.global.applyTheme(color);
        },

        // 2. 切换深色模式 (调用全局 Store)
        toggleDarkMode() {
            this.$store.global.toggleDarkMode();
        },

        // 3. 立即扫描 (scanNow)
        scanNow() {
            if (!confirm("立即触发一次全量扫描同步磁盘与数据库？\n（适用于 watchdog 未安装或你手动改动过文件）")) return;
            
            this.$store.global.isLoading = true;
            triggerScan()
                .then(res => {
                    if (!res.success) alert("触发扫描失败: " + (res.msg || 'unknown'));
                    else alert("已触发扫描任务（后台进行中）。稍后可点刷新查看结果。");
                })
                .catch(err => alert("网络错误: " + err))
                .finally(() => { 
                    this.$store.global.isLoading = false; 
                });
        },

        // 4. 系统操作 (systemAction: 打开文件夹、备份等)
        systemAction(action) {
            performSystemAction(action)
                .then(res => {
                    if (!res.success && res.msg) alert(res.msg);
                    else if (res.msg) alert(res.msg);
                })
                .catch(err => alert("请求失败: " + err));
        },

        // === 初始化 ===
        init() {
            // 设置数据直接绑定到 $store.global.settingsForm
            // 无需本地 duplicate
            this.$watch('showSettingsModal', (val) => {
                if (val) {
                    const roots = this.settingsForm.allowed_abs_resource_roots || [];
                    this.allowedAbsRootsText = Array.isArray(roots) ? roots.join('\n') : String(roots || '');
                }
            });
        },

        openSettings() {
            const roots = this.settingsForm.allowed_abs_resource_roots || [];
            this.allowedAbsRootsText = Array.isArray(roots) ? roots.join('\n') : String(roots || '');
            this.showSettingsModal = true;
        },

        saveSettings(closeModal = true) {
            const roots = (this.allowedAbsRootsText || '')
                .split(/[\r\n,]+/)
                .map(s => s.trim())
                .filter(Boolean);
            this.settingsForm.allowed_abs_resource_roots = roots;
            // 调用 Store 的 Action
            this.$store.global.saveSettings(closeModal)
                .then(res => {
                    if (res && res.success && closeModal) {
                        this.showSettingsModal = false; // 手动关闭
                    }
                });
        },

        // === 背景图上传 ===
        
        triggerBackgroundUpload() {
            this.$refs.bgUploadInput.click();
        },

        handleBackgroundUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            if (file.size > 10 * 1024 * 1024) {
                alert("图片太大，请上传 10MB 以内的图片");
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            const btn = e.target.previousElementSibling; 
            const originalText = btn ? btn.innerText : '';
            if(btn) btn.innerText = '⏳...';

            uploadBackground(formData)
                .then(res => {
                    if (res.success) {
                        // 更新 Store
                        this.$store.global.settingsForm.bg_url = res.url;
                        this.$store.global.updateBackgroundImage(res.url);
                    } else {
                        alert("上传失败: " + res.msg);
                    }
                })
                .catch(err => {
                    alert("网络错误: " + err);
                })
                .finally(() => {
                    if(btn) btn.innerText = originalText;
                    e.target.value = ''; 
                });
        },

        // === 回收站操作 ===

        openTrashFolder() {
            openTrash().then(res => {
                if(!res.success) alert("打开失败: " + res.msg);
            });
        },

        emptyTrash() {
            if(!confirm("确定要彻底清空回收站吗？此操作无法撤销！")) return;
            emptyTrash().then(res => {
                if(res.success) alert(res.msg);
                else alert("清空失败: " + res.msg);
            });
        },

        // === SillyTavern 同步功能 ===
        
        stPathStatus: '',
        stPathValid: false,
        stResources: {},
        syncing: false,
        syncStatus: '',
        syncSuccess: false,

        getResourceLabel(type) {
            const labels = {
                'characters': '🎴 角色卡',
                'worlds': '📚 世界书',
                'presets': '📝 预设',
                'regex': '🔧 正则脚本',
                'quick_replies': '💬 快速回复',
                'scripts': '📜 ST脚本'
            };
            return labels[type] || type;
        },

        async detectSTPath() {
            try {
                this.stPathStatus = '正在探测...';
                const resp = await fetch('/api/st/detect_path');
                const data = await resp.json();
                
                if (data.success && data.path) {
                    this.$store.global.settingsForm.st_data_dir = data.path;
                    this.stPathStatus = `✓ 探测到路径: ${data.path}`;
                    this.stPathValid = true;
                    await this.validateSTPath();
                } else {
                    this.stPathStatus = '未能自动探测到 SillyTavern 安装路径，请手动配置';
                    this.stPathValid = false;
                }
            } catch (err) {
                this.stPathStatus = '探测失败: ' + err.message;
                this.stPathValid = false;
            }
        },

        async validateSTPath() {
            const path = this.$store.global.settingsForm.st_data_dir;
            if (!path) {
                this.stPathStatus = '请输入或探测路径';
                this.stPathValid = false;
                this.stResources = {};
                return;
            }
            
            try {
                this.stPathStatus = '正在验证...';
                const resp = await fetch('/api/st/validate_path', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path })
                });
                const data = await resp.json();
                
                if (data.success && data.valid) {
                    if (data.normalized_path && data.normalized_path !== path) {
                        this.$store.global.settingsForm.st_data_dir = data.normalized_path;
                        this.stPathStatus = `✓ 路径有效，已转换为安装根目录：${data.normalized_path}`;
                    } else {
                        this.stPathStatus = '✓ 路径有效';
                    }
                    this.stPathValid = true;
                    this.stResources = data.resources || {};
                } else {
                    this.stPathStatus = '✗ 路径无效或不是 SillyTavern 安装目录';
                    this.stPathValid = false;
                    this.stResources = {};
                }
            } catch (err) {
                this.stPathStatus = '验证失败: ' + err.message;
                this.stPathValid = false;
                this.stResources = {};
            }
        },

        async syncFromST(resourceType) {
            if (this.syncing) return;
            
            this.syncing = true;
            this.syncStatus = `正在同步 ${this.getResourceLabel(resourceType)}...`;
            this.syncSuccess = false;
            
            try {
                let stPath = (this.$store.global.settingsForm.st_data_dir || '').trim();
                if (!stPath) {
                    const input = document.querySelector('input[x-model="settingsForm.st_data_dir"]');
                    if (input && input.value) stPath = input.value.trim();
                }
                const resp = await fetch('/api/st/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ resource_type: resourceType, st_data_dir: stPath })
                });
                const data = await resp.json();
                
                if (data.success) {
                    const result = data.result;
                    this.syncStatus = `✓ 同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
                    this.syncSuccess = result.failed === 0;
                    
                    // 同步成功后触发刷新
                    if (result.success > 0) {
                        if (resourceType === 'characters') {
                            this.syncStatus += '，正在刷新列表...';
                            // 等待后端扫描完成
                            await new Promise(r => setTimeout(r, 1500));
                            window.dispatchEvent(new CustomEvent('refresh-card-list'));
                            this.syncStatus = `✓ 同步完成: ${result.success} 个成功, ${result.failed} 个失败`;
                        } else if (resourceType === 'worlds') {
                            window.dispatchEvent(new CustomEvent('refresh-wi-list'));
                        }
                    }
                } else {
                    this.syncStatus = '✗ 同步失败: ' + (data.error || '未知错误');
                    this.syncSuccess = false;
                }
            } catch (err) {
                this.syncStatus = '✗ 同步失败: ' + err.message;
                this.syncSuccess = false;
            } finally {
                this.syncing = false;
            }
        },

        async syncAllFromST() {
            if (this.syncing) return;
            
            const types = ['characters', 'worlds', 'presets', 'regex', 'quick_replies'];
            let totalSuccess = 0;
            let totalFailed = 0;
            let hasCharacters = false;
            let hasWorlds = false;
            
            this.syncing = true;
            
            let stPath = (this.$store.global.settingsForm.st_data_dir || '').trim();
            if (!stPath) {
                const input = document.querySelector('input[x-model="settingsForm.st_data_dir"]');
                if (input && input.value) stPath = input.value.trim();
            }
            for (const type of types) {
                this.syncStatus = `正在同步 ${this.getResourceLabel(type)}...`;
                
                try {
                    const resp = await fetch('/api/st/sync', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ resource_type: type, st_data_dir: stPath })
                    });
                    const data = await resp.json();
                    
                    if (data.success) {
                        totalSuccess += data.result.success;
                        totalFailed += data.result.failed;
                        if (type === 'characters' && data.result.success > 0) {
                            hasCharacters = true;
                        }
                        if (type === 'worlds' && data.result.success > 0) {
                            hasWorlds = true;
                        }
                    }
                } catch (err) {
                    totalFailed++;
                }
            }
            
            this.syncStatus = `✓ 全部同步完成: ${totalSuccess} 个成功, ${totalFailed} 个失败`;
            this.syncSuccess = totalFailed === 0;
            this.syncing = false;
            
            // 同步成功后触发刷新
            if (hasCharacters) {
                await new Promise(r => setTimeout(r, 1500));
                window.dispatchEvent(new CustomEvent('refresh-card-list'));
            }
            if (hasWorlds) {
                window.dispatchEvent(new CustomEvent('refresh-wi-list'));
            }
        }
    }
}
