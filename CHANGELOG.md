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
- 安装 DDSP-SVC 6.3 独立运行时及 ContentVec、RMVPE、PC-NSF-HiFiGAN，完成 30 秒与《春日影》全曲真实 CUDA 推理。
- 安装并安全扫描非官方祥子 RVC/DDSP 社区模型；完成两条全曲 worker 输出、带 index RVC 中文路径兼容和共享分离阶段缓存。
- 加入 CC0 的 9.008 秒真实清唱标准干声；目标 RVC/DDSP 均真实生成试听，音色卡可播放，用户导入无试听时会启动独立后台任务。
- 修复 JobManager 根路径参数、DDSP 输出目录和 RVC/FAISS 中文路径问题；pytest 增至 15 项全通过。
- 改词扩展仍保持未验证状态，非官方角色权重仍禁止进入公开发行包。
- 固定并安装 Amphion Vevo2 4.28 GB 推理权重，真实生成中文/日文 9.16 秒 WAV，峰值 CUDA 7.91 GB。
- 固定 GAME 源码与 v1.0 small 模型，对《春日影》30 秒人声真实导出 MIDI/TXT/CSV；记录 DiffSinger 官方分支缺少歌声模型的阻塞状态。
