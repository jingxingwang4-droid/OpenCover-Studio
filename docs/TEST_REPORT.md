# 测试报告（2026-08-09）

## 环境

- Windows 10 build 26200
- Python 3.10.20（uv 管理的项目 `.venv`）
- PySide6 6.11.1
- GPU：NVIDIA GeForce RTX 5070 Ti Laptop GPU
- 显存：12172 MiB（应用显示 11.9 GB / 高质量）
- 驱动：591.86；`nvidia-smi` 报告 CUDA 13.1
- FFmpeg：9.0-essentials_build-www.gyan.dev，GPLv3 static build

驱动报告 CUDA 版本不等于 PyTorch CUDA runtime。由于本阶段没有安装 PyTorch 和 AI 后端，**未执行 CUDA tensor smoke test**，不得把 GPU 推理标记为已验证。

## 自动测试

命令：`.venv\Scripts\python.exe -m pytest`

结果：`12 passed`。

覆盖：

- JSON Lines worker 事件与进度边界；
- ZIP 正常解压、路径穿越拒绝；
- SQLite 任务生命周期与中文路径；
- RVC 权重、可选 index、头像、用户上传 WAV 试听导入；
- 模型 SHA256 重复拒绝；
- 缺少试听时保持 `preview_source=none`；
- 真实非静音波形的响度混音和 WAV 输出；
- 未安装 FFmpeg/MSST/RVC 时的 preflight 明确失败；
- 资源清单必填字段、唯一 ID 与已安装资源哈希；
- 七页面主窗口离屏构造。

## 手工/集成验证

- 使用真实 Windows Qt 平台渲染 1180×760 首页截图，中文正常，`背景1.jpg` 优先加载并应用浅色蒙层。
- `ffmpeg -version` 和 `ffprobe -version` 成功，版本均为 9.0 essentials build。
- Modern 与 Legacy 均由 PyInstaller `--windowed --onedir` 构建；启动后进程保持运行。
- 两个冻结 EXE 的 `--worker missing-request.json` 均快速返回代码 1，没有误开第二个 GUI。
- 最终每个发行目录 458 个文件、575.3 MB；无用户可见控制台窗口。

## 未执行测试

没有来源/许可清楚的初始 RVC、DDSP 或祥子权重，没有 MSST 分离模型，也没有合法标准歌唱干声。因此没有 MSST+RVC、MSST+DDSP、祥子双模型、自动模型试听、Vevo2、GAME+DiffSinger 或 CUDA 推理结果。没有用 mock、复制输入、静音、随机音频或其他模型试听代替。
