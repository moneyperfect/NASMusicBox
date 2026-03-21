# NAS音乐器

NAS音乐器是一个面向个人使用的本地音乐播放器与下载器，提供搜索、播放、歌词、收藏、桌面壳、迷你播放器和本地资料库能力。

## 本地启动

推荐使用桌面模式：

```powershell
start-desktop.bat
```

如果希望直接以沉浸式全屏进入桌面端：

```powershell
start-desktop.bat --fullscreen
```

浏览器备用模式：

```powershell
start-local.bat
```

## 开发依赖

后端：

```powershell
pip install -r requirements.txt
```

前端：

```powershell
cd frontend
npm install
```

开发测试与打包工具：

```powershell
pip install -r requirements-dev.txt
```

## 核心能力

- YouTube 搜索容错与排序增强
- 本地 SQLite 收藏、历史、搜索、下载记录
- 下载中心，支持顺序队列、进度跟踪与失败重试
- 多源歌词与歌词偏移持久化
- 桌面托盘、迷你播放器、全局快捷键、开机启动
- GitHub Release 自动更新检查
- 沉浸式全屏模式，可通过托盘菜单或 `Ctrl + Alt + Enter` 切换

## 桌面打包

先生成图标并构建桌面包：

```powershell
.\scripts\build-desktop.ps1
```

输出目录：

```text
dist\NASMusicBox
```

如果只想刷新图标资源：

```powershell
python scripts\generate_app_assets.py
```

## Windows 安装包

需要先安装 Inno Setup 6。

```powershell
.\scripts\build-installer.ps1
```

输出目录：

```text
dist\release
```

## GitHub Actions

项目内置了两条工作流：

- `CI`：运行 Python 编译检查、`pytest`、前端构建、桌面打包冒烟
- `Release Desktop`：在 `v*` tag 或手动触发时构建便携版 zip 和安装包 exe

发布建议流程：

1. 更新 `app_meta.py` 和 `frontend/package.json` 中的版本号
2. 提交代码并推送
3. 创建形如 `v1.2.0` 的 Git tag
4. GitHub Actions 自动生成 Release 产物

## 声明

本项目公开仅供学习交流与个人技术研究使用。

项目中的搜索、播放、歌词与下载相关代码，仅用于演示桌面应用、前后端协作、媒体处理与本地资料库管理等技术方案。我们不对任何人滥用本项目代码进行牟利、批量爬取、侵犯版权、绕过平台规则，或从事其他非法活动承担任何责任。

使用者应自行遵守所在地区的法律法规、平台服务条款以及相关版权要求。

## 测试

```powershell
python -m pytest
```

## 目录说明

- `main.py`：FastAPI 后端
- `desktop_app.py`：桌面壳入口，支持 `--backend`
- `app_meta.py`：版本、品牌、仓库与端口元数据
- `app_paths.py`：开发态与打包态共享路径
- `desktop_updater.py`：GitHub Release 检查与下载
- `packaging/`：PyInstaller 与 Inno Setup 配置
- `tests/`：核心后端与更新逻辑测试
