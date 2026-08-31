# ACE-Step 整合包原生改词翻唱交接

更新时间：2026-08-31（Asia/Shanghai）

## 1. 新对话唯一目标

不继承旧对话的实验思路，只按用户提供的视频文案，复刻 `downloads\ACE-Step-1.5.7z` 整合包里的原生 ACE-Step EDIT 改词翻唱链路。第一个真实测试改用带 LRC 的《云烟成雨》，先得到一份可直接试听、确实唱出新词且没有重复演唱的 ACE-Step 原生输出。

在这份原生输出被用户试听接受之前，不接 RVC/DDSP，不做人声分离、拼接、时长拉伸或混音，不改 OpenCover 产品链路，不处理打包问题。

## 2. 用户提供的视频文案（工作流的唯一产品依据）

> 开头买瓜翻唱的制作流程大致一样，只是用现成的原曲操作稍有区别。点击原音频，然后点分析按钮，模型自动提取原曲的音乐描述，然后勾选 EDIT 的选项，这里跟刚才直接发送过来不一样，描述和歌词都是空的，点 copy 按钮，把下面的线复制过来，分析生成的歌词删掉，换上原曲歌词用来对齐旋律，不要忘了加上英文标签，混音强度同样先设为 0.5，navg 调成三，歌曲描述不用动，翻唱歌词跟刚才一样，用你填好的歌词替换，同样加上英文标签，注意听头两句，还有结尾副歌和原曲的咬合程度，这是它最强的地方，买瓜翻唱完整版。如果没有复刻原来的旋律，可以把混音强度往上调 0.6、0.7 试。如果有些句子唱不出来，或者唱的还是原曲歌词，微调歌词的同时，继续调整 navg 参数，一般到 4 就能咬住你的翻唱歌词。大部分情况下只要翻唱歌词跟原曲字数相差不大，复写效果就不会太差。ACE-Step 翻唱也有不足，就是没法做音色迁移。比如我想用自己的声音来翻唱，它做不到。程序这里虽然设计了可以上传音色参考，但我实测下来基本没效果，它最多只能复刻原唱里的音色。

实施时把这段话直接翻译成一对一步骤，不根据旧代码自行发明算法。

## 3. 《云烟成雨》真实测试材料

必须用完整歌曲，禁止再用 5.52 秒或 12 秒的《惊鹊》预览片段。

- 原音频：`E:\project\一键翻唱工具包\assets\test_source\云烟成雨-M4Singer女声\云烟成雨-M4Singer女声+BGM完整混音.wav`
- 原 LRC：`E:\project\一键翻唱工具包\assets\test_source\云烟成雨-M4Singer女声\云烟成雨-M4Singer女声+BGM完整混音.lrc`
- 音频已有资料记录：48 kHz / 16-bit / 双声道 / 240.75 秒。
- 资源来源和权利边界：同目录 `SOURCE.md` 与 `dataset_license.md`。

首轮只做一个可判定的改词：

- 原第一句：`你的晚安 是下意识的恻隐`
- 新第一句：`窗外春风 吹过寂静的森林`
- 其余每句保持原 LRC 文本不变。

这组词已在历史回归请求 `workspace\jobs\dense_soulx_e2e_20260825\request.json` 中使用过。只借用这一句作为明确的 A/B 目标，不复用该 SoulX 任务的生成链路或输出。

## 4. 首轮必须逐步复刻的原生链路

1. 先解压/检查 `downloads\ACE-Step-1.5.7z` 的真实内容，找出整合包 UI 里“原音频”、“分析”、`EDIT`、`copy`、混音强度和 `navg` 对应的真实事件/函数/传参。
2. 优先直接驱动整合包的原生 UI 或原生后端函数跑一次。不允许先写一个“看起来相似”的自定义实现。
3. 上传上述 240.75 秒完整混音 WAV 作为原音频。
4. 点/调用“分析”，保存模型返回的原曲音乐描述和其他原生分析结果作为证据。
5. 勾选/启用 `EDIT`。
6. 按 `copy` 的真实行为，把当前音乐描述和歌词复制到 EDIT 的 source 字段。
7. 将 source lyrics 中分析生成的歌词删掉，改为上述 LRC 的原歌词文本；LRC 时间戳只用来保证句序和对照，是否传入时间戳必须以原生 UI 的真实处理为准。
8. source lyrics 和 target lyrics 使用完全相同的英文段落标签；标签种类与位置以整合包的分析结果/示例为准，不要只在全曲开头粗暴加一个 `[Verse]`。
9. target lyrics 使用同一份完整原歌词，仅替换第一句为“窗外春风 吹过寂静的森林”。
10. 分析得到的歌曲描述在 source/target 两侧保持不变。
11. 首轮只按视频设置：混音强度 `0.5`，`navg=3`。视频没提到的 `n_min`/`n_max`、sampler、steps、shift、CFG 等全部保持整合包原生当前值，不得自行设为 `0.6–1.0` 或其他值。
12. 一次只生成一个原生候选，输出到新的 `workspace\smoke\ace-step\yunyan_native_edit_*` 目录，保存完整请求参数、分析 JSON、日志、输出音频和 SHA-256。
13. 自动检查只能证明文件有效、时长合理、不静音、没有明显生成两遍；最终验收必须交给用户试听，重点听 00:17.71 的第一句是否真的变成新词。
14. 如果还唱原词或某句唱不出，第二轮才按视频把 `navg` 调到 `4`；如果旋律复刻不足，才将混音强度从 `0.5` 单变量调到 `0.6`，再必要时调到 `0.7`。

## 5. 已确认的本地 ACE-Step 资源

- 原始下载包：`E:\project\一键翻唱工具包\downloads\ACE-Step-1.5.7z`
- 下载包 SHA-256：`25402adb2a852a8792d0b562af7e9c7c5f84f35503542e0586fb6c033193e486`
- 当前本地后端：`E:\project\一键翻唱工具包\external_backends\ace_step`
- 已下载 DiT：`acestep-v15-turbo`
- 已下载分析 LM：`acestep-5Hz-lm-0.6B`（pt）
- 本机 GPU：NVIDIA GeForce RTX 5070 Ti Laptop GPU
- ACE 环境中已见 PyTorch：`2.7.1+cu128`

`external_backends\ace_step\flowedit_source` 是旧对话另外引入的 FlowEdit 源码，不能因为名字看起来对就默认它等同于 7z 整合包的原生实现。新对话必须先对照整合包本体的 UI 事件和运行时调用；只有证明函数和传参一致后才能复用。

## 6. 旧对话的失败与污染（不得当作成功样本）

- `assets\preview_sources\jingque_first_line.wav` 只有约 5.52 秒，不是完整原曲。
- `workspace\smoke\ace-step\source.wav` 是另一个约 12 秒的错误 smoke 夹具。
- 旧脚本擅自把《惊鹊》改词写成“轻舟渡过江南……”，并且曾把原词写错。
- 旧实现擅自把 `flow_edit_n_min/n_max` 设为 `0.6/1.0`；用户提供的视频文案没有这个操作。
- 旧实现在 ACE 输出后又进行分离、RVC、拉伸和混音，使失败原因无法判定。
- 用户已试听确认：一份输出跑调且重复演唱；另一份没有唱出新歌词。
- `external_backends\ace_step\backend.json` 里的 `listening_accepted: true` 不代表端到端改词成功；同一文件已有 `e2e_listening_accepted: false`。在用户接受《云烟成雨》新结果前，统一视为“未验收”。
- 以下输出均是无效样本，不要再试听或作为缓存复用：
  - `workspace\outputs\source_改词_toyokawa_sakiko_rvc_a7d886e898.wav`
  - `workspace\outputs\jingque_first_line_改词_toyokawa_sakiko_rvc_00c04658c3.wav`
  - `workspace\smoke\ace-step\flowedit_only_lyrics_navg3_strength050.wav`
  - `workspace\smoke\ace-step\flowedit_navg4_phrase_retry.wav`

## 7. 明确禁止事项

- 不要用《惊鹊》短片段或 `source.wav` 再测。
- 不要自己编原歌词或新歌词；原词以《云烟成雨》配套 LRC 为准，首轮只替换本文指定的第一句。
- 不要用自定义 repaint、硬拼接、分句重生成、SoulX 或其他生成器冒充 ACE-Step EDIT。
- 不要在首个 ACE 原生候选上做音色迁移；视频本身明确说 ACE-Step 基本只能保留/复刻原唱音色。
- 不要因为 CUDA 运行、输出非静音、文件时长正常或 ASR 有字就宣称成功；用户实际听到新词才算。
- 不要删除、还原或整体提交当前脏工作树。新对话只能动 ACE-Step 直接相关文件，修改前按 `AGENTS.md` 备份覆盖的源文件。
- 不要打包，不要修复 DDSP 模型元数据，不要处理与 ACE-Step 首轮验证无关的改动。

## 8. 代码与 Git 现状

- 项目根：`E:\project\一键翻唱工具包`
- 当前分支：`codex/add-codex-attribution`
- 当前 HEAD：`d986070 docs: credit OpenAI Codex assistance`
- 工作树有大量既有未提交改动，包含 SoulX、VocalParse、打包和 ACE-Step 实验，不得笼统 `git add -A`。
- 当前 ACE 相关未提交文件至少包括：
  - `src\opencover\workers\ace_step_runtime.py`
  - `tests\test_acestep_integration.py`
  - `scripts\smoke_acestep_lyric_e2e.py`
  - `docs\ACE_STEP_REPLICATION_RESEARCH.md`
  - `src\opencover\pipelines\lyric_cover.py` 的部分改动
  - `src\opencover\adapters\backends.py` 的部分改动
- 这些代码不是可验收成品。先用整合包原生链路产生通过试听的《云烟成雨》候选，再决定哪些实验代码保留、重写或丢弃。

## 9. 新对话的第一条回复和交付标准

新对话首先读本文档和项目 `AGENTS.md`，然后简短向用户确认：

> 我将不继承《惊鹊》短片段的任何实验参数。直接从 ACE-Step-1.5 整合包原生 UI 的“原音频 → 分析 → EDIT → copy → source 原词/目标新词 → 混音 0.5 → navg 3”开始，用 240.75 秒《云烟成雨》完整混音和配套 LRC，首轮只改第一句。

第一份交付必须同时提供：

1. 可点击试听的 ACE-Step 原生 WAV。
2. 该次请求的原生分析结果、source/target 描述、source/target 带英文标签歌词、混音强度、navg 和其他保持默认的参数证据。
3. 输入/输出时长、非静音和 SHA-256 校验。
4. 明确标记“等待用户试听”，不提前写入 `listening_accepted=true`。

