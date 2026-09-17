import re
import subprocess
import tempfile
from pathlib import Path

from crawler.config import load_transcribe_settings

TAG_RE = re.compile(r"<\|[^|]*\|>")
TEXT_PREFIX = "Text:"
TIMEOUT_SECONDS = 900
DETAIL_CHARS = 500


class TranscribeError(RuntimeError):
    pass


def strip_tags(text) -> str:
    cleaned = TAG_RE.sub("", text or "")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


def _decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return str(data)


def _default_runner(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _run(runner, cmd, timeout, action) -> str:
    try:
        result = runner(cmd, timeout)
    except subprocess.TimeoutExpired as exc:
        raise TranscribeError(f"{action}超时（{timeout} 秒）：{' '.join(cmd)}") from exc
    except FileNotFoundError as exc:
        raise TranscribeError(f"{action}失败：找不到命令 {cmd[0]}，请确认已安装并在 PATH 中") from exc
    if result.returncode != 0:
        detail = _decode(result.stderr).strip() or _decode(result.stdout).strip()
        raise TranscribeError(f"{action}失败（退出码 {result.returncode}）：{detail[-DETAIL_CHARS:]}")
    return _decode(result.stdout)


def _parse_text(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(TEXT_PREFIX):
            return stripped[len(TEXT_PREFIX):].strip()
    raise TranscribeError("转录失败：FunASR 输出中没有找到 Text: 结果行")


def transcribe_media(path, settings=None, runner=None, timeout=TIMEOUT_SECONDS) -> str:
    media = Path(path)
    if not media.exists():
        raise TranscribeError(f"转录失败：文件不存在 {media}")
    cfg = load_transcribe_settings()
    if settings:
        cfg.update({k: v for k, v in settings.items() if v not in (None, "")})
    runner = runner or _default_runner
    with tempfile.TemporaryDirectory(prefix="kuang_news_asr_") as tmp:
        wav = Path(tmp) / "audio.wav"
        _run(runner, ["ffmpeg", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
             timeout, "音频提取")
        if not wav.exists():
            raise TranscribeError("音频提取失败：ffmpeg 没有生成临时 wav 文件")
        output = _run(runner, [cfg["venv_python"], cfg["script"], str(wav), "--language", cfg["language"]],
                      timeout, "语音转录")
    return strip_tags(_parse_text(output))
