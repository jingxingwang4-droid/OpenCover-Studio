# 资源调研与阶段结论（2026-08-10）

## 已确认接口

- MSST 固定 commit `e247dfe...`，使用官方 v1.0.0 MDX23C vocals SDR 10.17 配置和 checkpoint；全曲《春日影》CUDA 分离成功。
- RVC CLI 固定 commit `7b284a6...`，Fairseq fork 固定 `ff08af2...`；HuBERT、RMVPE 和官方模型仓库演示权重均已记录 SHA256，30 秒真实 CUDA 推理成功。
- DDSP-SVC 固定 commit `2e2ac5d...`；独立 Python 3.11.5 / PyTorch 2.9.1+cu130 环境已安装 ContentVec、RMVPE 与 PC-NSF-HiFiGAN，`main_reflow.py` 及应用 adapter 均完成真实推理。
- Vevo2 位于 Amphion：官方推理权重固定到 `2674843...`，剔除 optimizer 后 4.28 GB；中文/日文 9.16 秒真实生成均通过，12 GB 显卡峰值分配约 7.91 GB。
- GAME 固定 `4ad815c...`，官方 v1.0 small 模型真实导出 DiffSinger 可用的 MIDI/文本。当前 OpenVPI DiffSinger 仍不附模型；为完成可核验回退，另固定原版官方仓库所链接的 Hugging Face demo commit `6a08cdd...`，使用其中 OpenCpop acoustic、pitch extractor、NSF-HiFiGAN 和 pypinyin 0.43.0，已完成固定样例、GAME 动态旋律和完整音色转换三层实测。
- Vevo2 已进入 GUI/JobManager 主路径：LRC/逐行短句、歌词密度检查、一次加载批量生成、时长拼接、RVC/DDSP 和混音均有真实打包 worker 证据。
- 自动对齐采用 Stable-ts 2.19.1 `model.align` + OpenAI Whisper 20250625 multilingual base，分别固定 `e312072...` / `5f86d1d...`。独立 Python 3.10 / torch 2.9.1+cu130 环境对 Whisper 官方 JFK 正确原文完成 22 词强制对齐（0 个零时长词、CUDA 峰值 469,291,008 bytes）；对《春日影》20–50 秒已分离人声完成日语转写及四行强制对齐，四个句级时间严格有效，48 个词中 1 个细粒度 token 为零时长。流水线只使用经过行数、正时长和严格递增校验的句级边界。

## 祥子模型与试听源

按用户要求找到 TogetsuDo 发布的两套非官方社区权重：RVC v2 40k（commit `61676cf...`）和 DDSP-SVC 6.3 Reflow（commit `4b77b1a...`）。两者的 Hugging Face 模型卡都说明未经官方授权，license 字段为 `Other`，也未给出训练数据及再分发许可。项目因此将其标记为“本机已安装并实测、禁止打包再分发”，而非正式内置资源。两份 checkpoint 经 `weights_only` 加载与 unsafe-global 扫描后，分别完成 30 秒和《春日影》全曲真实转换。

标准干声采用 Freesound 用户 owstu 的 “Female Vocal 01.wav”：页面明确标注 CC0，内容为真实女声清唱音阶。HQ preview 转为 9.008 秒、44.1 kHz、16-bit 单声道 `neutral_melody.wav`，SHA256 `de75b75a...256d`。RVC 与 DDSP 的 `preview.wav` 均由这段干声经各自目标模型实际推理生成；标准干声本身从不作为试听结果播放。

另核验 `yuier0721/DDSP-SVC_6.3_pcr-kokkoro_2.0` revision `aca0687...` 的 `model_500.pt`：219,737,099 bytes、LFS SHA256 `cca82132...dbb`，unsafe globals 为空、weights-only 加载成功并生成 9.009 秒真实试听。模型卡虽标 MIT，训练数据来自角色衍生语音，故不据此推断角色/音频再分发权。

## 可再分发 RVC 初始音色

2026-08-10 固定并验证三套公开内置 RVC。`Saisho-Utane/Saisho-Model-RVC` revision `7a61b17...` 的模型卡明确说明使用作者自有声音训练，并以 CC BY 4.0 允许带署名的公开、修改、商业使用与再分发；57,577,658-byte `model.pth` SHA256 为 `82312a29...f3d35`。`Nekochu/RVC-VCTK_Voice-sample` revision `005c2f9...` 明确训练自 VCTK，并把模型仓库标为 Apache-2.0；选择 p231 女声与 p226 男声两个 250-epoch checkpoint，SHA256 分别为 `26d3c122...e372`、`3c4c2e8e...6693`。CSTR VCTK 原始语料为 CC BY 4.0，作者/数据集署名进入第三方声明。

三个 checkpoint 的 unsafe globals 都为空，`torch.load(weights_only=True)` 均返回含 `config`/`weight` 的标准 RVC 字典。为减小包体并覆盖“无 index 仍可使用”，三个音色都走 RMVPE、`index_rate=0`；CC0 标准干声分别得到 9.000 秒的 48/40/40 kHz 有限非静音输出，SHA256 `52af2f59...e440`、`29deafb9...12c2`、`d651b9c6...0a9e`，且互不相同、不等于输入。头像不采用模型仓库人物图，而由项目生成 512×512 的 S/F/M 占位图。`scripts/install_bundled_rvc_voices.py` 可从固定 revision 断点下载、校验大小/SHA256、执行 checkpoint 安全扫描并可选重建试听；公开构建只复制这三个 ID。

## 仍未解决的问题

RVC 已达到三套可再分发初始音色；DDSP 仍未达到 3～5 套。当前可找到并适配的 DDSP 社区音色主要基于商业角色语音，仓库的 MIT 标签不足以证明训练声音与角色权利，故只作本机兼容测试。Vevo2 主路径和中文 GAME + DiffSinger 回退均已真实接入，但 DiffSinger 旧版权重未给出独立模型/数据许可，故只在本机完整包可用。无 LRC 原歌词现可自动强制对齐；非中文 DiffSinger 回退仍未实现，且真实歌声的歌词准确性仍取决于用户文本和录音质量。

2026-08-10 追加复核了三个方向。WhisperX 是 BSD-2-Clause 的语音 ASR/词级对齐工具，但没有直接把用户给定完整歌词强制对齐到音频的同等接口；活跃的 whisper-timestamped 是 AGPL-3.0，也以转写后估时为主。Stable-ts 虽在 2026-05-30 归档，却是 MIT 且明确支持 `model.align(audio, plain_text, language)`，因此固定最后提交、隔离安装并以真实音频验证，界面会披露其可选组件状态。YingMusic-Singer-Plus 官方方案直接接受旋律音频和新歌词，不要求人工音素级对齐；源码 HEAD `baa409c...`，官方模型 revision `9b3f444...`，五个主要 checkpoint 合计 13,052,111,592 bytes。其代码/主权重为 CC BY 4.0，但 Stable Audio VAE 使用单独的 Stability AI Community License，官方 Windows 预构建仍标记 Coming soon，批处理示例还面向 4/8 GPU，故只登记为后续候选。

RVC 复核同时排除了 AEmotionStudio（底模转换而非独立音色）、Razer112/Public_Models（专用条款禁止未经书面许可再分发）以及只有代码仓库 MIT 标签、没有声音授权的角色/真人模型。DDSP-SVC 标签下的公开候选仅有基础依赖仓库和商业角色衍生模型，尚未找到三套像 Saisho/VCTK 一样能同时证明 checkpoint 许可与训练声音来源的可适配权重；公开 DDSP 初始列表继续留空，而不是把仓库标签冒充声音授权。

## 发布门槛

每个后端转为“可用”前必须记录：固定 commit/tag、依赖锁、代码许可证、模型许可证与 SHA256、真实输入和真实输出的音频信息、运行命令、耗时、输出非静音检查和人工试听结论。RVC 为适配 Windows、PyTorch 2.9、PyAV 12 与中文路径，应用了可审计的兼容修复：Fairseq 无符号链接安装、旧 checkpoint tuple、完整 index `Path` 保留、PyAV 模式、显式 `weights_only`，以及把 FAISS index 按哈希复制到 ASCII 临时路径后加载。
