# 《惊鹊》第一句本机试听源

- 歌词：“白马过了离原，三月的天，春风漫草野”。
- 本机源文件：`assets/test_source/兰音Reine,扇宝 - 惊鹊.mp3`。
- 处理链：本机 UVR5 主唱分离结果 → Whisper 强制对齐第一句 1.98–7.04 秒 → 保留前后缓冲并淡入淡出。
- 输出：`jingque_first_line.wav`，5.520 秒，44.1 kHz，单声道 PCM16，SHA256 `def173c3d7b3fa9a9b7e819d5c68062a2afaabd97d41534bb8a8cac7d5945114`。
- 该片段只用于用户本机的模型转换与试听；歌曲及衍生片段的公开再分发授权未核验，因此 WAV 被 Git 和公开构建排除。
- 线上歌词核对：<https://vocaloidlyrics.fandom.com/wiki/%E6%83%8A%E9%B9%8A_%28J%C4%ABng_Qu%C3%A8%29>

这个文件是试听的模型输入，不是可直接播放给用户的音色结果。每个音色仍必须经过对应 RVC/DDSP 模型真实推理后生成独立 `preview.wav`。
