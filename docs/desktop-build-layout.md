# 桌面版文件夹说明

这次开始，桌面版构建产物会固定整理成下面这套结构：

```text
dist/
  Open-Latest-NASMusicBox.bat
  LATEST-VERSION.txt
  NASMusicBox/
  versions/
    NASMusicBox-v1.5.1/
  release/
    NASMusicBox-Setup.exe
    NASMusicBox-portable.zip
```

## 应该打开哪个文件

- 日常本地使用：直接双击 `dist\Open-Latest-NASMusicBox.bat`
- 想确认当前最新版本：打开 `dist\LATEST-VERSION.txt`
- 想看具体某个版本：进入 `dist\versions\NASMusicBox-v版本号\`
- 安装包：`dist\release\NASMusicBox-Setup.exe`
- 便携版压缩包：`dist\release\NASMusicBox-portable.zip`

## 这样做的原因

- `dist\NASMusicBox\` 仍然保留给构建工具使用，避免影响原有打包链路
- `dist\versions\NASMusicBox-v版本号\` 用来保存当前版本归档，方便识别
- `dist\Open-Latest-NASMusicBox.bat` 提供稳定入口，不再需要靠修改时间猜测
- 便携版压缩包现在会带版本号根目录，解压多个版本时不会把文件混在一起

## 推荐习惯

- 平时只认 `dist\Open-Latest-NASMusicBox.bat`
- 不要再直接去多个旧文件夹里找 `NASMusicBox.exe`
- 如果需要保留多个版本，请只在 `dist\versions\` 下查看和管理
- 更新桌面版前，先完全退出正在运行的 NAS，包括托盘里的旧实例
