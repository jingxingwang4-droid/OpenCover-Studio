# 测试报告（2026-08-10）

## 环境

- Windows 10 build 26200；Python 3.10.20；PySide6 6.11.1。
- NVIDIA GeForce RTX 5070 Ti Laptop GPU，12172 MiB，驱动 591.86。
- MSST 与 RVC 独立环境均为 PyTorch 2.9.1+cu130；CUDA tensor smoke test 成功。
- FFmpeg 9.0 essentials build。

## 自动与桌面回归

- `.venv\Scripts\python.exe -m pytest -q`：`14 passed`。
- 覆盖 worker JSON Lines、ZIP 安全、SQLite/中文路径、RVC 导入与哈希去重、头像/试听、非静音混音、preflight、资源清单、七页面窗口构造、`pythonw` 双击转交与 RVC CLI 入口。
- 系统 Python 启动 `app.py` 后会转交 `.venv\Scripts\pythonw.exe`；检测到响应中的 GUI 进程，解决双击无窗口问题。
- Modern/Legacy 均以 PyInstaller `--windowed --onedir` 构建；无控制台窗口。

## 真实后端测试

### MSST

- 源码 commit：`e247dfe4abc1f17c69dff719207fe045dc04413a`。
- 模型：官方 v1.0.0 MDX23C vocals SDR 10.17，checkpoint SHA256 `49d514...d816`。
- 公共领域 15 秒样例：CUDA 分离成功，生成 `vocals.wav` 与 `other.wav`，均非静音。
- 用户测试曲：`assets/audio/春日影.wav`，257.84 秒、44.1 kHz、立体声、SHA256 `942b5120...85d5`。
- 全曲 CUDA 分离耗时 22.20 秒；两条输出均为 257.84 秒、约 90.97 MB，SHA256 分别为 vocals `544ba017...d4d9`、other `8e0cc4c5...b511`。

### RVC

- CLI commit：`7b284a634667c34103eaaeed972b48ccdb4b893e`；Fairseq fork：`ff08af27e302625a27d3502b0791a9367c8af0c7`。
- HuBERT SHA256 `f54b40fd...db96`；RMVPE SHA256 `6d62215f...c193`；官方仓库演示音色 SHA256 `d309e805...8a55`。
- 输入为《春日影》MSST 人声的 20–50 秒片段，非原曲复制；使用 CUDA、RMVPE、无 index。
- 推理成功：HuBERT 1.25 秒、F0 5.31 秒、声码器 0.48 秒；输出 29.98 秒、40 kHz 单声道、mean -16.2 dB、peak -0.8 dB，SHA256 `a687ae5f...62f3`。
- 演示音色仅证明链路可运行，不是丰川祥子音色，也不进入发行包。

### GUI worker 全链路

- 通过与“开始翻唱”按钮相同的 `original_cover_worker` 对 257.84 秒《春日影》执行：标准化 → MSST → RVC → 44.1 kHz 对齐 → LUFS 混音 → WAV。
- 43.4 秒完成并发出 8/20/58/80/90/97/100% 进度；最终文件 257.84 秒、44.1 kHz、双声道 PCM24、mean -20.4 dB、peak -4.1 dB。
- 最终 SHA256 `ca70daf9...a16cc`，与输入 SHA256 `942b5120...85d5` 不同；不是复制原曲。
- 同一请求第二次运行 0.55 秒命中缓存，没有重复执行模型。

## 未通过/未执行

- DDSP 仅锁定源码 commit，尚无许可与格式均充分核验的测试音色，未标记可用。
- 丰川祥子 RVC/DDSP 权重来源与训练数据授权不明确，未下载、未推理。
- 标准 8–15 秒可再分发无伴奏干声、自动试听、Vevo2、GAME+DiffSinger 尚未真实验证。
- 没有以 mock、复制输入、静音、随机音频或其他模型试听代替上述结果。
