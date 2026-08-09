# 资源调研与阶段结论（2026-08-10）

## 已确认接口

- MSST 固定 commit `e247dfe...`，使用官方 v1.0.0 MDX23C vocals SDR 10.17 配置和 checkpoint；全曲《春日影》CUDA 分离成功。
- RVC CLI 固定 commit `7b284a6...`，Fairseq fork 固定 `ff08af2...`；HuBERT、RMVPE 和官方模型仓库演示权重均已记录 SHA256，30 秒真实 CUDA 推理成功。
- DDSP-SVC 固定 commit `2e2ac5d...`；独立 Python 3.11.5 / PyTorch 2.9.1+cu130 环境已安装 ContentVec、RMVPE 与 PC-NSF-HiFiGAN，`main_reflow.py` 及应用 adapter 均完成真实推理。
- Vevo2 位于 Amphion：官方推理权重固定到 `2674843...`，剔除 optimizer 后 4.28 GB；中文/日文 9.16 秒真实生成均通过，12 GB 显卡峰值分配约 7.91 GB。
- GAME 固定 `4ad815c...`，官方 v1.0 small 模型真实导出 DiffSinger 可用的 MIDI/文本；DiffSinger 当前源码固定 `8a07f76...`，但仍需格式/许可匹配的 acoustic 歌声模型、G2P 和音素表。

## 祥子模型与试听源

按用户要求找到 TogetsuDo 发布的两套非官方社区权重：RVC v2 40k（commit `61676cf...`）和 DDSP-SVC 6.3 Reflow（commit `4b77b1a...`）。两者的 Hugging Face 模型卡都说明未经官方授权，license 字段为 `Other`，也未给出训练数据及再分发许可。项目因此将其标记为“本机已安装并实测、禁止打包再分发”，而非正式内置资源。两份 checkpoint 经 `weights_only` 加载与 unsafe-global 扫描后，分别完成 30 秒和《春日影》全曲真实转换。

标准干声采用 Freesound 用户 owstu 的 “Female Vocal 01.wav”：页面明确标注 CC0，内容为真实女声清唱音阶。HQ preview 转为 9.008 秒、44.1 kHz、16-bit 单声道 `neutral_melody.wav`，SHA256 `de75b75a...256d`。RVC 与 DDSP 的 `preview.wav` 均由这段干声经各自目标模型实际推理生成；标准干声本身从不作为试听结果播放。

## 仍未解决的问题

基础包要求的每个引擎 3～5 个可再分发初始音色仍未达到：当前只找到并验证祥子社区模型，且其条款不允许项目安全地公开再分发。Vevo2 与 GAME 固定样例已真实通过；DiffSinger 歌声模型和完整“对齐→切句→生成→拼接→音色转换”流水线仍缺失，因此改词页面保持禁用。

## 发布门槛

每个后端转为“可用”前必须记录：固定 commit/tag、依赖锁、代码许可证、模型许可证与 SHA256、真实输入和真实输出的音频信息、运行命令、耗时、输出非静音检查和人工试听结论。RVC 为适配 Windows、PyTorch 2.9、PyAV 12 与中文路径，应用了可审计的兼容修复：Fairseq 无符号链接安装、旧 checkpoint tuple、完整 index `Path` 保留、PyAV 模式、显式 `weights_only`，以及把 FAISS index 按哈希复制到 ASCII 临时路径后加载。
