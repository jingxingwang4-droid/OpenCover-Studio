# 0.2 私人便携版构建与验证

0.2 将私人使用标记与改词功能开关分开。轻量版保留原词翻唱，完整版增加现有 GAME + DiffSinger 改词链路与 VocalParse 自动识词。两版使用相同的 RVC/DDSP 音色转换能力。

## 构建

在已具备本项目运行环境与模型的源码目录运行：

```powershell
.venv\Scripts\python.exe scripts/build_private_v02.py build lite
.venv\Scripts\python.exe scripts/build_private_v02.py assemble lite
.venv\Scripts\python.exe scripts/build_private_v02.py build full
.venv\Scripts\python.exe scripts/build_private_v02.py assemble full
```

目标为 `release/_private/测试版0.2_轻量版` 与 `release/_private/测试版0.2_完整版`。已有目标不会被直接覆盖。该目录被 Git 忽略；模型、私人音频和本地视频不进入仓库。

构建过程中只让 Windows 系统目录进入 DLL 搜索 PATH。曾发现宿主工具的 Poppler ICU 被误收，导致冻结 QtCore 缺少导出符号；普通源码运行不能发现此问题。新构建不再收集这些宿主 DLL。

各推理环境复制自身 Python 标准库与解释器，保留原有环境依赖，移除 `pyvenv.cfg`、启动器脚本和本机安装来源。editable 模块复制为真实包，VocalParse 保留指向包内 Alignment CUDA 依赖的相对路径。NumPy 等 wheel 的 `tests` 子包可能包含运行所需辅助代码，不能按目录名一律排除。

GUI 硬件检测优先选择便携 `runtime/python.exe`，仍兼容源码环境的 `runtime/Scripts/python.exe`。Worker 不写入固定 `runtime-tmpdir`，正常 GUI 启动后缓存和临时文件随当前软件根目录解析。

包内 RVC 使用由 Python 打开索引、FAISS 从内存反序列化的方式，避免中文路径经窄字符文件 API 打开失败。原模型和索引数据不改写。

## 验证与封装

```powershell
.venv\Scripts\python.exe scripts/verify_private_v02.py 'release/_private/测试版0.2_轻量版' audit
.venv\Scripts\python.exe scripts/verify_private_v02.py 'release/_private/测试版0.2_轻量版' original --engine rvc
.venv\Scripts\python.exe scripts/verify_private_v02.py 'release/_private/测试版0.2_轻量版' original --engine ddsp
.venv\Scripts\python.exe scripts/verify_private_v02.py 'release/_private/测试版0.2_完整版' lyric --engine native
```

音频测试默认使用本地保留的 12 秒回归样例，需在维护者工作区运行。探测时禁用用户 site-packages，并显式设置 `-B` 避免 `-I` 忽略环境变量后写出字节码。清洁环境保留 Windows 标准 ProgramFiles 变量，因为 NVIDIA NVML 需要这些系统位置；排除 Python/Conda/CUDA Toolkit 开发环境。

测试结束、确认没有运行中的包内程序后执行：

```powershell
.venv\Scripts\python.exe scripts/finalize_private_v02.py lite
.venv\Scripts\python.exe scripts/finalize_private_v02.py full
```

封装脚本把本次测试 workspace 移到本地证据目录，清除解释器字节码和构建来源，检查文本中的用户/开发机路径，生成包内逐文件 SHA-256。ZIP 生成后完整解压读取并验证 CRC，另输出压缩包 SHA-256。不要在校验/压缩期间启动成品或修改其内容。

## 2026-09-09 验证结果与边界

- 与本次改动相关的 75 项自动化测试通过。
- 最终轻量版冻结 GUI 离屏启动通过；完整版冻结 GUI 实际显示改词页、参数和硬件状态。
- 七个包内 Python/CUDA 运行时完成真实张量运算；运行前缀和模块路径都位于包内。
- 轻量版 RVC 和 DDSP 完成约 12 秒 UVR5 分离、转换与混音导出。
- 完整版以纯文本新旧歌词完成 GAME + DiffSinger GPU 端到端任务；VocalParse 完成真实 GPU 识词，结果仍需人工校对。
- 将完整版移至不同目录、使原发布路径不存在，并通过另一个盘符映射入口再次完成真实 RVC 和改词任务。
- 修改区间外 428,652 帧与标准化原曲解码后的样本完全一致。
- 冻结 Worker 不含固定临时目录选项；轻量版冻结模块中不含改词流水线。检查到的项目代码文件名为相对文件名。

硬件仅实测 RTX 5070 Ti Laptop GPU、591.86 驱动。包内为 CUDA 13.0 Modern 运行时；没有完成其他实体电脑、旧显卡或 Legacy CUDA 11.8 验收。目录/盘符映射测试不能替代其他电脑测试。生成歌词、旋律和最终混音的听感仍需用户验收。
