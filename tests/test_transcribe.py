from pathlib import Path
from types import SimpleNamespace

import pytest

from crawler import config
from crawler.transcribe import TranscribeError, strip_tags, transcribe_media

TEXT_OUTPUT = ("Loading model...\n"
               "Text: <|zh|><|NEUTRAL|><|Speech|><|woitn|>欢迎大家来体验达摩院推出的语音识别模型\n"
               "-------\n").encode("utf-8")


class FakeRunner:
    def __init__(self, output=TEXT_OUTPUT, fail=None, make_wav=True):
        self.calls = []
        self.output = output
        self.fail = fail or {}
        self.make_wav = make_wav

    def __call__(self, cmd, timeout):
        self.calls.append((list(cmd), timeout))
        if self.make_wav and cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"RIFF")
        if cmd[0] in self.fail:
            return SimpleNamespace(returncode=1, stdout=b"",
                                   stderr=self.fail[cmd[0]].encode("utf-8"))
        return SimpleNamespace(returncode=0, stdout=self.output, stderr=b"")


SETTINGS = {"venv_python": r"C:\funasr\python.exe",
            "script": r"C:\funasr\transcribe.py", "language": "zh"}


def test_strip_tags_removes_leading_tags():
    raw = "<|zh|><|NEUTRAL|><|Speech|><|woitn|>欢迎大家来体验达摩院推出的语音识别模型"
    assert strip_tags(raw) == "欢迎大家来体验达摩院推出的语音识别模型"


def test_strip_tags_removes_middle_tags():
    assert strip_tags("<|zh|>你好<|en|>世界") == "你好世界"
    assert strip_tags("<|zh|>你好 <|en|>世界") == "你好 世界"


def test_strip_tags_normalizes_whitespace():
    assert strip_tags("  第一行文字   \n\n  第二行\t文字  \n") == "第一行文字\n第二行 文字"
    assert strip_tags("多个   空格") == "多个 空格"


def test_strip_tags_empty():
    assert strip_tags("") == ""
    assert strip_tags(None) == ""
    assert strip_tags("<|zh|><|woitn|>") == ""


def test_transcribe_media_commands(tmp_path):
    src = tmp_path / "视频素材.mp4"
    src.write_bytes(b"fake-video")
    runner = FakeRunner()
    text = transcribe_media(src, settings=SETTINGS, runner=runner)
    assert text == "欢迎大家来体验达摩院推出的语音识别模型"
    assert len(runner.calls) == 2
    ffmpeg_cmd, ffmpeg_timeout = runner.calls[0]
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert ffmpeg_cmd[1:4] == ["-y", "-i", str(src)]
    assert ffmpeg_cmd[4:9] == ["-vn", "-ac", "1", "-ar", "16000"]
    wav_path = ffmpeg_cmd[9]
    assert wav_path.endswith(".wav")
    assert ffmpeg_timeout == 900
    asr_cmd, asr_timeout = runner.calls[1]
    assert asr_cmd == [SETTINGS["venv_python"], SETTINGS["script"], wav_path, "--language", "zh"]
    assert asr_timeout == 900


def test_transcribe_media_language_override(tmp_path):
    src = tmp_path / "a.wav"
    src.write_bytes(b"RIFF")
    runner = FakeRunner()
    transcribe_media(src, settings={**SETTINGS, "language": "en"}, runner=runner)
    assert runner.calls[1][0][3:] == ["--language", "en"]


def test_transcribe_media_accepts_settings_from_config(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    runner = FakeRunner()
    transcribe_media(src, runner=runner)
    defaults = config.load_transcribe_settings()
    assert runner.calls[1][0][0] == defaults["venv_python"]
    assert runner.calls[1][0][1] == defaults["script"]
    assert runner.calls[1][0][3:] == ["--language", defaults["language"]]


def test_transcribe_media_ffmpeg_failure_is_chinese(tmp_path):
    src = tmp_path / "bad.mp4"
    src.write_bytes(b"x")
    runner = FakeRunner(fail={"ffmpeg": "Invalid data found when processing input"})
    with pytest.raises(TranscribeError) as excinfo:
        transcribe_media(src, settings=SETTINGS, runner=runner)
    message = str(excinfo.value)
    assert "音频提取失败" in message
    assert "Invalid data found" in message


def test_transcribe_media_asr_failure_contains_stderr(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    runner = FakeRunner(fail={"C:\\funasr\\python.exe": "ModuleNotFoundError: funasr"})
    with pytest.raises(TranscribeError) as excinfo:
        transcribe_media(src, settings=SETTINGS, runner=runner)
    assert "语音转录失败" in str(excinfo.value)
    assert "ModuleNotFoundError" in str(excinfo.value)


def test_transcribe_media_missing_text_line(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    runner = FakeRunner(output=b"Loading model...\nNo result returned.\n")
    with pytest.raises(TranscribeError) as excinfo:
        transcribe_media(src, settings=SETTINGS, runner=runner)
    assert "Text" in str(excinfo.value)


def test_transcribe_media_missing_file(tmp_path):
    with pytest.raises(TranscribeError) as excinfo:
        transcribe_media(tmp_path / "不存在.mp4", settings=SETTINGS, runner=FakeRunner())
    assert "文件不存在" in str(excinfo.value)


def test_load_transcribe_settings_overrides(tmp_path):
    p = tmp_path / "settings.yaml"
    script = r"D:\x\t.py"
    p.write_text("transcribe:\n  language: en\n  script: " + script + "\n", encoding="utf-8")
    cfg = config.load_transcribe_settings(p)
    assert cfg["language"] == "en"
    assert cfg["script"] == script
    assert cfg["venv_python"].endswith("python.exe")


def test_load_section_missing_file_uses_defaults(tmp_path):
    assert config.load_transcribe_settings(tmp_path / "无.yaml")["language"] == "zh"
    assert config.load_marketing_settings(tmp_path / "无.yaml")["author"] == "计算机选矿"


def test_load_marketing_settings_reads_author(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("marketing:\n  author: 测试作者\n", encoding="utf-8")
    assert config.load_marketing_settings(p)["author"] == "测试作者"
