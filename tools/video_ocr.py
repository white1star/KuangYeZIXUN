import argparse
import difflib
import os
import shutil
import subprocess
import tempfile

from rapidocr_onnxruntime import RapidOCR


def extract_frames(video, fps=2.0):
    out_dir = tempfile.mkdtemp(prefix="video_ocr_")
    pattern = os.path.join(out_dir, "frame_%04d.png")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", f"fps={fps}", pattern],
        check=True,
    )
    frames = sorted(os.listdir(out_dir))
    return out_dir, [os.path.join(out_dir, f) for f in frames]


def is_similar(a, b, threshold=0.85):
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def ocr_video(video, fps=2.0, min_len=2):
    engine = RapidOCR()
    out_dir, frames = extract_frames(video, fps)
    lines = []
    try:
        for path in frames:
            result, _ = engine(path)
            if not result:
                continue
            for item in result:
                text = str(item[1]).strip()
                if len(text) < min_len:
                    continue
                if not any(is_similar(text, old) for old in lines):
                    lines.append(text)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return lines


def main():
    parser = argparse.ArgumentParser(description="提取视频画面中的文字（OCR）")
    parser.add_argument("video")
    parser.add_argument("--fps", type=float, default=2.0)
    args = parser.parse_args()
    lines = ocr_video(args.video, args.fps)
    print("画面文字（按出现顺序，已去重）:")
    for line in lines:
        print(" -", line)
    print("\n合并文案:")
    print(" ".join(lines))


if __name__ == "__main__":
    main()
