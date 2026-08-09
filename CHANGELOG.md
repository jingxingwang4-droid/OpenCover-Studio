# 更新日志

## 0.1.0 - 2026-08-09

- 创建 PySide6 Qt Widgets 桌面壳、七个中文页面和系统托盘。
- 添加 RVC/DDSP 模型注册、哈希去重、安全导入、头像与真实试听管理。
- 添加 SQLite 任务历史、QProcess worker、JSON Lines 协议与取消能力。
- 添加组件/硬件探测、安全下载/解压、FFmpeg 音频标准化与响度混音模块。
- 添加资源研究、许可证边界、Modern/Legacy 构建脚本和测试。
- 修复双击 `app.py` 时系统 Python 找不到 PySide6/项目源码而静默退出的问题，自动切换项目 `pythonw.exe`。
- 固定并安装 MSST、RVC、DDSP 源码；MSST MDX23C 和 RVC 在 RTX 5070 Ti 上对《春日影》完成真实 CUDA smoke test。
- 移除 worker 的阶段性硬停止，接通 GUI 原词翻唱全链路、进度事件、WAV/FLAC/MP3 导出与结果缓存。
- DDSP、祥子双模型与改词扩展仍保持未验证状态。
