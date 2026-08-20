# 资源来源索引

机器可读清单位于 `config/resource_manifest.yaml`。当前核验来源：

- FFmpeg 官方 Windows 下载导航：https://ffmpeg.org/download.html#build-windows
- MSST：https://github.com/ZFTurbo/Music-Source-Separation-Training
- Ultimate Vocal Remover GUI：https://github.com/Anjok07/ultimatevocalremovergui （本机固定 commit `5517e0c...`）
- UVR5 无界面运行器 audio-separator：https://github.com/nomadkaraoke/python-audio-separator （本机版本 `0.44.5`）
- RVC CLI：https://github.com/RVC-Project/Retrieval-based-Voice-Conversion
- RVC 官方基础模型/演示权重：https://huggingface.co/lj1995/VoiceConversionWebUI
- DDSP-SVC：https://github.com/yxlllc/DDSP-SVC
- DDSP ContentVec：https://huggingface.co/lengyue233/content-vec-best
- DDSP RMVPE：https://github.com/yxlllc/RMVPE/releases/tag/230917
- OpenVPI PC-NSF-HiFiGAN：https://github.com/openvpi/vocoders/releases/tag/pc-nsf-hifigan-44.1k-hop512-128bin-2025.02
- 丰川祥子 RVC（非官方社区模型）：https://huggingface.co/TogetsuDo/sakiko-rvc
- 丰川祥子 DDSP（非官方社区模型）：https://huggingface.co/TogetsuDo/sakiko-ddsp-svc-6.3
- 可可萝 DDSP-SVC 6.3 中文社区模型（本机测试）：https://huggingface.co/yuier0721/DDSP-SVC_6.3_pcr-kokkoro_2.0
- CC0 标准试听干声（owstu / Female Vocal 01）：https://freesound.org/people/owstu/sounds/508815/
- Amphion Vevo2：https://github.com/open-mmlab/Amphion/tree/main/models/svc/vevo2
- Vevo2 官方权重：https://huggingface.co/RMSnow/Vevo2
- GAME：https://github.com/openvpi/GAME
- GAME v1.0 模型：https://github.com/openvpi/GAME/releases/tag/v1.0.0
- DiffSinger：https://github.com/openvpi/DiffSinger
- 原版 DiffSinger 官方仓库（MIT）：https://github.com/MoonInTheRiver/DiffSinger
- 原版官方预训练模型 release：https://github.com/MoonInTheRiver/DiffSinger/releases/tag/pretrain-model
- 原版官方 README 链接的 Hugging Face demo/权重：https://huggingface.co/spaces/Silentlin/DiffSinger
- Stable-ts 强制对齐（MIT，固定归档前最后提交）：https://github.com/jianfch/stable-ts
- OpenAI Whisper 源码、模型卡与官方模型：https://github.com/openai/whisper
- YingMusic-Singer-Plus（无需精细对齐的未来改词候选）：https://github.com/ASLP-lab/YingMusic-Singer-Plus
- YingMusic-Singer-Plus 官方权重：https://huggingface.co/ASLP-lab/YingMusic-Singer-Plus
- 公共领域分离测试音频：https://commons.wikimedia.org/wiki/File:Irene_Dunne_singing_in_Love_Affair.ogg

未填写的下载地址、哈希、作者或许可表示尚未核验，而不是“任意镜像均可”。

UVR5 本机链使用 `UVR-MDX-NET-Voc_FT.onnx` 分离总人声/伴奏，再用 `5_HP-Karaoke-UVR.pth` 拆分主唱与和声，最后用 `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt` 对主唱强去混响。模型权重保留在被 Git 忽略的 `external_backends/uvr5/models_runtime/`，不进入公开发行包；真实测试、大小与 SHA256 记录在同目录 `backend.json`。
