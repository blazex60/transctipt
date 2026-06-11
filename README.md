# Discord Craig Bot 文字起こしツール

Craig Bot が保存した Discord ミーティングの別トラック録音（.flac/.opus）を
Whisper large-v3（ローカル・無料）で文字起こしし、話者ラベル付き SRT を生成します。

## 必要環境

- [uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
- ffmpeg（`apt install ffmpeg` / `brew install ffmpeg` / `choco install ffmpeg`）
- GPU: オプション（NVIDIA CUDA 12.x は標準インストールで対応、AMD ROCm は別途セットアップ必要）

## インストール

追加作業不要。`uv run` が初回実行時に仮想環境と依存パッケージを自動でセットアップします。

## 初回実行時の注意

- 初回のみ faster-whisper / onnxruntime が自動インストールされます
- Whisper large-v3 モデル（約 3GB）も初回のみダウンロードされます
- 処理時間の目安（CPU int8、large-v3）: 1 分の音声あたり約 2〜5 分
  - 高速化: `--model medium` で約 2〜4× 速く（精度は若干低下）

## 使い方

```bash
uv run transcribe.py meeting_folder/                              # 通常実行（CPU int8）
uv run transcribe.py meeting_folder/ --force                      # 既存 SRT を確認なしで上書き
uv run transcribe.py meeting_folder/ --model medium               # 高速モード
uv run transcribe.py meeting_folder/ --device cuda                # NVIDIA GPU（float16 自動選択）
uv run transcribe.py meeting_folder/ --device cuda --compute-type int8_float16  # VRAM 節約
uv run transcribe.py meeting_folder/ --device cpu --compute-type int8           # CPU 強制
```

## GPU を使う場合

### NVIDIA GeForce / Quadro (CUDA)

CUDA Toolkit がインストール済みであれば、`faster-whisper` に同梱の `ctranslate2` が自動的に GPU を使用します。追加の pip インストールは不要です。

```bash
uv run transcribe.py meeting_folder/ --device cuda
```

VRAM が少ない場合は `--compute-type int8_float16` で削減できます。

### AMD Radeon (ROCm)

**Step 1 — ROCm ユーザー空間ライブラリのインストール**（カーネルドライバだけでは不足）

```bash
# Arch / EndeavourOS
yay -S rocm-hip-sdk   # または rocm-hip-runtime hiprand
```

インストール後、`libhiprand.so.1` が `/opt/rocm/lib` に存在することを確認。

**Step 2 — ROCm 対応 ctranslate2 wheel の入手**

PyPI の標準 `ctranslate2` は ROCm 非対応のため、[OpenNMT/CTranslate2 Releases](https://github.com/OpenNMT/CTranslate2) から ROCm ビルドの wheel を入手。

**Step 3 — 実行**（`LD_LIBRARY_PATH` で ROCm ライブラリを明示）

```bash
LD_LIBRARY_PATH=/opt/rocm/lib:$LD_LIBRARY_PATH \
  uv run --with ./ctranslate2-X.Y.Z-cpXX-cpXX-linux_x86_64.whl \
  transcribe.py meeting_folder/ --device cuda
```

## 入力ファイル形式

Craig Bot がエクスポートしたミーティングフォルダを想定:

```
meeting_2026-06-11/
  alice.flac
  bob.opus
  charlie.flac
```

## 出力例

`meeting_2026-06-11/transcript.srt`:

```
1
00:00:01,000 --> 00:00:05,230
[alice] こんにちは、今日はよろしくお願いします。

2
00:00:06,100 --> 00:00:09,800
[bob] こちらこそ、よろしくお願いします。
```

## Craig Bot のファイル形式について

Craig Bot はセッション開始時刻（T=0）から全トラックを録音します。
参加が遅かったユーザーの先頭は無音パッドになり、途中退出したユーザーは
トラックが短くなります。タイムスタンプはファイル先頭基準で正確に揃っています。

ファイル名は `N-username.flac` 形式（例: `1-alice.flac`）で、話者ラベルは
`username` 部分（番号プレフィックスを除いた部分）が使われます。

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 正常完了 |
| 1 | 入力エラー（ファイルなし・パス不正・中断） |
| 130 | Ctrl+C による中断 |
