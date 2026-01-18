# ST-Manager
针对sillytavern的各种资源进行可视化管理的程序。

## 🐳 Docker 部署说明

通过 Docker 部署可以快速运行 ST-Manager 并保持环境隔离。

### 1. 拉取镜像
```bash
docker pull ggssst/st-manager:latest
```

### 2. 命令行快速启动
运行以下命令即可启动并映射必要的持久化目录。此命令会自动处理端口映射和卷挂载：

```bash
docker run -d \
  --name st-manager \
  -p 5000:5000 \
  -v ./data:/app/data \
  -v ./config.json:/app/config.json \
  --restart unless-stopped \
  ggssst/st-manager:latest
```

**参数详解：**
*   `-d`: 后台运行容器。
*   `--name st-manager`: 为容器指定一个易记的名称。
*   `-p 5000:5000`: 将宿主机的 5000 端口映射到容器的 5000 端口。
*   `-v ./data:/app/data`: 将宿主机的 `data` 目录挂载到容器内，用于持久化存储卡片、世界书等数据。
*   `-v ./config.json:/app/config.json`: 挂载配置文件。
*   `--restart unless-stopped`: 除非手动停止，否则容器在意外退出或 Docker 重启时会自动启动。

> **⚠️ 重要提示 (Windows 用户)**: 在执行命令前，请务必先在当前文件夹下手动创建一个 `config.json` 文件（即使是空的）。如果宿主机上不存在该文件，Docker 会默认将其创建一个**同名文件夹**，导致程序因路径冲突而启动失败。

### 3. 使用 Docker Compose (推荐)
对于更稳定的管理，推荐使用 `docker-compose.yml`。新的配置采用了**命名卷 (Named Volumes)**，它可以确保：
*   **零配置启动**：宿主机无需预先准备 `config.json` 或 `data` 文件夹，直接启动即可运行。
*   **数据持久化**：即使删除容器，您的数据仍保留在 Docker 管理的卷中。

在项目目录创建 `docker-compose.yml` 并填入：

```yaml
version: '3.8'
services:
  st-manager:
    image: ggssst/st-manager:latest
    container_name: st-manager
    ports:
      - "5000:5000"
    volumes:
      - st-manager-data:/app/data
    environment:
      - HOST=0.0.0.0
      - PORT=5000
    restart: unless-stopped

volumes:
  st-manager-data:
```

**操作指南：**
*   **启动服务**：`docker-compose up -d`
*   **停止服务**：`docker-compose down`
*   **查看运行日志**：`docker logs -f st-manager`

**进阶配置 (可选)**：
如果您想手动修改配置文件，可以先运行一次程序，然后将容器内的配置文件拷贝出来进行修改并重新挂载。

### 4. 目录说明
*   `/app/data`: 包含所有角色卡、世界书、缩略图等持久化数据。
*   `/app/config.json`: 程序配置文件。

### 5. 常见问题
*   **访问地址**: 默认访问 `http://localhost:5000`。
*   **登录认证**: 默认情况下已开启保底配置。若未在 `config.json` 中修改，默认账号为 `admin`，密码为 `password`。
*   **浏览器自动打开**: 在 Docker 环境下，程序不会尝试打开宿主机浏览器，需手动输入地址访问。

## 📝 更新日志

### V1.1 (2026-01-18)
*   **🔒 安全与易用性优化**
    *   移除了不安全的 Discord 脚本自动复制功能。
    *   新增详细的 Discord Token 手动获取教程及安全注意事项。
    *   优化了设置界面的交互细节。

### v1.1 (2024-05-22) - 资源同步与自动化增强
*   **✨ 新增：卡片更新检测系统**
    *   支持检测来自 **Chub.ai** 的角色卡更新（基于版本号和修改时间）。
    *   支持检测 **Discord 论坛/帖子** 链接的更新。支持识别帖子名称变更、文件大小变动或发布时间更新。
*   **🌟 新增：一键检测收藏更新**
    *   在顶部工具栏增加了一个“刷新”按钮，可针对所有“收藏”的角色卡进行批量在线比对。
*   **🔑 新增：Discord Token 配置**
    *   在设置中可配置 Discord User Token 或 Bot Token，以便程序能够访问需要权限的频道或提高 API 访问频率上限。
*   **🎨 界面优化**
    *   侧边栏底部增加版本号显示及项目链接。
    *   优化了卡片详情页的“检测更新”交互体验。
*   **⚙️ 内部改进**
    *   改进了配置保存机制，确保后台服务能即时感知配置变更。
    *   增强了扫码器的稳定性。

### v1.0
*   基础功能发布：可视化管理角色卡、世界书、批量标签、资源迁移等。
