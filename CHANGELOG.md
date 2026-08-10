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
- 接通改词 GUI/JobManager：TXT/LRC 多编码解析、短句规划、三档歌词密度、Vevo2 批量生成、时长拼接、RVC/DDSP、混音和分层缓存。
- 新增专用 `OpenCoverStudioWorker.exe`；Qt 隐藏启动仍保留 UTF-8 JSON Lines，修复 onefile TEMP 环境和中文路径乱码，实测 Vevo2 阶段取消无孤儿进程。
- 音色导入新增自动/上传/暂不生成试听，上传支持 WAV/FLAC/MP3/M4A；音色卡增加管理入口，可改名称、简介、语言、Key、头像/试听并删除用户模型。
- 修复 DDSP 用户配置必须命名 `config.yaml`、后端错误 GBK/UTF-8 解码、换混音误返旧缓存、模型哈希未进入转换缓存等问题。
- 新增真实 CUDA/FP16、Compute Capability、RAM/磁盘检测；pytest 增至 24 项。
- 组装并验证 22.76 GiB `Modern-LocalFull` 私有包；公开包继续排除不可再分发权重。
- 组件管理页接入可取消的资源 worker：断点、重试、速度/进度、缓存、大小/SHA256、安全解压和拒绝覆盖；下载完成后仍以真实后端 smoke test 判定可用状态。
- 固定原版官方 DiffSinger demo 与 OpenCpop/NSF-HiFiGAN 权重，接通 GAME 旋律提取、中文字符映射、批量 DiffSinger 合成及 Vevo2 失败自动回退；固定样例、动态旋律与完整祥子 RVC 混音均生成真实非静音 WAV。
- 历史任务新增“重新生成”和“更换音色生成”，音频播放器新增音量滑块；改词页在仅 GAME + DiffSinger 就绪时也可启动。
- RVC/DDSP 与试听转换新增 CUDA OOM 分类、失败子进程退出、30/15 秒分段有限重试和 `CUDA_OOM` 错误码；单元测试验证交叉淡化拼接，实体低显存硬件仍保守标为未验收。
- pytest 增至 33 项，新增改词生成器、缺失可选 marker、GAME 音符映射、历史操作、音量控制和 OOM 降级覆盖。
