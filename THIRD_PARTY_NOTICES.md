# 第三方声明

Git 源码提交包含原创 MIT 代码、用户提供的图片与资源元数据；用户歌曲、`.venv`、下载缓存、第三方源码、运行环境、FFmpeg 解压目录和模型权重由 `.gitignore` 排除，不进入源码提交。白菜与祥子 RVC 权重只在本机使用，不进入公开发行包。

- PySide6 / Qt for Python：LGPLv3/GPLv3 或 Qt 商业许可，详见 Qt 官方许可页面。
- FFmpeg：实际许可取决于构建选项；清单候选 Windows build 标注为 GPL，发布时必须随包附带对应许可与源代码获取方式。
- Music-Source-Separation-Training：MIT（须以锁定提交的 LICENSE 为准）。
- Ultimate Vocal Remover GUI 与 audio-separator：代码均为 MIT；UVR 模型权重作者和再分发条款需分别核验。当前使用的 `Voc_FT`、`5_HP-Karaoke-UVR` 与 anvuew MelBand 去混响权重只作本机推理，排除在 Git 和公开发行包之外；anvuew 模型仓库标注 GPL-3.0。
- Retrieval-based-Voice-Conversion：MIT（须以锁定提交的 LICENSE 为准）。
- 白菜 357k：来自 RVC 官方模型仓库示例，训练数据条款未单列，只作本机使用。
- 本机丰川祥子 RVC 模型的来源和再分发许可未知，不进入公开包。
- DDSP-SVC：MIT；预训练编码器、F0、vocoder 和用户模型有独立条款。
- ContentVec `lengyue233/content-vec-best`：模型卡未声明许可证，当前不再分发。
- OpenVPI PC-NSF-HiFiGAN：权重声明 CC BY-NC-SA 4.0，只安装于本机环境。
- RMVPE：来自 yxlllc/RMVPE 官方 230917 release；权重未见单独分发条款，当前不再分发。
- `TogetsuDo/sakiko-ddsp-svc-6.3`：非官方社区角色音色，未声明再分发授权，只作本机测试。
- `yuier0721/DDSP-SVC_6.3_pcr-kokkoro_2.0`：模型卡标 MIT，但角色与训练音频权利不随模型卡自动授予，只作本机兼容测试。
- `assets/preview_sources/neutral_melody.wav`：由 owstu 的 Freesound “Female Vocal 01.wav” CC0 素材转换，允许复制、修改和再分发。
- Amphion / Vevo2：代码与预训练模型条款需分别复核，当前不再分发。
- RMSnow/Vevo2 权重：CC BY-NC-ND 4.0；已本机实测，不再分发。
- OpenVPI GAME：代码 MIT；v1.0 模型 CC BY-NC-SA 4.0，不进入公开发行包。
- OpenVPI DiffSinger：Apache-2.0；歌声模型、vocoder、词典和 G2P 不自动继承代码许可。
- MoonInTheRiver 原版 DiffSinger/demo 代码：MIT。`Silentlin/DiffSinger` demo 中的 OpenCpop acoustic、pitch extractor 与 NSF-HiFiGAN 权重没有随文件提供独立模型/训练数据许可；只作本机兼容性验证，不进入公开发行包。
- Stable-ts 2.19.1：MIT；固定 commit `e312072...`。上游于 2026-05-30 归档并声明暂停开发，因此作为隔离可选组件使用，不导入 GUI 主进程。
- OpenAI Whisper 20250625 与官方 multilingual `base` 模型：MIT；源码 commit `5f86d1d...`，模型 SHA256 `ed3a0b6b...6e34e`。模型随本机改词扩展使用，公开包只含下载元数据和 runner。
- YingMusic-Singer-Plus：项目声明代码和主要模型权重为 CC BY 4.0，但 Stable Audio 2 VAE 代码/权重受 Stability AI Community License 约束；官方 Windows 预构建尚未发布，当前仅作为研究候选，不下载、不打包、不宣称可用。

只有完成真实推理且后端 marker 为 `smoke_test_passed` 的组件才应在 GUI 中宣称可用；“已下载”不等于“可推理”。
