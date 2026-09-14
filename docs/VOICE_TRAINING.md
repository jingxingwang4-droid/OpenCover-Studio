# 音色训练

左侧「音色训练」支持音频文件或素材文件夹。填写音色名称、目标声部，然后选择：

- **仅合并音频**：按文件名自然顺序合并，例如 2 在 10 之前。统一为 40 kHz 单声道，素材之间插入 0.4 秒静音，输出 24 位 WAV。保留原文件。
- **合并并切片**：先合并，再按静音切分；长句按所选长度切片，保留少量重叠。
- **切片并开始训练**：切片、RMVPE 音高、HuBERT v2 特征、特征与时值校验、检索索引、GPU 训练、权重校验、导入音色管理。默认 100 轮、每批 4 个切片。

音频支持 WAV、FLAC、MP3、M4A、OGG、AAC。素材应为同一角色的清晰干声，避免伴奏、其他角色、长静音和明显失真。纯对白训练的高音歌唱表现需要实际试听确认。

进度在训练页及任务记录显示。可取消当前任务，任务记录支持重新生成。重新生成会创建独立任务；取消或失败不会导入半成品模型。运行训练时应依次执行其他 GPU 任务。

训练模型为 RVC v2、40 kHz、带音高引导，并自动建立 768 维检索索引。名称相同的多次训练会生成独立音色，不覆盖已有模型。新模型标记为实验音色，技术校验不能代替听感验收。

## 文件与安装

每次任务保存在 `workspace/jobs/<任务 ID>/training/`：

- `input/merged.wav`：合并母带。
- `source_manifest.json`：原始文件路径、SHA256、合并位置及长度。
- `logs/voice/0_gt_wavs/`：40 kHz 切片；`1_16k_wavs/` 为特征提取副本。
- `slice.log`、`f0.log`、`features.log`、`index.log`、`train.log`、`verify.log`：阶段日志。
- `assets/weights/voice.pth`、`voice.index`：训练模型及索引。
- `result.json`：导入后的音色 ID、位置与训练信息。

推理沿用项目自己的 RVC 环境，不操作第三方整合包。训练代码来自 [RVC 官方仓库](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/tree/7ef19867780cf703841ebafb565a4e47d1ea86ff)，固定提交 `7ef19867780cf703841ebafb565a4e47d1ea86ff`。预训练权重来自官方使用的 `lj1995/VoiceConversionWebUI`，安装脚本校验 SHA256。

开发安装命令：`.venv/Scripts/python.exe scripts/setup_rvc_training.py`。需要先安装 RVC 推理组件、Git 和 uv。源码与权重安装在 `external_backends/rvc_training`，补充依赖安装到项目 RVC 独立环境，缓存放在 E 盘项目内。脚本不会覆盖版本不符的已有训练源码或校验失败的已有权重。

当前桥接器针对单张 NVIDIA GPU，避免 Windows Gloo 的 GPU 通信问题；保留官方模型、损失和优化器实现。仅在本机 RTX 5070 Ti Laptop / PyTorch 2.9.1+cu130 验证，不据此宣称其他显卡兼容。

`scripts/build_local_app.py` 会更新本地桌面程序并备份被覆盖文件。训练运行脚本同时纳入 GUI/worker 打包；训练环境和权重需随本地安装保留，此次更新不是新的便携发行包。
