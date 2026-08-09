# OpenCover Studio

OpenCover Studio 是面向 Windows 普通用户的本地歌曲翻唱桌面应用。当前仓库是 **v0.1.0 阶段性可运行版本**：桌面 GUI、模型导入、任务隔离、SQLite、安全下载、音频标准化/混音和后端适配器均已实现；MSST + RVC 已在本机对 `assets/audio/春日影.wav` 完成真实 CUDA 推理。DDSP 和改词扩展仍会明确显示未就绪，不会输出伪造音频。

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
3. 可选上传 PNG/JPG/WebP 头像与真实 WAV 试听。无试听时按钮不会伪装成“试听”。
4. 拖入歌曲，先选 RVC/DDSP，再选对应音色，点击“开始翻唱”。已通过 smoke test 的后端会在独立 worker 中真实执行分离、转换、混音和导出；同一输入/音色/Key 会复用缓存。

当前尚未提供合法可再分发的 8–15 秒标准歌唱干声，所以“自动生成试听”未宣称可用。已下载的 RVC 官方仓库演示音色只用于 smoke test，不是丰川祥子音色，也不随源码或发行包再分发。资源真实状态详见 `config/resource_manifest.yaml` 与 `docs/RESOURCE_RESEARCH.md`。

若 `assets/背景1.*` 存在，GUI 优先将其用作固定背景并添加浅色内容蒙层；背景 2/3 保留但不轮播。`assets/祥子音色头像.jpg` 用于尚未安装的祥子固定音色占位卡，不代表相关 RVC/DDSP 权重已获得授权或通过推理。

## 构建

```powershell
./scripts/build_windows.ps1 Modern
./scripts/build_windows.ps1 Legacy
```

构建脚本使用 PyInstaller `--windowed --onedir`，生成无控制台窗口的目录式发行包。Modern/Legacy 当前区别是发行配置目标；CUDA/PyTorch 后端运行时尚未打包，因此不能宣称已完成 GPU 推理发行。

本机阶段构建位于 `dist/OpenCoverStudio-NVIDIA-Modern` 与 `dist/OpenCoverStudio-NVIDIA-Legacy`，各 575.4 MiB。`dist/` 按要求不进入 Git；详细证据见 `docs/TEST_REPORT.md` 和 `docs/FINAL_REPORT.md`。

## 安全与版权

- 原创代码采用 MIT；Qt/PySide6、FFmpeg、后端、模型、权重、音频和图片各自遵守其许可证。
- 模型导入计算 SHA256、拒绝重复和覆盖，不执行模型目录中的脚本。
- 下载器拒绝 HTML 冒充文件，并防御路径穿越和异常压缩比。
- 请仅使用得到授权的歌曲、模型、角色素材和训练数据。
