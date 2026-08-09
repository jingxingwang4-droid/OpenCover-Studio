# 第三方声明

Git 源码提交包含原创 MIT 代码、用户提供的四张图片与资源元数据；`.venv`、下载缓存和 FFmpeg 解压目录由 `.gitignore` 排除，不进入源码提交。当前不包含 MSST、RVC、DDSP-SVC、Vevo2、GAME、DiffSinger 代码或任何模型权重。

- PySide6 / Qt for Python：LGPLv3/GPLv3 或 Qt 商业许可，详见 Qt 官方许可页面。
- FFmpeg：实际许可取决于构建选项；清单候选 Windows build 标注为 GPL，发布时必须随包附带对应许可与源代码获取方式。
- Music-Source-Separation-Training：MIT（须以锁定提交的 LICENSE 为准）。
- Retrieval-based-Voice-Conversion：MIT（须以锁定提交的 LICENSE 为准）。
- DDSP-SVC：MIT；预训练编码器、F0、vocoder 和用户模型有独立条款。
- Amphion / Vevo2：代码与预训练模型条款需分别复核，当前不再分发。
- OpenVPI GAME：MIT。
- OpenVPI DiffSinger：Apache-2.0；歌声模型、vocoder、词典和 G2P 不自动继承代码许可。

任何 `status` 不是 `installed_verified` 的条目都不应被发行说明宣称为可用。
