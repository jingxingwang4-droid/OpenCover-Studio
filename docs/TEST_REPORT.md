# 测试报告（2026-08-10）

## 私人跨电脑 Modern 包（2026-08-20）

完整便携运行时、冻结 GUI、真实 RVC/DDSP Worker 输出和目标笔记本未验收边界，见 `docs/PRIVATE_PACKAGE_VALIDATION_2026-08-20.md`。

## UI 背景与《惊鹊》音色试听复验（2026-08-17）

- 固定背景 1 的整页浅色蒙层从 alpha 232 降为 174，主面板改为 alpha 218–224；已生成 1200×760 正式 QSS 离屏截图 `workspace/validation/ui_background_after.png` 人工检查，背景主体可见，深色文字仍有浅色蒙层/面板承托。
- 在线核对的第一句为“白马过了离原，三月的天，春风漫草野”。已使用工作区现有真实 UVR5 分离主唱和 Whisper 1.98–7.04 秒对齐证据，截取为 5.520 秒、44.1 kHz、单声道 PCM16 本机干声，SHA256 `def173c3d7b3fa9a9b7e819d5c68062a2afaabd97d41534bb8a8cac7d5945114`。
- 5 个当前音色均经各自目标模型真实重建：祥子 DDSP `fff898d6...e5962`，可可萝 DDSP `37cb8de1...02e`，祥子本机 DDSP v2 `bccfd2d5...741e`，祥子 RVC `1d7f7814...e0065`，白菜 RVC `29622150...a626`。5 份输出哈希互不相同且与输入不同，时长 5.50–5.53 秒，平均音量 -13.9 至 -16.1 dB，峰值 -0.1 至 -1.9 dB，非静音。
- 定向 GUI/worker 4 项及当前全量 55 项 pytest 均通过。本机《惊鹊》 WAV 及原曲均被 Git/公开构建排除；公开包仍使用已核验 CC0 `neutral_melody.wav` 回退。

## DDSP 恢复复验（2026-08-13）

- DDSP-SVC 固定 commit `2e2ac5d34ffe08cb1a03fdffd51742e62b8bcf8c`；隔离环境为 Python 3.12、PyTorch/torchaudio 2.9.1+cu130，RTX 5070 Ti CUDA 可用，`pip check` 无依赖冲突。
- ContentVec：378,342,945 bytes，SHA256 `d8dd400e054ddf4e6be75dab5a2549db748cc99e756a097c496c099f65a4854e`。
- PC-NSF-HiFiGAN：官方 ZIP 52,675,337 bytes / SHA256 `9d98ba73727f2abb75172cf8249d75182237e8472fc3b6ed09c721ae8b0e83c6`；安装后模型 56,663,267 bytes / SHA256 `d6dd28909d2a1a2dcf74b3e3aa0b82b48695b87979fdf41561940aeecd85c67f`。
- RMVPE：官方 ZIP 340,638,958 bytes / SHA256 `54ae40d9c066d998b94574f6ef0deea19ed1565bd655b3f0d9b1ad612fb5309c`，Blob MD5 `2fec41d2c4b62170e850ef54c1d04fec` 与官方响应一致；内部模型 368,492,925 bytes / SHA256 `19dc1809cf4cdb0a18db93441816bc327e14e5644b72eeaae5220560c6736fe2`。此前文档中的 ZIP SHA256 有抄录错误，本轮已纠正。
- RMVPE、祥子和可可萝三个 checkpoint 的 unsafe globals 均为空，`torch.load(weights_only=True)` 均成功。
- 祥子 DDSP 对 CC0 标准干声真实 CUDA 输出 9.009342 秒、44.1 kHz、RMS 0.03544、peak 0.32010、finite/nonzero 均为 true，SHA256 `2c784ecd07599db579744c76263cc9b2b02d6e955e543b8f6e60ea9e8c3cc2f`。
- 可可萝 DDSP 对同一干声真实 CUDA 输出 9.009342 秒、44.1 kHz、RMS 0.04786、peak 0.18530、finite/nonzero 均为 true，SHA256 `e6c2dfeb3ce94c886c69ef383e73c65571676cc9ee0f875d4f9ba146f755a7b9`。
- OpenCover Studio 自己的 `DDSPAdapter` 再次完成真实转换，状态为 `installed=True, runnable=True`；最终 `.venv\Scripts\python.exe -m pytest -q` 为 `51 passed`，全量 Python 编译通过。

以下内容是 2026-08-10 的历史测试记录；其中当时的环境版本、公开音色和发行包数量不代表 2026-08-13 当前工作区状态。

## 环境与自动化

- Windows 10 build 26200；GUI Python 3.10.20；PySide6 6.11.1。
- NVIDIA GeForce RTX 5070 Ti Laptop GPU，12172 MiB，驱动 591.86，Compute Capability 12.0，驱动报告 CUDA 13.1。
- MSST/RVC 为 PyTorch 2.9.1+cu130；DDSP 为独立 Python 3.11.5、PyTorch/torchaudio 2.9.1+cu130；三者 CUDA tensor smoke test 均通过。
- FFmpeg 9.0 essentials build。
- 应用启动时调用后端 PyTorch 真实执行 CUDA FP16 tensor 运算：`cuda_smoke=True`、`fp16_supported=True`；Windows `GlobalMemoryStatusEx` 检出 31.4 GB RAM，本轮最终磁盘可用空间为 824.3 GB。
- `.venv\Scripts\python.exe -m pytest -q`：`38 passed`。覆盖歌词编码/LRC/密度限制、自动对齐语言判断/分段校验/adapter、公开内置音色固定白名单、Vevo2 与 DiffSinger 生成器选择、缺失可选 marker、GAME 音符映射、短句拼接、显存档位缓存/OOM 分段、DDSP `config.yaml` 导入规则、后端 UTF-8/GBK 错误透传、音色元数据编辑/置顶/删除、首页真实记录、输入播放器、设置持久化、异常任务恢复、worker 日志/ZIP 导出、历史操作、播放器音量，以及资源安装越界/覆盖/ZIP 符号链接防护。

## MSST

- 源码 commit `e247dfe4abc1f17c69dff719207fe045dc04413a`。
- MDX23C vocals SDR 10.17 checkpoint SHA256 `49d51472769e34a2501cd1da782346a3212555c3a5619fc2c53507445528d816`。
- 用户测试曲 `assets/audio/春日影.wav`：257.84 秒、44.1 kHz、立体声，SHA256 `942b5120...85d5`。
- 全曲 CUDA 分离耗时 22.20 秒；vocals SHA256 `544ba017...d4d9`、other SHA256 `8e0cc4c5...b511`，两者均非静音。

## 丰川祥子 RVC

- 社区模型 revision `61676cf82a23a9d736c0501021c905cf8b9c2e2f`；weight SHA256 `1a5640c2...0ae`，index SHA256 `bcb530c4...578`。模型卡标记非官方、license `Other`，只在本机测试。
- unsafe-global 扫描为空，`torch.load(weights_only=True)` 成功。
- 《春日影》分离人声 20–50 秒，RMVPE + FAISS index 真实输出：29.98 秒、40 kHz、单声道，SHA256 `d5e29bb9fd9ca1831b972cedf5ebc93d00b3b36b55efdf14036f509c220bdf0a0`。
- GUI 同款全链：257.840 秒、44.1 kHz、双声道 PCM24、mean -20.47 dB、peak -5.14 dB，SHA256 `00df7b62dc7594c0bae8f9aaba446c7d629369da11a25baf2b893b59ab1c1d9d`；43.09 秒完成。

## 丰川祥子 DDSP

- DDSP-SVC commit `2e2ac5d34ffe08cb1a03fdffd51742e62b8bcf8c`；社区模型 revision `4b77b1a9004c1a86cc8b06d1d118d0c49243a614`。
- weight SHA256 `3023012d...eadf`，config SHA256 `56632033...dd08`；unsafe-global 扫描为空且 weights-only 加载成功。
- 依赖：ContentVec `d8dd400e...854e`、RMVPE `19dc1809...6fe2`、PC-NSF-HiFiGAN `d6dd2890...5c67f`。
- 30 秒真实输出：30.000181 秒、44.1 kHz、单声道，SHA256 `079522a8043eb0ee40931f5c078fec8a3912ba635ef9af424aabda21592669ca`。
- GUI 同款全链：257.845986 秒、44.1 kHz、双声道 PCM24、mean -20.83 dB、peak -3.55 dB，SHA256 `61cfba1b1ec29558a5b5288e9548b6a81f83d622189c13970e8719a29097836b`；49.60 秒完成。

## 试听与缓存

- 标准干声 `neutral_melody.wav`：CC0 真实女声清唱，9.008163 秒、44.1 kHz、单声道 PCM16，SHA256 `de75b75a...256d`。
- `app.py --worker` 分发入口对目标 RVC/DDSP 均成功真实重建 `preview.wav`：RVC SHA256 `6c5dfa85...a180`，DDSP SHA256 `719752da...3282`。输出与源文件哈希不同，不是复制、静音或其他音色替代。
- 相同最终请求缓存命中：RVC 0.569 秒，DDSP 0.496 秒。
- 共享阶段缓存验证：RVC pitch +1 首次 43.19 秒；随后 DDSP pitch +1 复用标准化与 MSST 分离结果，23.29 秒完成。
- RVC 官方仓库示例音色独立试听：9.000 秒/40 kHz，SHA256 `ad78c1dc...cbb0`。普通 DDSP 社区音色独立试听：9.009 秒/44.1 kHz，SHA256 `440ab50d...3d1f`；两者均有限、非静音且与标准干声不同。
- 可再分发 RVC 初始音色：Saisho Utane、VCTK p231、VCTK p226 三个 checkpoint 的固定 LFS SHA256 全部匹配，unsafe globals 均为空且 `weights_only=True` 加载成功。应用同款 preview worker 总计 28.2 秒生成三份真实试听：Saisho 9.000 秒/48 kHz/RMS 0.06880/SHA256 `52af2f59...e440`；p231 9.000 秒/40 kHz/RMS 0.05203/`29deafb9...12c2`；p226（推荐 -12 半音）9.000 秒/40 kHz/RMS 0.06077/`d651b9c6...0a9e`。四个输入/输出哈希全部不同，finite/nonzero 均为 true。
- 修复 DDSP 导入器把配置命名为 `model.yaml` 导致上游固定查找 `config.yaml` 失败的问题；YML/YAML 输入现统一安全复制为 `config.yaml`。
- 改词任务只改变混音平衡后 0.70 秒完成，日志明确显示复用 Vevo2 和 RVC 转换缓存；两份最终 WAV SHA256 分别为 `cf29b9fc...be31` 与 `09305da1...e76c`。

## Windows GUI 与发行

- 系统 Python 双击 `app.py` 会转交 `.venv\Scripts\pythonw.exe`，检测到有效 GUI 进程；源码模式无浏览器、无 Web 服务。
- 导入无试听模型后会提交独立 preview worker；音色卡已有试听时使用 Qt Multimedia 播放，无试听时显示并启用“生成试听”。
- 已修复 `MainWindow` 向 `JobManager` 传入 `AppPaths` 而非根 `Path` 导致按钮任务崩溃的问题。
- Modern/Legacy 都按 PyInstaller `--windowed --onedir` 构建；公开包不包含用户测试歌和未获再分发授权的后端/角色权重。
- 最终 Modern/Legacy 两目录均为 804.2 MiB/482 文件。各包只含 Saisho Utane、VCTK p231、VCTK p226 三套白名单 RVC 的 `model.pth`、元数据、项目占位头像和真实试听，逐文件与源码安装目录 SHA256 一致；`assets/audio/春日影.wav`、祥子/Kokkoro、`.index`、DDSP 权重和后端模型计数均为 0。CC0 `neutral_melody.wav` 与轻量 DiffSinger/对齐调用包装器存在，但不含对应重型模型。Modern、Legacy GUI 均在隐藏启动 8 秒后保持存活。
- 两个公开包的 `OpenCoverStudioWorker.exe` 无参数协议 smoke 均返回退出码 2、合法 UTF-8 JSON `BAD_ARGUMENTS`，stderr 为 0 bytes，证明冻结 worker 可启动且不会静默挂起。
- 以系统 `python.exe app.py` 模拟双击：launcher 正常退出并产生 1 个新的项目 `pythonw.exe` GUI 进程，随后只终止该测试进程。

## 改词 GUI 与发行 worker 实测

- Vevo2：Amphion commit `26f6883110181f1dbfe95c70a7c7dbaf4de5f42a`，RMSnow/Vevo2 revision `2674843cbaa50aa89ee7ccaf5bb15d6ccf46c6c8`。只下载 4,281,405,036 bytes 推理文件，排除 optimizer/trainer state；权重为 CC BY-NC-ND 4.0，不再分发。
- 完整 AR 508.93M + Flow 362.87M + tokenizers + vocoder 255.04M 在 RTX 5070 Ti 成功加载；中文、日文各生成 9.16 秒/24 kHz/单声道 PCM16 WAV。中文 SHA256 `46baf4ea...c896`，日文 `f5b1bb0c...fb17`；RMS -25 dB，峰值约 -10.8/-10.6 dB；峰值 CUDA 7,910,244,864 bytes，总耗时 25.78 秒。
- GAME：源码 commit `4ad815c90dfe2442730f3fdc866fd23e737cbc97`，官方 v1.0 small ZIP SHA256 `3d3e1ac0...c576`。对《春日影》30 秒分离人声用日语条件、CUDA 16-bit AMP 提取成功；MIDI SHA256 `c6dfeffb...8d3e`，TXT `733bc418...0043`，CSV `495cc9b7...798f`。
- GAME 首次在结果全部保存后因 Rich 向 GBK 终端输出 `•` 而 teardown 失败；设置 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 后相同推理退出码 0。
- 原版官方 DiffSinger demo 固定 commit `6a08cddc365c614a1f50efd5fea1333ac58b5359`。OpenCpop acoustic 0831 权重 170,269,591 bytes / SHA256 `954a31208ee6afb6240d09454bb204c4fbc63cf70e2586bed0ab29b1dc964c9e`；pitch extractor 13,047,222 bytes / `53942abd8cb908b6d161e1ad7ff3d7d0dd6b204d5bf050613c9d00c56b185ceb`；NSF-HiFiGAN 55,827,436 bytes / `1cb68f3ce0c46ba0a8b6d49718f1fffdf5bd7bcab769a986fd2fd129835cc1d1`。三者都以 `torch.load(weights_only=True)` 加载为仅含 `state_dict` 的旧式 checkpoint；旧序列化格式不支持 unsafe-global 静态枚举，未据此虚称扫描通过。
- DiffSinger 固定示例输出 5.115 秒、24 kHz、单声道，RMS 0.04590，SHA256 `2a824f40...e765`；GAME 动态音符映射输出 8.672 秒、RMS 0.07277，SHA256 `00950451...a76`。两者均 finite、非静音。
- 强制选择 `generator=diffsinger` 的完整链执行 MSST 缓存→GAME→DiffSinger→祥子 RVC→混音，输出 9.008 秒、44.1 kHz、双声道，RMS 0.05513、peak 0.98，SHA256 `912147afe1dfcb59d2b1d5408bc0e7b6ffd09d950bb58d9895a9f9e8c7df869b`。
- 源码 worker 端到端 MSST→Vevo2→祥子 RVC→时长校正→混音成功；9.008 秒双声道输出 SHA256 `8271ac4c...97de3`。
- 最初复用 windowed GUI EXE 作为 worker 时无 stdout 且卡住，已替换为约 65.30 MB 的 console-subsystem `OpenCoverStudioWorker.exe`；Qt 使用 `CREATE_NO_WINDOW` 隐藏启动。Modern/Legacy 冻结 worker 的资源缓存任务均退出 0、产生 result、stderr 为 0 bytes。
- `Modern-LocalFull` 同步公开音色与许可证后为 26.769 GiB/168,237 文件（含运行时生成的 Python 缓存、测试输出与日志）。注册表识别祥子 RVC/DDSP、三套公开 RVC、Kokkoro DDSP 与官方 RVC 演示音色；其专用 worker 的 Vevo2 真实全链耗时 114 秒、退出码 0，输出 SHA256 `41f0bb4c...9143`，9.008 秒/44.1 kHz/双声道、RMS 0.05142、finite=True。
- 更新后的冻结 worker 以任务参数明确选择 `generator=diffsinger`，70.6 秒完整执行 GAME→DiffSinger→祥子 RVC→混音，进度 0–100 单调且退出码 0。输出 SHA256 `b0568c9ad5b45d225a2ee0fcce1c26a7657fb574a57c16996094075b03583c70`，9.008 秒/44.1 kHz/双声道、RMS 0.05783、peak 0.98、finite/nonzero 均为 true。
- 源码链以 `memory_profile=低` 再次真实执行 GAME→DiffSinger→祥子 RVC，29.9 秒退出 0；输出 SHA256 `f59b3206941e77f0b9cda72475b082a16db15fa61e9eaf902b34f3f6ee60f08e`，9.008 秒/44.1 kHz/双声道、RMS 0.05298、peak 0.98、finite/nonzero 均为 true。该档位进入生成/转换缓存键；若走 Vevo2，flow steps 为 24。
- 最终本机完整包的冻结 worker 也以 `memory_profile=低`、`generator=diffsinger` 完成新歌词任务：37.2 秒、退出码 0、没有 stderr 削波警告；输出 SHA256 `c7febb13ca4fa16031797d47986d0b250deae612bf69ae4349af54288dbdfa95`，9.008 秒/44.1 kHz/双声道、RMS 0.05507、peak 0.98、finite/nonzero 均为 true。
- Qt JobManager 从该 worker 收到完整 UTF-8 JSON Lines，并将含中文的真实输出路径逐字写入 SQLite。Vevo2 `generate` 阶段在进度 40% 取消后状态为 `cancelled`、无输出，进程树检查 `orphan_count=0`。
- JobManager 现将 stdout/stderr/进程退出按 UTC 时间持久化为 `workspace/jobs/<id>/worker.log`。冻结 worker 复用改词缓存后的完整祥子 RVC 任务 18.7 秒完成，日志同时含 `result` 与 `process_exit=0 success=True`；输出 SHA256 `146a88ed8f39f87929ecf5d96bceef0420518f7b92ad0ea94601a6dfa4c0f205`。
- 关闭并行 GPU 负载后，使用全新歌词绕过改词缓存重跑：Vevo2→拼接→祥子 RVC→混音共 67.4 秒，任务 `completed/100%/export`。输出 9.008163 秒、44.1 kHz、双声道，RMS 0.04753、peak 0.98、finite/nonzero 均为 true，SHA256 `546d9e83342d84727176b43a253ac9250eb45789c0cfb6f5f1de5b93d0a3fb6e`；日志 2789 bytes，含结果和正常退出。
- 启动恢复测试确认只把遗留 `pending/running` 记录转为失败，已完成记录保持不变；历史页日志包测试确认 ZIP 包含 `job.json`、`request.json`、`worker.log`。

## 自动歌词强制对齐

- Stable-ts 2.19.1 commit `e312072cc024ae9fceb25b057d7d18524873a02b`（MIT，上游 2026-05-30 归档）；OpenAI Whisper 20250625 commit `5f86d1d86363843179951550570367b37c5d6f78`（MIT）。独立 Python 3.10.20 / torch+torchaudio 2.9.1+cu130 环境 CUDA 可用。
- 官方 multilingual `base.pt` 为 145,262,807 bytes，SHA256 `ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`，与 OpenAI 官方 URL 内嵌哈希一致。
- Whisper 官方 `jfk.flac` SHA256 `63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715`。给定正确原文后强制对齐得到 22 词、0.32–10.26 秒、0 个零时长词、CUDA 峰值 469,291,008 bytes；两行输入保留换行并得到 0.32/8.30 秒两个句首。
- 《春日影》已分离人声 20–50 秒片段 SHA256 `da727842efe90d8b1a087cf4b181d73b092e77df4a8f24c88b18ac51e1c976cb`。Whisper 日语转写得到 4 段/48 词，再以这四行作给定文本强制对齐，句级区间为 0–11.52、11.80–23.76、23.96–26.94、27.76–29.76 秒；48 个词中 1 个细粒度 token 为零时长，因此只宣称句级边界可用，不宣称自然歌声逐字完美。
- 源码 JobManager 的无时间戳完整链“Whisper→GAME→DiffSinger→祥子 RVC→混音”32.5 秒完成；输出 9.008 秒、RMS 0.05424、peak 0.98、SHA256 `cfed28b63ad655bcfc247d8fae94c1c21f7fdd3c5fac8fb6c154cfe36c20ece5`。相同请求复跑 1.4 秒，日志同时证明对齐、生成和最终缓存命中。
- 同步后的冻结完整包以全新歌词执行同一链路，61 秒完成；其中冷启动对齐约 24.9 秒。输出 9.008 秒、44.1 kHz、双声道、RMS 0.05515、peak 0.98、finite/nonzero 均为 true，SHA256 `b4e30346bcaa2e7ce15f94c77841cf2eb2b100eb9d7424c95adb05cf3787ee6e`。

## 2026-08-17 改词音质缺陷修复复验

- 复现旧缺陷：5 秒 Vevo2 目标短句在未限制 AR token 时真实生成 30.8 秒音频；旧线性重采样会把它强压回目标时间并连带改变音高。
- 新增 FFmpeg Rubber Band 保音高校时。440 Hz / 1.0 秒正弦拉长到 1.2 秒后主频仍在 440±3 Hz；拉长到 2.0 秒会明确拒绝，不再产生 220 Hz 伪结果。
- 同一真实《惊鹊》短句重新执行自动链：UVR5 分离缓存 → Vevo2 → 保音高校时 → 丰川祥子 RVC → 混音，未触发 DiffSinger 回退。Vevo2 原始段为 5.760 秒/24 kHz/单声道，SHA256 `892d854c7f19452db08788c17221f2908c596c0e22c539fd8ee429236af2e3c7`；校时拼接人声 5.518367 秒/44.1 kHz，SHA256 `ac608b1ecaa36160438cd0b7280e980a82492d468ac9b050027fbab36eff2416`。
- 最终真实输出为 5.520 秒/44.1 kHz/双声道，RMS 0.092065、peak 0.610340、finite=True，SHA256 `198d9a1388e2a8eb827557618c1635542131b6ed6e9b2df5fdc0a5581e81ad10`。
- GAME + DiffSinger 回退也以新增 SP/AP 休止输入真实跑通一条短句；项目 DiffSinger G2P 实测将 `SP春日AP` 解析为 `['SP', 'chun', 'ri', 'AP']`。
- `.venv\Scripts\python.exe -m pytest -q`：62 项全部通过；新增测试覆盖 Vevo2 首选路由、AR 时长 token 上限、休止/原时值保留、保音高校时和极端拉伸拒绝。
- 复核该输出后确认 UVR5 的 `other.wav` 并非伴奏：它与标准化原输入的波形相关度为 `0.999310474`、RMS 比为 `0.293449923`，原流程随后对它做响度匹配并重新混入，构成明确的原唱回流。
- 新增改词专用伴奏守卫：只有当 `other.wav` 近似原输入的缩放复制、主唱分轨同时占显著能量时才禁用该轨；正常独立伴奏回归样例保持不变。分离缓存加入守卫版本，最终混音缓存也已失效，旧坏成品不会再命中。
- 同一请求真实重跑输出 `jingque_first_line_改词_toyokawa_sakiko_rvc_c05a5adc0d.wav`：5.520 秒/44.1 kHz/双声道，RMS `0.080353`、peak `0.589529`、SHA256 `b58c73a21a50b706bccdd9f3e696d0fda3bb811da0060c1ab154664a394b70f6`。守卫后伴奏峰值为 0；新成品与原输入的波形相关度由旧成品的 `0.487917` 降到 `-0.006659`，与转换后新歌词人声相关度为 `1.000000`。
- `.venv\Scripts\python.exe -m pytest -q`：64 项全部通过；新增两项覆盖原唱缩放复制轨拦截与真实独立伴奏保留。

## 2026-08-18 改词节奏失败审计

- 用户复听确认整句 Vevo2 成品节奏错误。新增与音色无关的能量/起音包络比较；相同节奏但不同频率的合成样例得分大于 `0.90`，重排起音样例低于 `0.10`。
- GAME 对原唱短句提取 19 个音符，起始约 `0.09s`；对整句 Vevo2 结果只提取 12 个音符，首个音符约 `1.23s`，且开头音高由原曲 `F4→G4→A#4` 变为 `D#4→F4→F4`。因此错误不只是总时长或线性偏移，不能靠 Rubber Band 整句校时修复。
- 真实试验过 3 块和 7 块 GAME 时间窗约束的 Vevo2 分段生成。完整时间轴节奏得分分别约 `0.214`、`0.122`，相对整句 Vevo2 的 `0.203` 没有形成可靠改善；细分还引入接缝，因此该实验已从正式路径移除，相关输出不作为修复结果交付。
- 当前 GAME + legacy DiffSinger 能按显式音符时值合成，但声学模型仍是旧 24 kHz OpenCpop checkpoint；Vevo2 声学质量较高但不是精确乐谱控制模型。当前本机后端无法同时满足“新歌词音质可接受”和“严格保留原旋律/节奏”，不宣称该缺陷已修复。
- GUI 文案已移除“Vevo2 保留原唱旋律与节奏”的错误保证，明确标注参考韵律、节奏门控、legacy 回退及音质边界。`.venv\Scripts\python.exe -m pytest -q`：65 项全部通过。

## 2026-08-18 VISinger2 后端更换复验

- 自动改词主后端已更换为 ESPnet VISinger2：模型 `espnet/aceopencpop_svs_visinger2_40singer_pretrain` 固定 revision `8620f8f72df95d1d60dc3d7483f4da9acf8073be`，模型卡声明 CC BY 4.0；448,208,603 bytes 权重 SHA256 为 `4125552c2bbd45e21137dd016bf00e3c1f3ca335eb027e0fef49967c388ee171`。ESPnet 源码固定当前可获取的官方 commit `2d9a6c37c8eef710debc903d86132f1ad9a40c9f`（Apache 2.0）。模型卡记录的旧 ESPnet commit 已不可获取，因此未伪称按该死链固定；运行器只为旧序列化配置补齐当前解析器的默认字段。
- 官方模型卡示例真实输出 `workspace/jobs/visinger2-smoke/official_example.wav`：1.799546 秒/44.1 kHz，RMS `0.052006`、peak `0.228250`，SHA256 `8edd4f765e5f7a54e53c4e0dd61d4dc95b53e5f670f932f50ec4430e5b0051c3`。项目 19 音符短句直接生成 `project_sample.wav`：4.957460 秒/44.1 kHz，目标乐谱跨度 4.970 秒，RMS `0.081195`、peak `0.272445`，SHA256 `a1afd97ca0a60d3f411ad6ee7df57f1a7aa6e388769c3f9fd470d95c0ccd8262`。
- 同一《惊鹊》请求完整执行 GAME → VISinger2 → 丰川祥子 RVC → 混音，输出 `workspace/outputs/jingque_first_line_改词_toyokawa_sakiko_rvc_1f9a77fde0.wav`：5.520 秒/44.1 kHz，RMS `0.080178`、peak `0.494810`，SHA256 `1feaccc907d59868b6fbd22b82041c939f35c09230f49dbd05992c53f368c456`。最终成品与原输入波形相关度为 `0.029243`，没有把原唱重新混回去。
- 用 GAME 对最终成品反向提取，得到与原曲目标相同的 19 个音符，音高序列逐项一致（开头 `F4→G4→A#4→A#4→C5`）；音符边界平均绝对误差 `0.16158s`、最大 `0.26s`。这证明新链路确实跟随显式乐谱，但不宣称逐采样或逐字边界完美。
- 旧能量包络指标对更换歌词后的不同音素只得到 `0.074`，会把按谱合成误判为失败，因此现代按谱路径改用可读性、句长和反向音符验证；该包络门控只保留给不接受乐谱的 Vevo2。自动路径在 VISinger2 已就绪但推理失败时不会静默退回旧 DiffSinger。
- `.venv\Scripts\python.exe -m pytest -q`：67 项全部通过；新增覆盖后端状态、中文音素/连音展开、自动优先路由和资源 marker。冻结完整包尚未重建，不能据此宣称旧 EXE 已包含新后端。

## 2026-08-20 第一行跑调与吐字修复复验

- 逐项检查确认旧映射按音符数量平均分字，会把“轻”压到约 `0.15s` 的单音并把后续音符移给错误汉字。现改为 Whisper 原唱逐字边界 + GAME 连续 F0 音符窗口映射；逐字对齐不匹配时停止，不再静默均分。
- 同一修正乐谱对比 VISinger2、legacy DiffSinger、5 个 VISinger2 女声 ID、3 档 RVC protect、Sakiko DDSP 与多组频段混合。DiffSinger 原始段的 Whisper medium 结果为“青州渡过江南西越的天流徐漫长街”，首六字音同且边界稳定；因此自动优先级改为 DiffSinger，VISinger2 降为后备。
- 修正乐谱的 DiffSinger 原始输出逐音符连续 F0 中位绝对误差约 `20` 音分，`90%` 可测音符在 `±50` 音分内。最终逐句 RVC 产品输出 `jingque_first_line_改词_toyokawa_sakiko_rvc_f634032416.wav` 为 `5.520s / 44.1kHz`，SHA256 `0f4147380872825716d9877b04e9632740cfd26069b5aa7719b58f88bd1aebd3`；最终 F0 中位绝对误差 `25` 音分，`90.5%` 音符在 `±50` 音分内。
- 整轨 RVC 会把同一清晰短句从“青州渡过江南”退化为“青秋渡过青年”。现改为一次加载 RVC 模型、每个未校时短句分别转换后再校时拼接；最终首六字恢复为 Whisper 识别“青州渡过江南”。后半句仍会识别为“今夜的天流是难唱尽”，说明该 Sakiko RVC 权重对中文声母/韵母仍有可听边界，不宣称整句吐字已经完美。
- 最终成品与原输入波形相关度为 `-0.023699`，伴奏守卫标记为 muted，没有把原唱或伪伴奏重新混回。源码完整测试 `70` 项通过；冻结 EXE 尚未重建。
- 用户随后实际复听确认“柳絮满长街”仍然听感完全跑调。连续 F0 与 ASR 只能验证频率轨迹和近似音素，不能证明音符落字、声学重音和听感正确；因此该人耳结果否决“已修复”结论。另一次按音符起点重新分字的真实实验还导致前半句错位，已撤回且不进入正式路径。
- 尚未完成第二首不同歌曲的端到端人工验收，也没有覆盖不同字数、快歌、说唱、密集转音、和声或非中文的测试矩阵。当前改词功能不宣称跨歌曲泛用；Sakiko RVC 对普通话的破坏是已知阻断项。

## 未通过/未执行

- RVC 已有三套可再分发、带头像和真实试听的初始音色；DDSP 的 3～5 套公开初始音色仍未满足。祥子双模型仍只允许本机使用的保守判断。
- 当前改词自动主路径为逐字对齐 + GAME/连续 F0 + legacy DiffSinger，VISinger2 为按谱后备。冻结完整包和公开发行包尚未重建验证；旧版 DiffSinger 权重许可仍不明确，因此不宣称可公开再分发。非中文 G2P 仍未实现。
- Legacy CUDA 11.8 机器未获得实体旧显卡实测；“Legacy”目前只代表发行目标，不宣称兼容性已验收。
- OOM 故障注入验证了 CUDA 错误分类、后端退出后的 30/15 秒有限分段重试与交叉淡化拼接；当前 12 GB 显卡未发生真实 OOM，因此不宣称已完成实体 4–8 GB 显卡压力测试。MSST 也没有许可/格式匹配的轻量替代 checkpoint 可自动切换。
- 没有以 mock、输入复制、静音或随机音频代替任何上述未完成结果。
