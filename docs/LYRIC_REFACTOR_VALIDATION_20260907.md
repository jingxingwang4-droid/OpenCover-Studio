# 改词翻唱重构与本机验证（2026-09-07）

当前交付是源码运行版。改词主链路、桌面入口、worker、构建脚本和回归测试已整理为固定 GAME + DiffSinger 方案。真实 GPU 任务已完成，听感尚未得到用户验收，不能宣称任意歌曲均能准确吐字或最终成品已经验收通过。

## 实现

- `pipelines/lyric_cover.py` 负责当前产品流程；历史生成器保留在 `legacy_lyric_cover.py` 及原有目录，当前入口不调用或回退。
- `lyrics/score_contract.py` 负责原词逐字时间到目标词谱的映射、音符分配、停顿和字段校验；`workers/diffsinger_score_frontend.py` 在句子上下文中解析拼音，明确每个音素。
- 连续转音使用一个持续元音；声学时长按音素校准，声码器仍使用完整原曲音高曲线，避免鼻韵母重复变成额外音节。GAME 的音符由连续 F0 复核，低能量分离底噪不能补成新音符。
- 默认音色为 DiffSinger 原生中文歌声，仍可选择 RVC/DDSP。原生升降调在保持输出帧数的前提下执行；不必要的音色转换不会被强制执行。
- 仅重生成改词短句，移除该区间原有和声。区间外直接使用标准化原曲的采样值。TXT/普通 LRC 的外部静音会按人声活动修正，内部停顿保留。
- 生成、转换和分离各自缓存。生成缓存覆盖代码、输入和后端配置，生成/转换成品校验 SHA256；词谱及 CUDA 证据留在任务/缓存目录。
- 试验过的句内原唱字音拼接未进入最终产品，因为边界误差会损伤相邻新字。整句未修改时仍直接保留原唱。

## 验证结果

本地证据汇总：`workspace/refactor_20260907/final_validation.json`。文件包括输出 SHA256、真实 GAME CUDA 日志路径、DiffSinger CUDA 信息、逐采样比较和识别结果。

| 检查 | 结果 |
| --- | --- |
| 全部自动化测试 | 125 passed；包括原词、历史流程和当前改词回归 |
| 离屏 GUI | 已构造和检查中文截图；默认原生歌声，无内部词谱上传前置条件 |
| 29.75 秒长段 | 8 行改词，7 个生成短句；真实 GAME + DiffSinger GPU 推理、混音导出完成 |
| 12 秒 LRC 输入 | QProcess 后台任务完成，只替换 2.14–4.25 秒 |
| 12 秒 TXT 输入 | 自动对齐与后台任务完成，只替换 2.12–4.40 秒，保留前奏 |
| 未改词区间 | 三个任务均与标准化原曲逐采样完全一致 |
| 原生升降调 | 440 Hz 测试音在 ±12 半音下分别为 880/220 Hz，输出帧数严格不变 |
| 长段生成干声识别 | VocalParse 独立识别 63/63 个字一致 |
| TXT 短段生成干声识别 | “我多想奔向你”6/6 个字一致 |
| 长段最终混音识别 | 62/63 个字一致；“第一场雨”中的“第”被识别成“的” |
| 长段旋律 | 各句相对自动词谱的音高绝对误差中位数 10–30 音分；有声评估帧在一半音内约 97.1%–100% |

音高统计剔除音符边缘各 40 ms，仅比较提取到 F0 的帧；各句有声覆盖率约 91.4%–98.3%。自动词谱本身也来自模型提取，统计不能代替原曲旋律听感比较。

## 试听与验收边界

完整输出：`workspace/outputs/long_source_改词_diffsinger_native_e2e_long.wav`。

生成干声：`workspace/refactor_20260907/e2e_long/audition/01_generated_lead.wav`。

重点核对 20.95–24.10 秒的“窗外第一场雨落纷纷”。提高人声比例的混音对照仍产生“第/的”识别差异，因此没有据此修改默认混音。ASR 差异既可能来自发音，也可能来自识别器；当前没有人工试听证据来判定。仍需分别确认生成主唱、合并人声和最终混音，尤其是改词区间有无残留原词。旧和声轨在改词区间被移除，未生成新和声。

12 秒 TXT 成品中，识别器把“奔向”识别成“能像”，也把未修改、且已证明逐采样保留的原唱句子识别错；单独识别原曲同样出现漏字和错字。该结果明确保留在 TXT 任务的 `asr.json`、`dry_asr.json`、`original_asr.json`，不能隐去混音差异或把干声通过解释为最终成品通过。

本次未构建新的发布 EXE，也未完成另一台电脑/另一块磁盘的便携包验收。原有私人包仍按其自身功能范围使用，不能用源码测试替代发行包验收。原词成熟能力保留，但本轮重点真实推理验证的是原生改词路线。

## 复现

在项目根目录使用现有环境：

```powershell
.venv/Scripts/python.exe workspace/refactor_20260907/validate.py tests
.venv/Scripts/python.exe workspace/refactor_20260907/validate.py long
.venv/Scripts/python.exe workspace/refactor_20260907/validate.py short --worker
.venv/Scripts/python.exe workspace/refactor_20260907/plain_worker.py
.venv/Scripts/python.exe workspace/refactor_20260907/short_asr.py
.venv/Scripts/python.exe workspace/refactor_20260907/short_compare_asr.py
.venv/Scripts/python.exe workspace/refactor_20260907/audit.py long asr
.venv/Scripts/python.exe workspace/refactor_20260907/audit.py long melody
.venv/Scripts/python.exe workspace/refactor_20260907/final_check.py
```

这些验证依赖本机已有《云烟成雨》实验音源和模型，不随公开仓库分发。原有接受/待接受的 DFS-01 音频未被覆盖。修改前逐文件备份保存在 `workspace/source_backups/refactor_20260907`；原有未提交改动保留，未执行 Git 提交或推送，B 站交接文件仍被忽略。
