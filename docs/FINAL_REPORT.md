# OpenCover Studio v0.1.0 阶段交付报告

1. GUI：七个简体中文 Qt Widgets 页面、左侧导航、背景蒙层、音频拖放、输入/音色/输出播放器及音量、托盘、窗口/页面记忆；首页显示真实最近任务与推荐音色，历史任务可重新生成或更换同引擎音色后生成。
2. 启动：双击 `app.py` 自动转交 `pythonw.exe`；Modern/Legacy EXE 均为 windowed onedir，不显示控制台、不打开浏览器。
3. 后端：MSST `e247dfe...`、RVC `7b284a6...`、DDSP-SVC `2e2ac5d...` 均在各自独立环境通过真实 CUDA 推理。
4. MSST：官方 MDX23C vocals SDR 10.17 完成公共领域样例和《春日影》全曲分离。
5. 祥子 RVC：TogetsuDo revision `61676cf...`，weight/index 均记录 SHA256；30 秒 indexed 与全曲 worker 成功。
6. 祥子 DDSP：TogetsuDo revision `4b77b1a...`，weight/config 均记录 SHA256；30 秒与全曲 worker 成功。
7. 权利边界：两套祥子权重都是未经官方授权的社区模型、license `Other`，只在本机按用户要求安装测试，不随 Git 或公开发行包分发；头像仅使用用户提供图片。
8. 标准试听：owstu/Freesound “Female Vocal 01.wav”，CC0，转换后 9.008 秒；目标 RVC/DDSP 均由此干声实际推理生成独立 `preview.wav`。
9. 自动试听：导入时可选自动/上传/暂不生成；独立 worker 有进度、可取消、失败写 SQLite；WAV/FLAC/MP3/M4A 上传会保留原始文件并统一转码。
10. 原词链路：标准化 → MSST → RVC/DDSP → 对齐 → LUFS/峰值混音 → WAV/FLAC/MP3；两引擎都完成《春日影》257.84 秒全曲真实输出。
11. 缓存：分离、改词生成、音色转换和最终混音分层；换混音/格式不重复模型推理，模型哈希变化会使转换缓存失效。
12. 模型导入/管理：RVC `.pth/.pt` + 可选 `.index`；DDSP `.pt/.ckpt` + YAML；哈希去重、头像原图/缩略图、试听原件/统一 WAV、名称简介/语言/Key 编辑、试听重生与用户模型删除；支持名称/简介/语言搜索、置顶、隐藏内置、名称与最近使用排序。
13. 安全：组件页下载 worker 支持断点、重试、速度/进度、取消、缓存、大小与 SHA256 校验；安全解压拒绝路径穿越、符号链接、压缩炸弹和覆盖；checkpoint 先做 unsafe-global/weights-only 检查；子进程参数列表调用，无 `shell=True`。
14. 测试：33 项 pytest 全部通过；完整数值与文件哈希见 `docs/TEST_REPORT.md`。
15. 发行：GUI 为 windowed EXE；独立 worker 用 `CREATE_NO_WINDOW` 隐藏启动并保留 UTF-8 进度。Modern/Legacy 公开包均为 641.8 MiB/466 文件且敏感资源泄漏数为 0。本机 Modern 完整私有包约 23.61 GiB，打包后 Vevo2 改词、低显存 DiffSinger 回退与取消均通过。
16. Vevo2：官方 4.28 GB 权重已安装；中文/日文独立样例以及 GUI/JobManager 端到端改词均真实成功。支持 LRC/逐行分段、密度策略、时长拼接和缓存；模型 CC BY-NC-ND 4.0，不进入公开包。
17. GAME + DiffSinger：GAME 官方 small 模型已对《春日影》30 秒真实提取 MIDI/TXT/CSV；另固定原版官方 DiffSinger HF demo commit `6a08cdd...`，使用 OpenCpop acoustic、pitch extractor 与 NSF-HiFiGAN 完成固定样例、GAME 动态旋律以及完整 fallback 三层真实 WAV 验证。旧版权重没有独立许可文件，只作本机测试。
18. 普通音色：除祥子双模型外，RVC 官方仓库示例与一个 DDSP-SVC 6.3 社区模型均生成自己的真实试听；因训练数据/角色衍生权利不清，仍只在本机安装。
19. 显存模式/OOM：设置即时持久化并进入任务；极低/低模式使用 16/24 Vevo2 steps，RVC/DDSP 捕获明确显存错误后按档位以 8～45 秒分段有限重试；最终失败使用 `CUDA_OOM`。策略和拼接已用故障注入测试，未冒充实体低显存显卡验证。
20. 未完成：每引擎 3～5 个可再分发初始音色、自动 ASR 歌词强制对齐、完全可移植的各后端独立运行时和实体旧显卡 Legacy 验收。界面不会把它们伪装为可用。
