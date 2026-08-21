# OpenCover Studio

OpenCover Studio 是面向 Windows 普通用户的本地歌曲翻唱桌面应用。当前仓库是 **v0.1.0 阶段性可运行版本**：桌面 GUI、RVC/DDSP 模型导入与编辑、独立任务、SQLite、安全下载、音频标准化、分离、转换、混音与真实试听均已实现。

首页会从 SQLite 显示最近完成任务，并从本地模型注册表显示推荐音色；原词和改词页都能在提交前播放输入歌曲。音色管理支持名称/简介/语言搜索、推荐优先/名称/最近使用排序、置顶与隐藏内置。设置页会即时保存显存模式、下次启动默认格式和托盘关闭行为。

“改词翻唱 Beta”现已接入 GUI 和 JobManager：支持粘贴或导入 UTF-8/GBK/Shift-JIS 的 TXT/LRC，并可选上传 `.mid/.midi` 旋律文件。上传 MIDI 后会读取速度变化、自动选择非鼓组主旋律轨道并对齐 LRC 时间轴；未上传时由 GAME 从原唱提取旋律。自动模式会先将原唱逐字边界映射到连续 F0 复核后的 GAME 音符，再用本机 legacy OpenCpop DiffSinger 按谱生成；同一《惊鹊》短句的实测中文吐字优于当前 VISinger2。完整链路执行 MSST/UVR5 → LRC/Whisper 强制对齐 → GAME/MIDI + 连续 F0 → DiffSinger → 逐句 RVC 后校时拼接 → 混音。VISinger2 保留为 DiffSinger 不可用时的按谱后备；两套权重的许可与发行边界见资源清单。

该功能仍不具备已验证的跨歌曲泛用性。《惊鹊》首句复听仍发现“柳絮满长街”听感跑调，且当前 Sakiko RVC 会明显破坏普通话音素。现阶段只建议将“普通话、清晰单主唱、新旧歌词汉字数相同、每句 3～15 秒”作为实验输入；不同字数、快歌、说唱、密集转音、和声/混响重、非中文或未经逐句人工试听的结果都不能视为可靠成品。

## 本地开发运行

要求 Windows 10/11 与 Python 3.10 或 3.11：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python app.py
```

仓库已配置好 `.venv` 时可直接双击 `app.py`；启动器会自动切换到项目的 `pythonw.exe`，不会弹出终端窗口。普通用户优先双击发行目录中的 `OpenCoverStudio-NVIDIA-Modern.exe`。

程序不会打开浏览器，也不会启动 Web 服务。GUI 推理任务由 `QProcess` 启动独立 worker，第三方后端仅通过参数列表调用，禁止 `shell=True`。

## 使用流程

1. 在“组件管理”确认 FFmpeg、分离组件以及 RVC 或 DDSP 已经安装且通过真实 smoke test。
2. 在“音色管理”或“原词翻唱”点击“导入音色”。RVC 接受 `.pth/.pt` 和可选 `.index`；DDSP 接受 `.pt/.ckpt` 和配套 `.yaml/.yml`，导入后统一保存为上游要求的 `config.yaml`。
3. 试听可明确选择“自动生成 / 上传 / 暂不生成”。上传支持 WAV/FLAC/MP3/M4A，经 FFmpeg 限长并统一为 `preview.wav`；自动模式优先用本机《惊鹊》第一句干声（存在时），否则回退到 CC0 标准干声，并始终通过目标模型真实推理。
4. 拖入歌曲，选择 RVC 或 DDSP 音色并点击“开始翻唱”。分离、改词生成、音色转换、混音和格式分别缓存；换混音或格式不会重复模型推理。
5. 改词页优先使用带时间戳 LRC；如有对应旋律 MIDI，可在“旋律 MIDI（可选）”上传。完整歌曲 MIDI 应保留从歌曲 0 秒开始的时间轴；只含人声旋律、从 0 秒开始的 MIDI 也会尝试自动对齐到第一句 LRC。纯文本原歌词在对齐组件可用时会用 Stable-ts + Whisper 强制对齐到 MSST 人声，否则长音频明确要求 LRC。每句被限制在约 3～15 秒范围，新歌词密度超出所选“保守/均衡/强制”策略时会明确拒绝。
6. “任务记录”可直接重新生成，或为原词/改词/试听任务更换同引擎音色后再生成；播放器提供独立音量滑块。历史表显示音色头像，并可导出包含 `job.json`、`request.json` 与 `worker.log` 的 ZIP 日志包。

每个 worker 的标准输出、标准错误和退出状态都会按 UTC 时间写入任务目录。应用异常退出后，下一次启动会把遗留的 `pending/running` 任务标记为可重新生成的失败记录；运行期间托盘菜单和提示文字显示任务 ID、进度与当前阶段。

RVC 转换若捕获到明确的 CUDA OOM，会等待失败的后端子进程退出并释放 CUDA 上下文，再按显存模式使用 8～45 秒分段有限重试；次数有限，仍失败时任务记录显示 `CUDA_OOM`，不会无限循环。“极低/低”模式还会把显式 Vevo2 路径的 flow steps 从标准 32 降到 16/24。改词歌声会在每个生成短句仍未做全曲校时前逐句 RVC，并只加载一次音色模型，避免前后静音和整轨时伸破坏辅音、短转音。

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

`./scripts/build_local_full.ps1 Modern` 可在 `release_private/OCS-Private-Modern` 组装仅供同一用户在自己电脑之间迁移的完整目录。组装器为 MSST、UVR5、RVC、DDSP、Vevo2、GAME、Whisper 对齐和 VISinger2 环境嵌入包内 Python 基础运行时，移除 `pyvenv.cfg` 与 RVC editable 绝对路径；目标电脑无需 Python、Conda 或 CUDA Toolkit，但仍需要兼容的 64 位 Windows、NVIDIA 显卡和驱动。该包含受限社区模型，只能遵守 `LOCAL_ONLY_FULL_PACKAGE.txt` 私人使用，不能公开上传。DDSP 资源可用 `./scripts/restore_ddsp_resources.ps1 -Install` 按固定来源、大小和 SHA-256 自动恢复。

源码环境可运行 `./scripts/install_alignment.ps1` 安装固定版本的对齐扩展；脚本使用独立 Python 3.10 环境、核验官方 Whisper 模型 SHA256，并且只有真实 CUDA 强制对齐 smoke 通过后才写入可用 marker。Stable-ts 上游已于 2026-05-30 归档，此维护风险会保留在组件说明中。

## 安全与版权

- 原创代码采用 MIT；Qt/PySide6、FFmpeg、后端、模型、权重、音频和图片各自遵守其许可证。
- 模型导入计算 SHA256、拒绝重复和覆盖，不执行模型目录中的脚本。
- 组件页现可从核验清单启动独立下载 worker，支持断点、自动重试、速度/进度、取消、缓存复用、大小与 SHA256 校验。安装器拒绝 HTML 冒充文件、路径穿越、符号链接、异常压缩比、越界和覆盖已有文件；下载成功不等于后端可用，界面仍以真实 smoke test 为准。
- 请仅使用得到授权的歌曲、模型、角色素材和训练数据。

## 开发致谢

OpenCover Studio 的需求整理、实现、测试、打包与仓库维护过程中使用了 [OpenAI Codex](https://developers.openai.com/codex/) 作为开发辅助工具。项目决策、发布与责任归项目所有者。
