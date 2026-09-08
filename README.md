# OpenCover Studio

OpenCover Studio 是面向 Windows 普通用户的本地歌曲翻唱桌面应用。当前仓库是 **v0.1.0 阶段性可运行版本**：桌面 GUI、RVC/DDSP 模型导入与编辑、独立任务、SQLite、安全下载、音频标准化、分离、转换、混音与真实试听均已实现。

首页会从 SQLite 显示最近完成任务，并从本地模型注册表显示推荐音色；原词和改词页都能在提交前播放输入歌曲。音色管理支持名称/简介/语言搜索、推荐优先/名称/最近使用排序、置顶与隐藏内置。设置页会即时保存显存模式、下次启动默认格式和托盘关闭行为。

“改词翻唱 Beta”固定使用 UVR5 → 原词逐字对齐 → GAME 与连续 F0 复核 → DiffSinger → 可选音色转换 → 区间混音导出。默认使用原生中文歌声，优先保留吐字；仍可选择 RVC/DDSP 音色。用户只需上传原曲、填写或导入新旧歌词，并选择音色、升降调和输出格式；内部词谱自动生成。新旧歌词按行对应，允许在同一句增减字词，不要求上传 MIDI 或元数据。

只重新生成歌词发生变化的句子。音符、停顿和句长保留在原时间轴上，词谱与音素经过数量、时值和音高检查；缺失发音、无效对齐、静音或异常时长会明确失败。改词区间移除旧歌词和声，区间外直接复用原曲采样。分离、生成和音色转换分别缓存，缓存结果经过完整性校验。

历史 SoulX、ACE-Step、VISinger2 和 Vevo2 实现保留于历史模块及原目录，当前产品入口不使用，也不在失败时切换。原词翻唱功能仍保留原有分离、RVC/DDSP 和混音能力。

当前改词默认采用已经认可的 C 处理流程：连续元音承载转音、35 ms 音高柔化、按句均衡音量，并自动匹配所有改词边界的伴奏电平。普通歌词也会自动对齐，无需人工设置修复时间点。完整说明见 [改词翻唱通用工作流](docs/LYRIC_WORKFLOW.md)。

技术校验不代表听感验收。当前中文 OpenCpop 模型、自动逐字对齐和所选音色仍需逐句核对吐字、旋律及混音中的旧词残留；真实回归结果记录于本地任务目录。

## 本地开发运行

要求 Windows 10/11 与 Python 3.10 或 3.11：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python app.py
```

仓库已配置好 `.venv` 时可直接双击 `app.py`；启动器会自动切换到项目的 `pythonw.exe`，不会弹出终端窗口。本机使用下述已更新入口；独立发行包使用其目录内对应的启动程序。

本机已更新的改词入口是项目根目录 `OpenCoverStudio.exe`，与同目录 worker、运行库和现有后端一起使用。可通过 `.venv\Scripts\python.exe scripts\build_local_app.py` 重新构建；此入口使用本机项目资源，不是独立便携发行包。

程序不会打开浏览器，也不会启动 Web 服务。GUI 推理任务由 `QProcess` 启动独立 worker，第三方后端仅通过参数列表调用，禁止 `shell=True`。

## 使用流程

1. 在“组件管理”确认 FFmpeg、分离组件以及 RVC 或 DDSP 已经安装且通过真实 smoke test。
2. 在“音色管理”或“原词翻唱”点击“导入音色”。RVC 接受 `.pth/.pt` 和可选 `.index`；DDSP 接受 `.pt/.ckpt` 和配套 `.yaml/.yml`，导入后统一保存为上游要求的 `config.yaml`。
3. 试听可明确选择“自动生成 / 上传 / 暂不生成”。上传支持 WAV/FLAC/MP3/M4A，经 FFmpeg 限长并统一为 `preview.wav`；自动模式优先用本机《惊鹊》第一句干声（存在时），否则回退到 CC0 标准干声，并始终通过目标模型真实推理。
4. 拖入歌曲，选择 RVC 或 DDSP 音色并点击“开始翻唱”。分离、改词生成和音色转换分别缓存；换混音或格式可复用已校验的推理结果。
5. 在改词页填写或导入新旧歌词 TXT/LRC，也可先自动识别再校对。请保持行数对应；未修改的行保留原词。后台自动对齐和构谱，组件缺失或无法可靠分配歌词时明确报错。输出试听文件包括生成主唱、转换后主唱、已移除的旧和声和最终混音。
6. “任务记录”可直接重新生成，或为原词/改词/试听任务更换同引擎音色后再生成；播放器提供独立音量滑块。历史表显示音色头像，并可导出包含 `job.json`、`request.json` 与 `worker.log` 的 ZIP 日志包。

每个 worker 的标准输出、标准错误和退出状态都会按 UTC 时间写入任务目录。应用异常退出后，下一次启动会把遗留的 `pending/running` 任务标记为可重新生成的失败记录；运行期间托盘菜单和提示文字显示任务 ID、进度与当前阶段。

原词翻唱的 RVC 转换若捕获到明确的 CUDA OOM，会等待失败的后端子进程退出并释放 CUDA 上下文，再按显存模式使用 8～45 秒分段有限重试；次数有限，仍失败时任务记录显示 `CUDA_OOM`，不会无限循环。改词任务选择 RVC 时逐句转换，并只加载一次音色模型；原生歌声无需音色转换。生成短句按原时间轴拼接，避免整轨时伸破坏辅音、短转音。

`assets/preview_sources/jingque_first_line.wav` 是从用户本机《惊鹊》测试曲的真实分离主唱中截取的 5.52 秒片段，只用于本机音色试听，不进入 Git 或公开发行包。没有该本机片段时，程序使用 owstu 在 Freesound 发布的 9.008 秒 CC0 清唱素材 `neutral_melody.wav`。两种源音频都只能作为模型输入，不会直接冒充转换结果。当前本机的丰川祥子 RVC 模型来源和再分发许可未知，因此被 `.gitignore` 排除，也不会打入公开发行包。资源状态详见 `config/resource_manifest.yaml`。

RVC 当前只保留白菜 357k 与丰川祥子两套本机音色。DDSP 已恢复丰川祥子及此前用于兼容验证的可可萝社区模型。角色衍生模型的训练数据或再分发权利均未完整核验，因此不会随公开发行包分发。

若 `assets/背景1.*` 存在，GUI 优先将其用作固定背景并添加约 68% 不透明的浅色内容蒙层；背景 2/3 保留但不轮播。`assets/祥子音色图标.jpg` 用作祥子音色头像及尚未安装时的占位卡，`assets/图标.jpg` 用作软件与系统托盘图标；这些图片不代表相关 RVC 权重已获得授权。

## 构建

```powershell
./scripts/build_windows.ps1 Modern
./scripts/build_windows.ps1 Legacy
```

构建脚本生成 windowed GUI 和独立 `OpenCoverStudioWorker.exe`。Qt 以 `CREATE_NO_WINDOW` 启动 worker，因此没有可见终端，同时保留 UTF-8 JSON Lines 进度、SQLite 状态和进程树取消。公开 Modern/Legacy 阶段包含 GUI、worker、顶层 assets/config、FFmpeg 与 CC0 试听源；受限制权重不进入公开包。

公开构建不会递归复制本机 `weights/`，因此白菜、祥子和其他本机模型不会意外进入公开包。

`./scripts/build_local_full.ps1 Modern` 可在 `release_private/OCS-Private-Modern` 组装仅供同一用户在自己电脑之间迁移的完整目录。当前私人测试版组装器仅为 MSST、UVR5、RVC、DDSP 环境嵌入包内 Python 基础运行时，改词功能仍限源码运行版。组装时移除 `pyvenv.cfg` 与 RVC editable 绝对路径；目标电脑无需 Python、Conda 或 CUDA Toolkit，但仍需要兼容的 64 位 Windows、NVIDIA 显卡和驱动。该包含受限社区模型，只能遵守 `LOCAL_ONLY_FULL_PACKAGE.txt` 私人使用，不能公开上传。DDSP 资源可用 `./scripts/restore_ddsp_resources.ps1 -Install` 按固定来源、大小和 SHA-256 自动恢复。

源码环境可运行 `./scripts/install_alignment.ps1` 安装固定版本的对齐扩展；脚本使用独立 Python 3.10 环境、核验官方 Whisper 模型 SHA256，并且只有真实 CUDA 强制对齐 smoke 通过后才写入可用 marker。Stable-ts 上游已于 2026-05-30 归档，此维护风险会保留在组件说明中。

## 安全与版权

- 原创代码采用 MIT；Qt/PySide6、FFmpeg、后端、模型、权重、音频和图片各自遵守其许可证。
- 模型导入计算 SHA256、拒绝重复和覆盖，不执行模型目录中的脚本。
- 组件页现可从核验清单启动独立下载 worker，支持断点、自动重试、速度/进度、取消、缓存复用、大小与 SHA256 校验。安装器拒绝 HTML 冒充文件、路径穿越、符号链接、异常压缩比、越界和覆盖已有文件；下载成功不等于后端可用，界面仍以真实 smoke test 为准。
- 请仅使用得到授权的歌曲、模型、角色素材和训练数据。

## 开发致谢

OpenCover Studio 的需求整理、实现、测试、打包与仓库维护过程中使用了 [OpenAI Codex](https://developers.openai.com/codex/) 作为开发辅助工具。项目决策、发布与责任归项目所有者。
