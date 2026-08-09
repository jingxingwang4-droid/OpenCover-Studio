# OpenCover Studio v0.1.0 阶段交付报告

1. GUI：首页、原词翻唱、改词翻唱 Beta、音色管理、任务记录、组件管理、设置，共七页。
2. 启动：`app.py` 双击会自动转交项目 `pythonw.exe`；Modern/Legacy 为 `--windowed --onedir` EXE，无用户可见终端。
3. 已下载后端：MSST `e247dfe...`、RVC CLI `7b284a6...`、Fairseq `ff08af2...`、DDSP-SVC `2e2ac5...`；均来自官方 GitHub。
4. MSST：官方 v1.0.0 MDX23C vocals SDR 10.17 已校验并在 RTX 5070 Ti 上完成公共领域样例和《春日影》全曲真实分离。
5. RVC：官方 HuBERT/RMVPE 与官方模型仓库演示音色已校验；《春日影》分离人声 30 秒真实推理成功。该音色只作 smoke test，不是祥子音色、不随包再分发。
6. DDSP：源码已锁定，但运行环境、普通测试模型和真实 WAV 尚未全部验证，GUI 保持不可用。
7. 初始音色/试听：无可再分发的正式内置音色；没有用测试模型冒充内置音色。用户可从 GUI 导入 RVC `.pth`/可选 `.index` 或 DDSP 权重/配置，上传头像和真实试听。
8. 头像：使用用户提供的 `assets/祥子音色头像.jpg` 作为未安装祥子卡片素材；不联网替换。支持 PNG/JPG/JPEG/WebP、EXIF 修正、512×512 裁切和首字母占位。
9. 祥子双模型：清单保留固定 ID，但未找到身份、训练数据授权和再分发许可都明确的权重，故未下载、未生成试听。
10. 标准干声/自动试听：尚无满足 8–15 秒、真实无伴奏且明确可再分发的源音频，所以保持禁用。
11. 原词主链：GUI 同款 worker 已对《春日影》全曲完成 MSST→RVC→对齐→响度混音→WAV，43.4 秒完成；再次请求 0.55 秒命中缓存。DDSP 路线尚未验收。
12. 改词 Beta：界面和条件后端适配存在，但 Vevo2、GAME、DiffSinger 尚未下载权重或真实推理，不宣称可用。
13. 硬件：RTX 5070 Ti Laptop，12172 MiB；PyTorch 2.9.1+cu130 CUDA tensor、MSST、RVC 三项验证通过。
14. 测试：14 项 pytest 全部通过；Windows GUI、双击 `app.py`、冻结 EXE、FFmpeg、MSST 与 RVC 集成测试通过。
15. 发行：Modern/Legacy 当前打包 GUI、FFmpeg 与素材；AI 后端/权重体积大且分发条款各异，未塞入源码 Git 或阶段 EXE 目录。
16. 当前风险：DDSP、祥子双模型、合法标准干声和改词扩展仍未解决；第三方兼容补丁必须在后端安装流程中可复现。
17. 下一步：完成 DDSP 6.x 合法测试模型与安装脚本，然后把已验证的 MSST/RVC 安装流程接入组件管理页，最后再评估改词扩展。
