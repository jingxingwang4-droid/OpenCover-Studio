# 测试报告（2026-08-10）

## 环境与自动化

- Windows 10 build 26200；GUI Python 3.10.20；PySide6 6.11.1。
- NVIDIA GeForce RTX 5070 Ti Laptop GPU，12172 MiB，驱动 591.86。
- MSST/RVC 为 PyTorch 2.9.1+cu130；DDSP 为独立 Python 3.11.5、PyTorch/torchaudio 2.9.1+cu130；三者 CUDA tensor smoke test 均通过。
- FFmpeg 9.0 essentials build。
- `.venv\Scripts\python.exe -m pytest -q`：`15 passed`。覆盖 JSON Lines worker、ZIP 安全、SQLite/中文路径、模型导入/哈希去重、头像/上传试听、非静音混音、preflight、跨音色分离缓存 key、资源清单、七页面窗口、`pythonw` 双击转交与 RVC CLI。

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

## Windows GUI 与发行

- 系统 Python 双击 `app.py` 会转交 `.venv\Scripts\pythonw.exe`，检测到有效 GUI 进程；源码模式无浏览器、无 Web 服务。
- 导入无试听模型后会提交独立 preview worker；音色卡已有试听时使用 Qt Multimedia 播放，无试听时显示并启用“生成试听”。
- 已修复 `MainWindow` 向 `JobManager` 传入 `AppPaths` 而非根 `Path` 导致按钮任务崩溃的问题。
- Modern/Legacy 都按 PyInstaller `--windowed --onedir` 构建；公开包不包含用户测试歌和未获再分发授权的后端/角色权重。
- 最终重建后两目录均为 576.1 MiB/457 文件；CC0 `neutral_melody.wav` 存在，`assets/audio/春日影.wav` 不存在，weights/backend 文件计数均为 0。两 EXE 分别启动 5 秒仍存活。
- 以系统 `python.exe app.py` 模拟双击：launcher 正常退出并产生 1 个新的项目 `pythonw.exe` GUI 进程，随后只终止该测试进程。

## 改词后端研究性实测

- Vevo2：Amphion commit `26f6883110181f1dbfe95c70a7c7dbaf4de5f42a`，RMSnow/Vevo2 revision `2674843cbaa50aa89ee7ccaf5bb15d6ccf46c6c8`。只下载 4,281,405,036 bytes 推理文件，排除 optimizer/trainer state；权重为 CC BY-NC-ND 4.0，不再分发。
- 完整 AR 508.93M + Flow 362.87M + tokenizers + vocoder 255.04M 在 RTX 5070 Ti 成功加载；中文、日文各生成 9.16 秒/24 kHz/单声道 PCM16 WAV。中文 SHA256 `46baf4ea...c896`，日文 `f5b1bb0c...fb17`；RMS -25 dB，峰值约 -10.8/-10.6 dB；峰值 CUDA 7,910,244,864 bytes，总耗时 25.78 秒。
- GAME：源码 commit `4ad815c90dfe2442730f3fdc866fd23e737cbc97`，官方 v1.0 small ZIP SHA256 `3d3e1ac0...c576`。对《春日影》30 秒分离人声用日语条件、CUDA 16-bit AMP 提取成功；MIDI SHA256 `c6dfeffb...8d3e`，TXT `733bc418...0043`，CSV `495cc9b7...798f`。
- GAME 首次在结果全部保存后因 Rich 向 GBK 终端输出 `•` 而 teardown 失败；设置 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 后相同推理退出码 0。

## 未通过/未执行

- 每个引擎 3～5 个可再分发初始音色尚未满足；当前祥子模型只允许本机使用的保守判断。
- Vevo2 中文/日语和 GAME MIDI 提取已真实通过，但尚未接入完整 GUI 改词流水线。
- DiffSinger 当前官方分支不附歌声 acoustic/variance 模型；未找到格式匹配且许可清晰的模型，因此 GAME + DiffSinger 合成 WAV 仍未完成。
- Legacy CUDA 11.8 机器未获得实体旧显卡实测；“Legacy”目前只代表发行目标，不宣称兼容性已验收。
- 没有以 mock、输入复制、静音或随机音频代替任何上述未完成结果。
