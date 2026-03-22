# NAS音乐器

NAS音乐器是一个面向个人使用的本地音乐播放器与下载器，提供搜索、播放、歌词、收藏、下载中心、桌面壳、迷你播放器和本地资料库能力。

[![Windows 安装版下载](https://img.shields.io/badge/Windows-下载安装包-2ea043?style=for-the-badge&logo=windows11)](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-Setup.exe)
[![Windows 便携版下载](https://img.shields.io/badge/Windows-便携版ZIP-0a84ff?style=for-the-badge&logo=windows11)](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-portable.zip)

## Windows 一键下载

- 安装版 exe：[`NASMusicBox-Setup.exe`](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-Setup.exe)
- 便携版 zip：[`NASMusicBox-portable.zip`](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-portable.zip)

如果你只想直接使用，优先下载安装版。便携版适合不想安装、想临时体验或放在移动目录中运行的场景。

## 三步安装

1. 下载 [`NASMusicBox-Setup.exe`](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-Setup.exe)。
2. 双击安装，按向导完成安装；如有需要，可以勾选创建桌面图标。
3. 安装完成后，从桌面或开始菜单打开 NAS音乐器。应用启动后会在系统托盘驻留，可从托盘执行显示、隐藏、沉浸式全屏、检查更新和退出等操作。

如果你想免安装运行：

1. 下载 [`NASMusicBox-portable.zip`](https://github.com/moneyperfect/NASMusicBox/releases/latest/download/NASMusicBox-portable.zip)。
2. 解压到任意目录。
3. 双击 `NASMusicBox.exe` 启动。

## 常见问题

- Windows 提示“未知发布者”或 SmartScreen 警告怎么办？
  目前发布包未做代码签名，首次运行可能出现系统提示。请确认下载来源是本仓库的 GitHub Releases，再选择继续运行。
- 打不开桌面端怎么办？
  请优先确认系统可正常使用 Microsoft Edge WebView2 运行时，以及本机网络没有拦截本地 `127.0.0.1:8010` 回环请求。
- 安装版和便携版有什么区别？
  安装版会创建开始菜单和可选桌面快捷方式，更适合长期使用。便携版无需安装，解压即可运行，适合快速体验。
- 数据保存在哪里？
  用户数据默认保存在 `%LOCALAPPDATA%\NASMusicBox\data`，包括收藏、历史、歌词偏移、下载记录和桌面缓存。安装版程序默认安装到 `%LOCALAPPDATA%\Programs\NASMusicBox`。

## 功能亮点

- YouTube 搜索容错与排序增强
- 本地 SQLite 收藏、历史、搜索、下载记录
- 下载中心，支持顺序队列、进度跟踪与失败重试
- 多源歌词与歌词偏移持久化
- 桌面托盘、迷你播放器、开机启动
- GitHub Release 自动更新检查
- 沉浸式全屏模式，可通过托盘菜单或 `start-desktop.bat --fullscreen` 启动
- 托盘菜单已统一为中文项，便于长期使用

## 源码运行

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

## 本地打包

先生成图标并构建桌面包：

```powershell
.\scripts\build-desktop.ps1
```

输出目录：

```text
dist\NASMusicBox
```

构建 Windows 安装包：

```powershell
.\scripts\build-installer.ps1
```

输出目录：

```text
dist\release
```

如果只想刷新图标资源：

```powershell
python scripts\generate_app_assets.py
```

## GitHub Release 发布

项目内置了两条工作流：

- `CI`：运行 Python 编译检查、`python -m pytest`、前端构建、桌面打包冒烟
- `Release Desktop`：在 `v*` tag 或手动触发时构建安装版 exe 和便携版 zip，并上传到 GitHub Release

发布建议流程：

1. 更新 `app_meta.py` 和 `frontend/package.json` 中的版本号
2. 提交代码并推送
3. 创建形如 `v1.2.4` 的 Git tag
4. GitHub Actions 自动生成 Release 产物

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

## 声明

本项目公开仅供学习交流与个人技术研究使用。

项目中的搜索、播放、歌词与下载相关代码，仅用于演示桌面应用、前后端协作、媒体处理与本地资料库管理等技术方案。我们不对任何人滥用本项目代码进行牟利、批量爬取、侵犯版权、绕过平台规则，或从事其他非法活动承担任何责任。

使用者应自行遵守所在地区的法律法规、平台服务条款以及相关版权要求。
