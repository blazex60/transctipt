# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "faster-whisper>=1.0.0",
#     "onnxruntime>=1.16.0",
# ]
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from faster_whisper import WhisperModel


# --- カスタム例外 ---

class NoAudioFilesError(ValueError):
    """指定フォルダに .flac/.opus が見つからない"""


class UserAbortError(RuntimeError):
    """ユーザーが処理を中断した"""


AUDIO_EXTENSIONS = (".flac", ".opus")


# --- ファイル検出 ---

def find_audio_files(folder: Path) -> list[Path]:
    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not files:
        raise NoAudioFilesError(f"{folder} に .flac/.opus ファイルが見つかりません")
    return files


# --- Whisper モデルロード ---

def load_model(model_name: str, device: str = "auto", compute_type: str = "auto") -> WhisperModel:
    return WhisperModel(model_name, device=device, compute_type=compute_type)


# --- 転写 ---

def transcribe_file(
    model: WhisperModel,
    audio_path: Path,
    speaker: str,
) -> list[dict]:
    segments, _ = model.transcribe(
        str(audio_path),
        language="ja",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    return [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "speaker": speaker,
        }
        for seg in segments
        if seg.text.strip()
    ]


# --- SRT 変換 ---

def seconds_to_srt_time(total_seconds: float) -> str:
    """浮動小数秒を SRT タイムコード HH:MM:SS,mmm に変換（divmod ベース）"""
    total_ms = round(total_seconds * 1000)
    ms = total_ms % 1000
    total_s, _ = divmod(total_ms, 1000)
    h, remainder = divmod(total_s, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = seconds_to_srt_time(seg["start"])
        end = seconds_to_srt_time(seg["end"])
        text = f"[{seg['speaker']}] {seg['text']}"
        lines.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(lines) + "\n"


# --- メイン処理 ---

def run(folder: Path, force: bool, model_name: str, device: str, compute_type: str) -> None:
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} はディレクトリではありません")

    audio_files = find_audio_files(folder)
    output_path = folder / "transcript.srt"

    if output_path.exists() and not force:
        answer = input(f"{output_path} が既に存在します。上書きしますか？ [y/N]: ")
        if answer.lower() != "y":
            raise UserAbortError("中止しました。--force オプションで強制上書きできます。")

    device_label = device if device != "auto" else "auto (GPU 優先)"
    print(f"モデルを読み込み中: {model_name} (device={device_label}, compute={compute_type})...")
    print("※ 初回実行時は ~3GB のモデルダウンロードが発生します")
    model = load_model(model_name, device=device, compute_type=compute_type)

    all_segments: list[dict] = []
    for idx, audio_file in enumerate(audio_files, start=1):
        stem = audio_file.stem
        speaker = stem.split("-", 1)[1] if "-" in stem else stem
        print(f"[{idx}/{len(audio_files)}] {audio_file.name} を処理中 (話者: {speaker})...")
        segs = transcribe_file(model, audio_file, speaker)
        all_segments.extend(segs)
        print(f"  → {len(segs)} セグメント取得")

    # 時系列ソート（同 start の場合は話者名アルファベット順）
    all_segments.sort(key=lambda s: (s["start"], s["speaker"]))

    srt_content = segments_to_srt(all_segments)
    output_path.write_text(srt_content, encoding="utf-8")
    print(f"\n完了: {output_path} に {len(all_segments)} エントリを書き出しました。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Craig Bot 録音を Whisper large-v3 で文字起こし → SRT 出力"
    )
    parser.add_argument("folder", type=Path, help="ミーティングフォルダのパス")
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="既存の transcript.srt を確認なしで上書き",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="Whisper モデル名（デフォルト: large-v3）",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="使用デバイス (auto: GPU 優先、なければ CPU / cuda: CUDA/ROCm GPU / cpu: CPU強制)",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        dest="compute_type",
        choices=["auto", "int8", "float16", "float32", "int8_float16"],
        help="計算精度 (auto: GPU→float16, CPU→int8)",
    )
    args = parser.parse_args()

    try:
        run(args.folder, args.force, args.model, args.device, args.compute_type)
        return 0
    except NoAudioFilesError as e:
        print(f"警告: {e}", file=sys.stderr)
        return 1
    except NotADirectoryError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except UserAbortError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
