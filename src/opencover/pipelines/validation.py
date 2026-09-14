"""Shared user option checks for both cover workflows."""


def cover_option_issues(pitch: int, balance: str, output_format: str, memory_profile: str) -> list[str]:
    issues = []
    if output_format.lower() not in {"wav", "flac", "mp3"}:
        issues.append("输出格式必须是 WAV、FLAC 或 MP3")
    if not isinstance(pitch, int) or isinstance(pitch, bool) or not -12 <= pitch <= 12:
        issues.append("升降调必须在 -12 到 12 半音之间")
    if balance not in {"均衡", "人声更突出", "伴奏更突出"}:
        issues.append("混音选项无效")
    if memory_profile not in {"极低", "低", "标准", "高质量"}:
        issues.append("显存配置无效")
    return issues
