# OpenCover Studio v0.1.0 阶段交付报告

1. GUI 页面：首页、原词翻唱、改词翻唱 Beta、音色管理、任务记录、组件管理、设置，共七页。
2. EXE：Modern 与 Legacy 两个 `--windowed --onedir` 目录包均构建并真实启动。
3. 终端窗口：PyInstaller windowed 子系统，无用户可见控制台。
4. 已下载后端/运行时：只下载 FFmpeg；AI 后端均未下载，状态未伪装。
5. 版本：FFmpeg 9.0；MSST/RVC/DDSP/Vevo2/GAME/DiffSinger 未锁定 commit，不能发布为可用。
6. MSST 模型：未选定。具体模型的身份和许可没有核验。
7. RVC 初始音色：0 个。
8. DDSP 初始音色：0 个。
9. 初始头像：用户提供 `祥子音色头像.jpg`，作为未安装祥子模型占位；无其他初始音色。
10. 初始试听：0 个，不以标准干声冒充试听。
11. 标准试听干声：尚未取得满足真实无伴奏歌声、8–15 秒和明确再分发权的素材。
12. 丰川祥子 RVC：固定 ID 已列入清单，但模型来源、训练数据授权和分发许可未核验，未下载。
13. 丰川祥子 DDSP：同上。
14. 祥子推理：未执行；没有权重。
15. 用户模型导入：GUI 选择引擎、权重、index/配置、名称、简介、头像、试听后导入；计算 SHA256 并拒绝重复/覆盖。
16. 用户头像：PNG/JPG/JPEG/WebP，验证图片、修正 EXIF、居中裁切 512×512 WebP；没有头像则生成首字母占位。
17. 用户试听：当前直接导入验证过的 WAV；FFmpeg 统一转换入口已实现但尚未接入导入对话框的非 WAV 分支。
18. 自动试听：协议与真实状态已设计；因没有合法标准干声/后端不启用。
19. RVC 自动试听：未测试。
20. DDSP 自动试听：未测试。
21. MSST + RVC：未测试。
22. MSST + DDSP：未测试。
23. Vevo2 中文：未测试。
24. Vevo2 日语：未测试。
25. GAME + DiffSinger：未测试。
26. Modern/Legacy：现阶段 GUI 与 FFmpeg 内容相同；AI CUDA runtime 尚未装入，名称只代表目标发行配置。
27. GPU：RTX 5070 Ti Laptop，12172 MiB，驱动 591.86，驱动报告 CUDA 13.1；未安装 PyTorch，所以没有 CUDA tensor smoke test。
28. 包体积：Modern 575.3 MB；Legacy 575.3 MB。
29. 测试：12 项自动测试通过；Windows GUI 渲染、FFmpeg、双 EXE 启动和冻结 worker 双入口通过。
30. Git：源码、图片、文档和测试提交；`.venv`、FFmpeg、下载缓存、构建目录、工作区与权重按要求忽略。
31. 当前风险：真实翻唱主链仍不可用；后端 commit、模型、许可、CUDA runtime、自动试听干声尚未解决。
32. 下一优先级：锁定并安装 MSST+分离模型，然后锁定 RVC CLI+合法测试模型做单条真实 WAV；通过后再做 DDSP，最后才评估 Vevo2 和 DiffSinger 备用链。
