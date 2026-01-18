/**
 * static/js/components/contextMenu.js
 * 上下文菜单组件 (右键菜单)
 */

import { deleteFolder } from '../api/system.js';

import { toggleBundleMode } from '../api/card.js';

export default function contextMenu() {
    return {
        visible: false,
        x: 0,
        y: 0,
        target: null, // path
        type: null,   // 'folder' | 'card'
        targetFolder: null, // 文件夹对象引用

        init() {
            // 监听显示事件 (由 Sidebar 触发)
            window.addEventListener('show-context-menu', (e) => {
                const { x, y, type, target, targetFolder } = e.detail;
                
                // 边界检测 (防止菜单溢出屏幕)
                const menuWidth = 160; 
                const menuHeight = 200;
                
                this.x = (x + menuWidth > window.innerWidth) ? x - menuWidth : x;
                this.y = (y + menuHeight > window.innerHeight) ? y - menuHeight : y;
                
                this.type = type;
                this.target = target;
                this.targetFolder = targetFolder;
                this.visible = true;
            });

            // 监听隐藏事件
            window.addEventListener('hide-context-menu', () => {
                this.visible = false;
            });

            // 点击外部自动关闭
            window.addEventListener('click', () => {
                this.visible = false;
            });
        },

        // === 菜单动作 ===

        // 重命名
        handleRename() {
            if (this.type === 'folder' && this.target) {
                const currentName = this.target.split('/').pop();
                
                // 直接操作全局 Store
                this.$store.global.folderModals.rename = {
                    visible: true,
                    path: this.target,
                    name: currentName
                };
                
                this.visible = false;
            }
        },

        // 新建子文件夹
        handleCreateSub() {
            if (this.type === 'folder') {
                // 直接操作全局 Store
                this.$store.global.folderModals.createSub = {
                    visible: true,
                    parentPath: this.target,
                    name: ''
                };
                
                this.visible = false;
            }
        },

        // 删除
        handleDelete() {
            if (this.type === 'folder') {
                if(!confirm(`确定删除文件夹 "${this.target}" 及其内容吗？`)) return;
                deleteFolder({ folder_path: this.target }).then(res => {
                    if(res.success) {
                        window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    } else alert(res.msg);
                });
            }
        },

        // 聚合模式
        handleBundle() {
            if (this.type === 'folder') {
                // Toggle Bundle Mode
                // 1. Check
                toggleBundleMode({ folder_path: this.target, action: 'check' }).then(res => {
                    if(!res.success) return alert(res.msg);
                    
                    if(confirm(`将 "${this.target}" 设为聚合角色包？\n包含 ${res.count} 张图片。`)) {
                        toggleBundleMode({ folder_path: this.target, action: 'enable' }).then(r2 => {
                            if(r2.success) {
                                alert(r2.msg);
                                window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                                window.dispatchEvent(new CustomEvent('refresh-card-list'));
                            } else alert(r2.msg);
                        });
                    }
                });
            }
        }
    }
}