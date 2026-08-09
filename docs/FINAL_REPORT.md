# OpenCover Studio v0.1.0 阶段交付报告

1. GUI：七个简体中文 Qt Widgets 页面、左侧导航、背景蒙层、音频拖放、Qt Multimedia 播放器、托盘、窗口/页面记忆。
2. 启动：双击 `app.py` 自动转交 `pythonw.exe`；Modern/Legacy EXE 均为 windowed onedir，不显示控制台、不打开浏览器。
3. 后端：MSST `e247dfe...`、RVC `7b284a6...`、DDSP-SVC `2e2ac5d...` 均在各自独立环境通过真实 CUDA 推理。
4. MSST：官方 MDX23C vocals SDR 10.17 完成公共领域样例和《春日影》全曲分离。
5. 祥子 RVC：TogetsuDo revision `61676cf...`，weight/index 均记录 SHA256；30 秒 indexed 与全曲 worker 成功。
6. 祥子 DDSP：TogetsuDo revision `4b77b1a...`，weight/config 均记录 SHA256；30 秒与全曲 worker 成功。
7. 权利边界：两套祥子权重都是未经官方授权的社区模型、license `Other`，只在本机按用户要求安装测试，不随 Git 或公开发行包分发；头像仅使用用户提供图片。
8. 标准试听：owstu/Freesound “Female Vocal 01.wav”，CC0，转换后 9.008 秒；目标 RVC/DDSP 均由此干声实际推理生成独立 `preview.wav`。
9. 自动试听：导入模型没有试听时提交独立 QProcess worker；有进度、可取消、失败写入 SQLite；卡片只有真实文件存在时才播放。
10. 原词链路：标准化 → MSST → RVC/DDSP → 对齐 → LUFS/峰值混音 → WAV/FLAC/MP3；两引擎都完成《春日影》257.84 秒全曲真实输出。
11. 缓存：最终结果按完整参数缓存；标准化与 MSST 分离按输入和 checkpoint 单独共享，换音色/引擎不重复分离。
12. 模型导入：RVC `.pth/.pt` + 可选 `.index`；DDSP `.pt/.ckpt` + 配置；哈希去重、不覆盖、中文路径、头像裁切、WAV 试听上传。
13. 安全：下载器支持断点、校验、安全解压；checkpoint 先做 unsafe-global/weights-only 检查；子进程参数列表调用，无 `shell=True`。
14. 测试：15 项 pytest 全部通过；完整数值与文件哈希见 `docs/TEST_REPORT.md`。
15. 发行：Modern/Legacy 最终重建目录各 576.1 MiB、457 个文件；两者 EXE 启动 5 秒后均保持窗口进程存活。包内含 FFmpeg 与 CC0 试听源，不含《春日影》、模型权重或大型后端。
16. Vevo2：官方 4.28 GB 推理权重已安装；中文/日文 9.16 秒样例都真实成功，峰值显存 7.91 GB。模型为 CC BY-NC-ND 4.0，不进入公开发行包；完整歌曲切句/对齐/拼接尚未接入 GUI。
17. GAME：官方 small 模型已对《春日影》30 秒真实提取 MIDI/TXT/CSV。DiffSinger 源码已固定，但当前官方分支不附歌声模型，因此 fallback 合成 WAV 仍不可用。
18. 未完成：每引擎 3～5 个可再分发初始音色、完整改词 GUI 流水线、DiffSinger 合成和实体旧显卡 Legacy 验收。界面不会把未完成部分伪装为可用。
19. 当前优先级：先取得条款清晰的可再分发基础音色和 DiffSinger acoustic 模型，再把已验证 Vevo2/GAME 包装为可取消 worker，最后制作包含相应许可证的完整运行时包。
