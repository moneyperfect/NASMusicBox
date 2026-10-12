# NAS音乐器下载网站

静态成品位于 `dist/`，无依赖安装或构建步骤。正式域名：`music.nasbuild.dev`。

从软件仓库根目录运行 `python scripts/preview-download-site.py`，打开 `http://127.0.0.1:5349`。预览服务器只开放网站文件与两个指定安装包，不开放资料库或整个仓库。完成本地打包并生成 `dist/release/release-manifest.json` 后，本机下载自动可用。

`dist/release.json` 管理版本、大小、SHA-256 和正式下载地址。公开发布安装包并检查链接后填入 `publicUrl`、设置 `published: true`；公开网站从不回退到旧版 latest，也不访问本机下载路径。

现有截图来自实际软件的演示曲目。界面预览标签支持方向键，页面适配手机与减少动态效果设置。不添加统计追踪或第三方脚本。
