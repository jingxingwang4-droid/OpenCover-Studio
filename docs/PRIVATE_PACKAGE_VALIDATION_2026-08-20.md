# 私人跨电脑包验收记录（2026-08-20）

目标目录：`release_private/OCS-Private-Modern`

## 构建与便携运行时

- PyInstaller 6.22.0 / Python 3.10.20，Modern GUI 为 windowed onedir，Worker 为独立 console-subsystem onefile，并由 GUI 隐藏启动。
- 组装后未清理时为 34.55 GiB；包含 MSST、UVR5、RVC、DDSP、Vevo2、GAME、legacy DiffSinger、Whisper/Stable-ts 对齐和 ESPnet VISinger2。
- MSST、UVR5、RVC、DDSP、Vevo2、GAME、Alignment、VISinger2 八套环境均生成包内 `runtime/python.exe`；探针确认 `sys.prefix == sys.base_prefix == 包内 runtime`。
- RVC 的 editable fairseq 已复制为包内实体模块，冻结探针导入路径位于私人包内，不再引用开发工作区。
- 各后端分别从私人包目录成功导入其实际依赖；PyTorch 环境均报告 `2.9.1+cu130` / CUDA runtime 13.0。目标笔记本仍需要足够新的 NVIDIA 驱动。

## 冻结 EXE 与真实任务

- 完整源码测试：71 项通过。此前一次全量测试在连续加载多套 CUDA DLL 后出现 Windows 原生 access violation；定向测试 8 项和随后全量 71 项均通过，没有复现，因此保留此记录而不伪装成从未发生。
- 冻结 GUI 以 offscreen 模式隐藏启动 8 秒后仍存活，随后仅终止该测试进程。
- 冻结 Worker 真实执行 `UVR5 → 丰川祥子 RVC → 校正 → 混音 → WAV` 成功：9.008163 秒、44.1 kHz、双声道、RMS 0.076908、peak 0.361680、finite/nonzero，SHA256 `03c20aabcaa2ddb21a67ca5eaf6d093e3c8ac24eeb4ba278ee79a6cae7c25062`。
- 冻结 Worker 复用分离缓存执行 `可可萝 DDSP → 校正 → 混音 → WAV` 成功：9.009342 秒、44.1 kHz、双声道、RMS 0.091975、peak 0.373690、finite/nonzero，SHA256 `0b3265927495899aec0c0ec3836be28c01132577ce2fc5fb2bb3863104719d05`。
- 输入 CC0 干声 SHA256 为 `de75b75a917a9898e48da59510e86793aba5e7b788d215c44942b9a31bac256d`；两份输出哈希均与输入及彼此不同。
- 丰川祥子 DDSP 被当前质量策略明确拒绝选择，原因是既有真实歌曲验证不合格；这不是便携环境故障。本包保留模型文件作私人历史复验，但不把它冒充可用音色。

## 尚未在目标笔记本验证

- 目标笔记本的具体 GPU、VRAM、NVIDIA 驱动及 CUDA 驱动兼容性未知。
- 本轮只在当前 RTX 5070 Ti 环境构建并完成真实冻结任务；不能据此声明另一台实体机器已兼容。
- 改词翻唱仍有祥子 RVC 普通话吐字与音符落字听感问题，不作为稳定功能承诺。
- 压缩包仅供同一用户自己的电脑间迁移，不能公开上传、出售或转发。
