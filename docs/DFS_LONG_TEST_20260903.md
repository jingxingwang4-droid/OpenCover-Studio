# DFS-LONG-01 长段改词试听记录（2026-09-03）

## 结论

当前长段基线为 `B_short_DFS01_first_pair`。

- 开头非人声喘息：已解决。
- 前两句音准：仍有部分跑调，暂不继续修复。
- 后六句：用户反馈效果很好，后续必须锁定并复用，不得重新生成。
- 整体状态：阶段性保留，不标记为完整听感通过。

用户原始反馈：

> B解决了喘息的问题，但是还是有些跑调。总之先这样吧。

## 测试范围

- 原曲：`assets/test_source/云烟成雨-M4Singer女声/云烟成雨-M4Singer女声+BGM完整混音.wav`
- 全曲区间：71.00–100.75 秒
- 输出时长：29.75 秒
- 改词核心：片段内 2.14–29.04 秒
- 构谱：GAME 1.0 small，本轮真实 CUDA 连续音高提取
- 生成：legacy DiffSinger OpenCpop，单次完整长段生成
- 分离：仅 UVR5，未使用 MSST
- 和声策略：DiffSinger 未生成可靠新词和声；改词区间不混回旧歌词和声，和声证据层为显式静音

## 目标歌词

1. 我多想奔向你
2. 穿过漫长黑夜去相遇
3. 晨光中温柔的剪影
4. 照亮我回家的路径
5. 我多想拥抱你
6. 那些心里话都说给你
7. 窗外第一场雨落纷纷
8. 并肩走过每个清晨

## 保留产物

实验根目录（由 `.gitignore` 排除，不提交大音频）：

`workspace/experiments/yunyan_diffsinger_long_20260903`

当前 B 最终混音：

`workspace/experiments/yunyan_diffsinger_long_20260903/DFS-LONG-01/repair_ab/B_short_DFS01_first_pair/04_final_mix.wav`

- SHA-256：`e41a426a7d019a576ceb13204b3d57990983af8e4b25fc5d042d33e50d69bd67`
- 采样率：48 kHz
- 声道：双声道
- 时长：29.75 秒
- 峰值：约 0.596
- RMS：约 -17.945 dBFS

当前 B 生成主唱：

`workspace/experiments/yunyan_diffsinger_long_20260903/DFS-LONG-01/repair_ab/B_short_DFS01_first_pair/01_generated_lead.wav`

- SHA-256：`9cbb6aceeef191ed2784cb86ff671be3482f850c0561172024ec63684cd71076`

原生 DiffSinger 输出：

`workspace/experiments/yunyan_diffsinger_long_20260903/DFS-LONG-01/native/lead_native_raw.wav`

- SHA-256：`ced6a5415a57c9b0257b977e39cc75def0570f1213e97f8e3c74ad917cbe05b7`
- 原生采样率：24 kHz
- 原生时长：28.048 秒

完整参数、四层输出与保存性检查：

- `workspace/experiments/yunyan_diffsinger_long_20260903/DFS-LONG-01/manifest.json`
- `workspace/experiments/yunyan_diffsinger_long_20260903/DFS-LONG-01/repair_ab/manifest.json`
- `workspace/experiments/yunyan_diffsinger_long_20260903/VALIDATION.json`

## 局部修复边界

- 0.00–1.78 秒：清除生成主唱中的异常喘息。
- 1.78–1.90 秒：平滑淡入。
- 0.00–8.40 秒：B 使用先前较好的短版 DFS-01 前两句。
- 8.25–8.40 秒：在无声间隙交叉淡化。
- 8.40–29.75 秒：主唱和最终混音与原长版逐采样一致。

## 后续约束

若后续继续修复跑调：

1. 只处理前两句，不重生成后六句。
2. 以当前 B 为听感基线，先交付短 A/B。
3. 每次只改变一个音高或构谱变量。
4. 必须验证 8.40 秒以后与当前 B 逐采样一致。
5. 未经用户试听确认，不得把跑调问题标记为已解决。
