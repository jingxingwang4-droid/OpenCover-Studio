# 第三方声明

Git 源码提交包含原创 MIT 代码、用户提供的四张图片与资源元数据；用户歌曲、`.venv`、下载缓存、第三方源码、运行环境、FFmpeg 解压目录和模型权重由 `.gitignore` 排除，不进入源码提交。MSST/RVC/DDSP 源码与模型只存在于本机开发环境，发行包是否可再分发必须按清单逐项判断。

- PySide6 / Qt for Python：LGPLv3/GPLv3 或 Qt 商业许可，详见 Qt 官方许可页面。
- FFmpeg：实际许可取决于构建选项；清单候选 Windows build 标注为 GPL，发布时必须随包附带对应许可与源代码获取方式。
- Music-Source-Separation-Training：MIT（须以锁定提交的 LICENSE 为准）。
- Retrieval-based-Voice-Conversion：MIT（须以锁定提交的 LICENSE 为准）。
- DDSP-SVC：MIT；预训练编码器、F0、vocoder 和用户模型有独立条款。
- Amphion / Vevo2：代码与预训练模型条款需分别复核，当前不再分发。
- OpenVPI GAME：MIT。
- OpenVPI DiffSinger：Apache-2.0；歌声模型、vocoder、词典和 G2P 不自动继承代码许可。

只有完成真实推理且后端 marker 为 `smoke_test_passed` 的组件才应在 GUI 中宣称可用；“已下载”不等于“可推理”。
