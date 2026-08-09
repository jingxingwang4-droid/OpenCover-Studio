# 资源调研与阶段结论（2026-08-10）

## 已确认接口

- MSST 固定 commit `e247dfe...`，使用官方 v1.0.0 MDX23C vocals SDR 10.17 配置和 checkpoint；全曲《春日影》CUDA 分离成功。
- RVC CLI 固定 commit `7b284a6...`，Fairseq fork 固定 `ff08af2...`；HuBERT、RMVPE 和官方模型仓库演示权重均已记录 SHA256，30 秒真实 CUDA 推理成功。
- DDSP-SVC 官方 README 给出 `main_reflow.py` 非实时转换接口，并明确提到 Windows + Python 3.11 + CUDA 13 组合可工作。
- Vevo2 位于 Amphion，官方快速开始会自动下载多个 Hugging Face 权重；体积、中文/日语歌词编辑质量与 12GB 显存适配均未实测。
- GAME 官方推理可导出 DiffSinger 数据格式兼容的 MIDI/文本；DiffSinger 仍需合法歌声模型、vocoder、G2P 和音素表。

## 没有解决的问题

尚未找到身份、训练数据授权与再分发许可均明确的丰川祥子 RVC/DDSP 权重。角色模型与试听可能涉及角色权利、声音权和非商业限制；在来源不明确时不下载或随包发布。DDSP 当前只有锁定源码，未取得与当前 5/6 系格式匹配且来源条款充分的普通测试模型，因此仍不可用。

同样尚未找到满足“8–15 秒、真实无伴奏歌唱、许可明确允许再分发”的标准干声。项目因此保留目录和生成协议，但不放入合成音、空白 WAV、随机声音或其他模型试听作为替代。

## 发布门槛

每个后端转为“可用”前必须记录：固定 commit/tag、依赖锁、代码许可证、模型许可证与 SHA256、真实输入和真实输出的音频信息、运行命令、耗时、输出非静音检查和人工试听结论。RVC 为适配 Windows 普通用户、PyTorch 2.9 和 PyAV 12，应用了四个最小兼容修复：Fairseq 无符号链接安装、旧 checkpoint tuple、完整 `Path` 保留、PyAV 模式与 PyTorch `weights_only` 显式设置。
