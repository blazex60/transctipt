# 実装計画: Discord Craig Bot 文字起こし CLI ツール

**Status:** pending approval
**Generated:** 2026-06-11
**Revision:** 3（Architect + Critic Iteration 2 minor 改善反映）
**Source Spec:** `.omc/specs/deep-interview-discord-transcription.md`
**Session:** ralplan-discord-transcription-001

---

## RALPLAN-DR サマリー

### Principles
1. ローカル完結 — 外部 API へのデータ送信なし
2. 最小依存 — faster-whisper + ffmpeg/ffprobe のみ（onnxruntime は VAD 必須のため追加）
3. 1 コマンド完結 — `python transcribe.py <folder>` で全処理
4. 品質優先 — Whisper large-v3 + VAD フィルタで最高精度の日本語認識
5. 冪等性 — 同じ入力フォルダから同じ出力を生成（beam_size 固定、seed は Whisper 側の制限で完全保証は困難だが実用上安定）

### Decision Drivers
1. 無料・プライバシー安全（ローカル実行、API キー不要）
2. 日本語精度（Whisper large-v3 + vad_filter）
3. シンプルな実行体験（1 コマンド完結）

### Options: STT バックエンド
| | Option A: openai-whisper | Option B: faster-whisper（採用） |
|---|---|---|
| 速度 | 基準 | 2〜4× 高速 |
| CPU 最適化 | 限定的 | int8 量子化で CPU に最適 |
| VAD 対応 | なし | built-in（onnxruntime） |
| GPU/CPU | GPU 前提 | CPU int8 で実用速度 |

**採用: faster-whisper** — CPU int8 で大きな速度アドバンテージ、VAD 組み込み。openai-whisper は却下（CPU 遅すぎ、VAD なし）。Whisper API / Google STT は却下（有料・外部送信）。

### Craig タイムスタンプ前提（最重要）
Craig Bot のマルチトラックエクスポートは「全トラックがセッション開始から同一時間長で先頭無音パディング済み」として実装。この前提は Step 0 で `ffprobe` により実測検証し、全トラックの duration が ±5 秒以内であることを assert する。前提が崩れた場合はエラーを出して処理を中断し、ユーザーに手動確認を促す。

---

## Requirements Summary

Craig Bot が保存した Discord ミーティングの各ユーザー別音声ファイル（.flac/.opus）を格納したフォルダを受け取り、各トラックを Whisper large-v3（ローカル・無料・VAD フィルタ付き）で日本語音声認識し、全話者の発言を時系列に統合した 1 つの SRT ファイルを同フォルダに出力する Python CLI ツール。

---

## Acceptance Criteria

### 機能基準（手続き面）
- [ ] `python transcribe.py meeting_folder/` を実行すると処理が開始される
- [ ] フォルダ内の全 .flac および .opus ファイルを自動検出する
- [ ] 各ファイルを faster-whisper large-v3（`language="ja"`, `vad_filter=True`, `compute_type="int8"`）で転写する
- [ ] ファイル名（拡張子除く）を話者ラベルとして使用する（例: `alice.flac` → `[alice]`）
- [ ] 全話者のセグメントを `start` 時刻順にソートして統合する（同 start の場合は話者名アルファベット順）
- [ ] `meeting_folder/transcript.srt` として SRT 形式で出力する
- [ ] SRT 各エントリの字幕テキストは `[話者名] 発言内容` の形式になっている
- [ ] `--force` フラグで既存 `transcript.srt` を確認なしで上書きできる
- [ ] フォルダに音声ファイルが 0 件の場合: 警告メッセージを表示して終了コード 1 で終了する
- [ ] 処理進捗をファイルごとに標準出力に表示する（`[1/3] alice.flac を処理中...`）

### 品質・正確性基準
- [ ] Craig Bot エクスポートフォルダで、全トラックの duration 差が ±5 秒以内であること（ffprobe で検証）。差が ±5 秒を超える場合はエラーを表示して処理を中断する
- [ ] 2 話者が交互に話す 1 分間のサンプルで、SRT の話者順序が実際の発話順と一致する（時刻ずれ ±2 秒以内）
- [ ] 各話者トラックの無音区間（他者発話中）から生成される SRT エントリが 0 件（VAD によって除去されること）
- [ ] CPU 環境（GPU なし）で large-v3 が `compute_type="int8"` によりクラッシュせず完走する
- [ ] 処理時間の目安: 1 トラック 1 分あたり CPU int8 で約 2〜5 分（large-v3）。ユーザーは README で事前に認識済みとする

---

## Implementation Steps

### Step 0: 環境セットアップと入力形式検証

#### 0a: Python / pip 環境確認
```bash
# Python バージョン確認（3.9 以上が必要）
python3 --version

# pip がない場合
python3 -m ensurepip --upgrade
# または
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python3 get-pip.py

# 仮想環境の作成（推奨）
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 依存インストール（onnxruntime は VAD 必須）
pip install faster-whisper
# ffmpeg はシステムパッケージ: apt install ffmpeg / brew install ffmpeg
```

> **Python 3.14 互換性:** faster-whisper/ctranslate2 の wheel が 3.14 用に提供されているか `pip install` 実行時に確認すること。エラーが出た場合は Python 3.11 または 3.12 の venv を使用。

#### 0b: Craig タイムスタンプ基準の検証（実装前に必須）

Craig Bot のエクスポートは「全トラックがセッション開始から同一長さで先頭無音パディング済み」と仮定する。この前提が崩れると時系列統合が無意味になるため、**実装前に実際のサンプルファイルで確認すること**。

```bash
# 各トラックの duration を確認
for f in meeting_folder/*.flac meeting_folder/*.opus; do
  [ -f "$f" ] || continue
  echo "$f: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f") 秒"
done
```

期待結果: 全トラックの duration が ±5 秒以内。差が大きい場合はトリム済み形式の可能性があり、オフセット補正が必要（付録 A 参照）。

> **注意（Architect 指摘）:** duration が揃っていても「先頭無音パディング済み」の保証にはならない。Craig が「先頭トリム・末尾パディング」形式の場合、duration は揃うが先頭オフセットがずれ、時系列統合が崩壊する。下記の先頭無音確認も必ず実施すること。

```bash
# 先頭の無音状況を確認（最初のセグメントの start 時刻が全トラックで近いか）
# ffprobe で先頭 5 秒の音声データをチェック
for f in meeting_folder/*.flac meeting_folder/*.opus; do
  [ -f "$f" ] || continue
  echo "$f: 先頭5秒 RMS = $(ffmpeg -i "$f" -t 5 -af astats=metadata=1:reset=1 -f null - 2>&1 | grep RMS_level | head -1)"
done
# → 全トラックで先頭が無音（RMS_level が低い）ことを確認
# → 先頭から音声が始まるトラックがあれば先頭トリム形式の可能性（付録 A）
```

**この検証をスキップして実装を進めてはいけない。**

#### 0c: requirements.txt の作成
```
# requirements.txt
faster-whisper>=1.0.0
# onnxruntime は faster-whisper が vad_filter=True 使用時に必要（自動インストールされる場合あり）
onnxruntime>=1.16.0
```

---

### Step 1: `transcribe.py` のメインスクリプト実装
**ファイル:** `transcribe.py`（唯一の実装ファイル）

#### 1a: カスタム例外と型定義
```python
from __future__ import annotations
import argparse
import sys
from pathlib import Path


class NoAudioFilesError(ValueError):
    """指定フォルダに .flac/.opus が見つからない"""


class TrackDurationMismatchError(RuntimeError):
    """全トラックの duration がセッション開始基準で揃っていない"""


class UserAbortError(RuntimeError):
    """ユーザーが処理を中断した"""


AUDIO_EXTENSIONS = (".flac", ".opus")
```

#### 1b: 音声ファイル検出
```python
def find_audio_files(folder: Path) -> list[Path]:
    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not files:
        raise NoAudioFilesError(f"{folder} に .flac/.opus ファイルが見つかりません")
    return files
```

#### 1c: Craig タイムスタンプ基準の検証（`ffprobe`）
```python
import subprocess
import json


def get_duration(path: Path) -> float:
    """ffprobe でファイルの duration (秒) を取得"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def assert_tracks_aligned(files: list[Path], tolerance_sec: float = 5.0) -> None:
    """全トラックの duration が ±tolerance_sec 以内であることを確認"""
    durations = {f: get_duration(f) for f in files}
    min_d, max_d = min(durations.values()), max(durations.values())
    if max_d - min_d > tolerance_sec:
        details = "\n".join(f"  {f.name}: {d:.1f}s" for f, d in durations.items())
        raise TrackDurationMismatchError(
            f"トラック間の duration 差が {max_d - min_d:.1f}s です（許容: {tolerance_sec}s）。\n"
            f"Craig Bot のエクスポート形式が期待と異なる可能性があります。\n{details}\n"
            "付録 A のオフセット補正手順を参照してください。"
        )
```

#### 1d: Whisper 転写（VAD + CPU int8）
```python
from faster_whisper import WhisperModel


def load_model(model_name: str) -> WhisperModel:
    """CPU int8 モードでモデルをロード（GPU なし環境向け）"""
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
    )


def transcribe_file(
    model: WhisperModel, audio_path: Path, speaker: str
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
```

#### 1e: SRT フォーマット変換（`divmod` ベース）
```python
def seconds_to_srt_time(total_seconds: float) -> str:
    """浮動小数秒を SRT タイムコード HH:MM:SS,mmm に変換"""
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
        end   = seconds_to_srt_time(seg["end"])
        text  = f"[{seg['speaker']}] {seg['text']}"
        lines.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(lines) + "\n"
```

#### 1f: メイン処理フロー（例外ベース、sys.exit は main 最上位のみ）
```python
def run(folder: Path, force: bool, model_name: str) -> None:
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} はディレクトリではありません")

    audio_files = find_audio_files(folder)  # NoAudioFilesError を raise
    output_path = folder / "transcript.srt"

    # Craig タイムスタンプ基準を検証
    print(f"トラックの duration を検証中 ({len(audio_files)} ファイル)...")
    assert_tracks_aligned(audio_files)

    # 上書き確認
    if output_path.exists() and not force:
        answer = input(f"{output_path} が既に存在します。上書きしますか？ [y/N]: ")
        if answer.lower() != "y":
            raise UserAbortError("中止しました。--force オプションで強制上書きできます。")

    print(f"モデルを読み込み中: {model_name} (CPU int8)...")
    print("※ 初回実行時は ~3GB のモデルダウンロードが発生します")
    model = load_model(model_name)

    all_segments: list[dict] = []
    for idx, audio_file in enumerate(audio_files, start=1):
        speaker = audio_file.stem
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
    parser.add_argument("--force", "-f", action="store_true",
                        help="既存の transcript.srt を確認なしで上書き")
    parser.add_argument("--model", default="large-v3",
                        help="Whisper モデル名（デフォルト: large-v3）")
    args = parser.parse_args()

    try:
        run(args.folder, args.force, args.model)
        return 0
    except NoAudioFilesError as e:
        print(f"警告: {e}", file=sys.stderr)
        return 1
    except TrackDurationMismatchError as e:
        print(f"エラー（タイムスタンプ不整合）:\n{e}", file=sys.stderr)
        return 2
    except NotADirectoryError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except UserAbortError as e:
        print(str(e), file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, ValueError, KeyError) as e:
        print(f"エラー（ffprobe / メタデータ解析失敗）: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n中断されました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
```

---

### Step 2: README.md の作成（最小限・必要事項のみ）

```markdown
# Discord Craig Bot 文字起こしツール

## 必要環境
- Python 3.9〜3.12（3.14 は wheel 提供状況に依存）
- ffmpeg（`apt install ffmpeg` / `brew install ffmpeg` / `choco install ffmpeg`）
- GPU: 不要（CPU int8 で動作）

## インストール
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 初回実行時の注意
- Whisper large-v3 モデル（約 3GB）を初回のみダウンロードします
- 処理時間: CPU で 1 分の音声あたり約 2〜5 分（large-v3）
  - 高速化: `--model medium` で約 2〜4× 速く（精度は若干低下）

## 使い方
```bash
python transcribe.py meeting_folder/         # 通常実行
python transcribe.py meeting_folder/ --force  # 既存 SRT を上書き
python transcribe.py meeting_folder/ --model medium  # 高速モード
```

## 出力例
`meeting_folder/transcript.srt`:
```
1
00:00:01,000 --> 00:00:05,230
[alice] こんにちは、今日はよろしくお願いします。
```
```

---

### Step 3: 動作確認

#### 3a: 単体確認（手動）
```bash
# フォルダなし・ファイルなしエラー確認（終了コード 1）
python transcribe.py /nonexistent && echo "ERROR: should fail"
mkdir /tmp/empty && python transcribe.py /tmp/empty; echo "Exit: $?"

# 通常実行
python transcribe.py meeting_folder/

# --force 確認
python transcribe.py meeting_folder/ --force

# --model medium（速度確認）
python transcribe.py meeting_folder/ --model medium
```

#### 3b: SRT 品質検証
```bash
# エントリ数確認
grep -c "^[0-9]" meeting_folder/transcript.srt

# 話者ラベル確認（全エントリに [話者名] が付いているか）
grep -v "^\[" meeting_folder/transcript.srt | grep -v "^[0-9]" | grep -v "^$" | grep -v " --> "

# タイムコード形式確認
head -6 meeting_folder/transcript.srt

# 幻聴フィルタ確認（空のはずの時間帯にセグメントがないか）
# → 各話者が話していない時間帯のエントリが少ないことを目視確認
```

#### 3c: Craig タイムスタンプ基準の事前確認
```bash
for f in meeting_folder/*.flac meeting_folder/*.opus; do
  [ -f "$f" ] || continue
  echo "$f: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f") 秒"
done
# → 全ファイルの duration が ±5 秒以内であることを確認
```

---

## Risks and Mitigations

| Risk | 影響 | 確率 | 緩和策 |
|------|------|------|--------|
| Craig トラックがトリム済み（先頭無音なし） | 致命的（時系列崩壊） | 中 | Step 0b・Step 3c で duration assert。崩れた場合は付録 A のオフセット補正を適用 |
| CPU 処理速度（large-v3 が遅い） | 中（実用性低下） | 高 | `--model medium` で約 2〜4× 高速化（精度は若干低下）。README に処理時間目安を明記 |
| ffmpeg 未インストール（.opus デコード失敗） | 大 | 中 | README にインストール手順を明記。エラーメッセージに `ffmpeg が必要です` を含める |
| Whisper large-v3 モデルのダウンロード（~3GB） | 中 | 高（初回） | `~/.cache/huggingface/` にキャッシュ。README に明記 |
| Python 3.14 / ctranslate2 互換性 | 大（起動不能） | 中 | Step 0a で 3.11/3.12 venv にフォールバックする手順を README に明記 |
| `compute_type="int8"` で精度低下 | 小 | 小 | large-v3 int8 の精度劣化は実用上無視できる（fp32 比 -0.1〜0.3% WER 程度） |
| VAD が発話をカットしすぎる | 中 | 小 | `min_silence_duration_ms=500` で調整。フォールバック: `vad_filter=False` オプション追加 |
| OOM（CPU float32 時） | 大 | 小 | `compute_type="int8"` によりメモリ使用量を抑制（int8: ~1.5GB, fp32: ~4GB） |

---

## Verification Steps

1. `python transcribe.py --help` がヘルプを表示する
2. `.flac` と `.opus` 混在フォルダで両形式を検出する
3. `transcript.srt` が `meeting_folder/` に生成される
4. SRT 各エントリが `[話者名] テキスト` 形式になっている
5. タイムコードが `HH:MM:SS,mmm --> HH:MM:SS,mmm` 形式になっている
6. 空フォルダで終了コード 1 で終了する
7. duration 不整合フォルダ（ファイルを手動トリムして作成）で終了コード 2 で終了する
8. `--force` なし・既存ファイルあり時に確認プロンプトが出る
9. `--force` あり時に確認なく上書きされる
10. **品質ゲート:** 2 話者の既知サンプルで話者順序が正しい（時刻 ±2 秒以内）
11. **品質ゲート:** 無音トラックから生成されたセグメントが 0 件（VAD 確認）
12. **品質ゲート:** CPU 環境で large-v3 int8 がクラッシュせず完走する

---

## ADR: STT バックエンド選択

**Decision:** faster-whisper（`compute_type="int8"`, `vad_filter=True`）を採用

**Drivers:**
1. 無料ローカル実行（プライバシー安全）
2. 日本語 large-v3 最高精度
3. CPU int8 で実用速度

**Alternatives Considered:**
- openai-whisper: 公式、CPU 遅すぎ（2〜4× 劣速）、VAD なし → 却下
- OpenAI Whisper API: 有料、外部送信 → 要件に反する、却下
- Google STT: 有料、外部送信 → 要件に反する、却下

**Why Chosen:**
faster-whisper の CPU int8 モードは openai-whisper の 2〜4× 高速、メモリ使用量も int8 で約 1.5GB（fp32 比 1/3）。VAD 内蔵（onnxruntime）で無音区間からのハルシネーションを抑制できる。大会議録音（多トラック・多無音）での品質確保に必須。

**Consequences:**
- onnxruntime が VAD のために追加依存（faster-whisper に同梱される場合あり）
- 初回実行時 ~3GB ダウンロード
- Python 3.14 での ctranslate2 互換性は事前確認が必要

**Follow-ups:**
- Craig タイムスタンプ前提の実データ検証（付録 A でオフセット補正パターンも文書化）
- `--model medium/small` のベンチマーク（速度/精度トレードオフ）
- macOS / Windows での動作確認

---

## ファイル構成（完成形）

```
<project_root>/
├── transcribe.py        # メインスクリプト（唯一の実装ファイル）
├── requirements.txt     # faster-whisper, onnxruntime
└── README.md            # インストール・使い方・処理時間目安
```

---

## 付録 A: Craig トラックがトリム済みだった場合のオフセット補正（将来対応）

Craig Bot のバージョン・設定によっては、各ユーザートラックが「その話者の初回発話から始まる」形式で保存される場合がある。その場合、各 `.flac`/`.opus` のファイル名や付属 JSON にオフセット情報が含まれることがある。

**確認方法:**
```bash
# duration が大きくばらつく場合（Step 0b で検出される）
# → Craig の設定でセッション開始基準に切り替えるか、
#    ファイル名や Craig の JSON ログからオフセット秒数を取得して
#    transcribe_file の返す start/end に加算する補正ロジックを追加する
```

この補正は今回の仕様スコープ外だが、Step 0b の assert でトリガーされた場合に本付録を参照して対応すること。

---

## 改訂ログ

### v3（Architect + Critic Iteration 2 — minor 改善）
- `segments_to_srt` を `\n\n` 終端に統一（SRT パーサ互換性修正）
- `find_audio_files` に `f.is_file()` チェック追加（サブディレクトリ混入防止）
- `UserAbortError` を追加し `run()` 内の `raise SystemExit` を置換（例外一貫性）
- `main()` に `CalledProcessError`/`ValueError`/`KeyError` の except 節追加（ffprobe 失敗の明示的ハンドリング）
- Step 0b に先頭無音確認手順を追記（duration 一致 ≠ 先頭整合の注記）
- AC line 63 の「または」を除去し品質ゲートを締める

### v2（Architect + Critic フィードバック反映）
- `compute_type="auto"` → `"int8"` に明示（GPU なし環境、OOM リスク低減）
- `vad_filter=True` + `vad_parameters` を追加（無音ハルシネーション対策）
- Step 0 として環境セットアップ + Craig タイムスタンプ検証 (`ffprobe` + assert) を追加
- 関数内 `sys.exit()` を廃止し例外ベースに変更（`NoAudioFilesError`, `TrackDurationMismatchError`）
- 終了コード体系を定義（0: 成功, 1: 警告終了, 2: タイムスタンプ不整合, 130: Ctrl+C）
- `seconds_to_srt_time` を `divmod` ベースに変更（丸め安全性）
- `requirements.txt` に `onnxruntime>=1.16.0` を追加
- AC に品質ゲート 3 件を追加（話者順序 ±2s・幻聴 0 件・CPU 完走）
- リスク表に Craig トリム済み・Python 3.14 互換性・OOM 行を追加（定量表現付き）
- 同 start 時刻のタイブレーク規則を追加（話者名アルファベット順）
- README に処理時間目安を定量化（1 分 ≈ 2〜5 分、CPU int8 large-v3）
