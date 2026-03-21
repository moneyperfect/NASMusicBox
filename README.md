# NAS Local

本仓库是本地版，和线上版本完全隔离，目标是把它打造成稳定可用的个人桌面音乐终端。

## 启动方式

### 桌面模式（推荐）

在仓库根目录双击：

```bash
start-desktop.bat
```

它会：

1. 检查并按需构建前端。
2. 拉起本地后端或复用已经健康的 NAS 后端。
3. 打开 NAS 桌面壳，提供托盘、迷你播放器、全局快捷键和开机自启开关。

### 浏览器模式（备用）

如果你更想继续用浏览器访问：

```bash
start-local.bat
```

这会转到浏览器模式并打开 `http://localhost:8010`。

## 常用参数

```bash
start-desktop.bat --rebuild
start-desktop.bat --kill-port
start-desktop.bat --browser
```

- `--rebuild`：强制重新构建前端。
- `--kill-port`：清理占用 `8010` 端口的进程后再启动。
- `--browser`：不打开桌面壳，直接用浏览器模式启动。

## 首次安装

### Backend

```bash
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## 桌面能力

桌面壳默认包含：

- 系统托盘菜单
- 迷你播放器窗口
- 全局快捷键
- 开机自启开关

默认快捷键：

- `Ctrl + Alt + Space`：播放 / 暂停
- `Ctrl + Alt + Left`：上一首
- `Ctrl + Alt + Right`：下一首
- `Ctrl + Alt + Up`：音量增加
- `Ctrl + Alt + Down`：音量减小
- `Ctrl + Alt + M`：显示或隐藏迷你播放器

开机自启可在托盘菜单里的 `Launch at Login` 切换。

## 手动启动

只启动后端：

```bash
python main.py
```

然后访问：

```bash
http://localhost:8010
```

只启动桌面壳：

```bash
python desktop_app.py
```

## API

- `GET /health`
- `GET /system-check`
- `POST /search`
- `POST /visualize`
- `GET /proxy-stream?url=...`
- `GET /library`
- `GET /lyrics`
- `GET /lyrics-offset`

## 常见问题

### 页面提示前端未构建

运行：

```bash
start-desktop.bat --rebuild
```

### 端口 8010 被占用

运行：

```bash
start-desktop.bat --kill-port
```

### 播放失败或中断

- 先暂停再播放一次。
- 换一个搜索结果重试。
- 确认 `tools/ffmpeg/bin/ffmpeg.exe` 存在，或者系统 PATH 已包含 ffmpeg。
