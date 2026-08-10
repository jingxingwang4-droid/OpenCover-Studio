# OpenCover Studio

OpenCover Studio 是面向 Windows 普通用户的本地歌曲翻唱桌面应用。当前仓库是 **v0.1.0 阶段性可运行版本**：桌面 GUI、模型导入/编辑、独立任务、SQLite、安全下载、音频标准化/分离/转换/混音与真实试听均已实现；MSST + RVC 和 MSST + DDSP 都在本机对 `assets/audio/春日影.wav` 完成了真实 CUDA 全曲推理。

首页会从 SQLite 显示最近完成任务，并从本地模型注册表显示推荐音色；原词和改词页都能在提交前播放输入歌曲。音色管理支持名称/简介/语言搜索、推荐优先/名称/最近使用排序、置顶与隐藏内置。设置页会即时保存显存模式、下次启动默认格式和托盘关闭行为。

“改词翻唱 Beta”现已接入 GUI 和 JobManager：支持粘贴或导入 UTF-8/GBK/Shift-JIS 的 TXT/LRC，执行 MSST → LRC/逐行短句规划 → Vevo2 → 时长拼接 → RVC/DDSP → 混音。Vevo2 不可用或推理失败时，会自动切换到 GAME 提取旋律 → 中文字符映射 → 原版 DiffSinger OpenCpop 模型合成 → RVC/DDSP。主路径和回退路径都已生成真实、非静音 WAV。无时间戳的长歌曲仍会要求用户提供 LRC；DiffSinger 回退当前只支持含中文汉字的歌词，且其旧版权重许可不明确，只进入本机完整包，不进入公开发行包。

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

1. 在“组件管理”确认 FFmpeg、MSST 与 RVC 或 DDSP 已经安装且通过真实 smoke test。
2. 在“音色管理”或“原词翻唱”点击“导入音色”。RVC 接受 `.pth` 和可选 `.index`；DDSP 接受 `.pt/.ckpt` 和可选配置。
3. 试听可明确选择“自动生成 / 上传 / 暂不生成”。上传支持 WAV/FLAC/MP3/M4A，经 FFmpeg 限长并统一为 `preview.wav`；自动模式用 CC0 标准干声和目标模型真实推理。
4. 拖入歌曲，先选 RVC/DDSP，再选对应音色，点击“开始翻唱”。分离、改词生成、音色转换、混音和格式分别缓存；换混音或格式不会重复模型推理。
5. 改词页优先使用带时间戳 LRC。每句被限制在约 3～15 秒范围，新歌词密度超出所选“保守/均衡/强制”策略时会明确拒绝。
6. “任务记录”可直接重新生成，或为原词/改词/试听任务更换同引擎音色后再生成；播放器提供独立音量滑块。

RVC/DDSP 转换若捕获到明确的 CUDA OOM，会等待失败的后端子进程退出并释放 CUDA 上下文，再按显存模式使用 8～45 秒分段有限重试；次数有限，仍失败时任务记录显示 `CUDA_OOM`，不会无限循环。“极低/低”模式还会把 Vevo2 flow steps 从标准 32 降到 16/24。Vevo2 主路径失败时自动切换 GAME + DiffSinger。实体低显存显卡上的 OOM/Legacy 兼容性仍需独立验收。

`assets/preview_sources/neutral_melody.wav` 来自 owstu 在 Freesound 发布的 CC0 清唱素材，9.008 秒。当前本机另安装并验证了 TogetsuDo 的丰川祥子 RVC/DDSP 社区模型；它们均为非官方且没有明确再分发许可，因此被 `.gitignore` 排除，也不会打入公开发行包。资源真实状态详见 `config/resource_manifest.yaml` 与 `docs/RESOURCE_RESEARCH.md`。

若 `assets/背景1.*` 存在，GUI 优先将其用作固定背景并添加浅色内容蒙层；背景 2/3 保留但不轮播。`assets/祥子音色头像.jpg` 用于尚未安装的祥子固定音色占位卡，不代表相关 RVC/DDSP 权重已获得授权或通过推理。

## 构建

```powershell
./scripts/build_windows.ps1 Modern
./scripts/build_windows.ps1 Legacy
```

构建脚本生成 windowed GUI 和独立 `OpenCoverStudioWorker.exe`。Qt 以 `CREATE_NO_WINDOW` 启动 worker，因此没有可见终端，同时保留 UTF-8 JSON Lines 进度、SQLite 状态和进程树取消。公开 Modern/Legacy 阶段包含 GUI、worker、顶层 assets/config、FFmpeg 与 CC0 试听源；受限制权重不进入公开包。

`./scripts/build_local_full.ps1 Modern` 另可在 `release_private/` 组装当前机器专用的 23.61 GiB 完整目录；它包含不可再分发的社区模型、Vevo2、GAME、旧版 DiffSinger 权重和绑定本机解释器路径的虚拟环境，必须遵守 `LOCAL_ONLY_FULL_PACKAGE.txt`，不能公开上传。该私有包的冻结 worker 已完成 Vevo2 主路径与 GAME + DiffSinger 回退路径端到端测试。Legacy 尚无实体旧显卡/CUDA 11.8 验收，不宣称已兼容。

## 安全与版权

- 原创代码采用 MIT；Qt/PySide6、FFmpeg、后端、模型、权重、音频和图片各自遵守其许可证。
- 模型导入计算 SHA256、拒绝重复和覆盖，不执行模型目录中的脚本。
- 组件页现可从核验清单启动独立下载 worker，支持断点、自动重试、速度/进度、取消、缓存复用、大小与 SHA256 校验。安装器拒绝 HTML 冒充文件、路径穿越、符号链接、异常压缩比、越界和覆盖已有文件；下载成功不等于后端可用，界面仍以真实 smoke test 为准。
- 请仅使用得到授权的歌曲、模型、角色素材和训练数据。
