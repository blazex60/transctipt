# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 環境
- uv

## 実行方法

```bash
# 文字起こし実行（uv が依存関係を自動セットアップ）
uv run transcribe.py <meeting_folder>/

# オプション
uv run transcribe.py record/ --force              # 既存 SRT を確認なしで上書き
uv run transcribe.py record/ --model medium       # 高速モード（精度低下）
uv run transcribe.py record/ --device cuda        # GPU 使用
uv run transcribe.py record/ --compute-type float16
```

## アーキテクチャ

エントリポイントは `transcribe.py` 1ファイルのみ。PEP 723 インラインメタデータで依存関係を自己完結している。

### 処理フロー

```
find_audio_files()        # .flac/.opus をアルファベット順に列挙
  ↓
load_model()              # WhisperModel(device, compute_type)
  ↓
transcribe_file() × N     # 各トラックを Whisper で転写
  ↓                       # VAD フィルタで無音セグメント（別ユーザー発話中の無音）を除去
segments_to_srt()         # 全セグメントを start 昇順でソートし SRT 化
  ↓
folder/transcript.srt     # 出力
```

### Craig Bot ファイル形式の前提

- ファイル名: `N-username.flac`（例: `1-alice.flac`）→ 話者名は `N-` プレフィックスを除いた部分
- 全トラックは **セッション開始（T=0）から無音パッドで録音**される。参加が遅いユーザーは先頭が無音、途中退出は末尾がない。**Whisper のタイムスタンプは調整不要**（ファイル先頭 = セッション T=0）
- `info.txt` にセッション開始時刻・参加者リスト・ノートが含まれるが、現在は使用していない

### デバイス選択

`--device auto`（デフォルト）で CTranslate2 が CUDA を自動検出。NVIDIA は標準インストールで動作、AMD ROCm は ROCm 対応 ctranslate2 ビルドが必要。

## 依存関係

`pyproject.toml` は空（プロジェクト管理用）。実際の依存関係は `transcribe.py` 冒頭の PEP 723 `# /// script` ブロックに記述されており、`uv run` が自動インストールする。手動で追加する場合もこのブロックを編集する。

システム要件: `ffmpeg`（.opus デコード用）
