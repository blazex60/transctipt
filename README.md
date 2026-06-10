# Discord Craig Bot 文字起こしツール

Craig Bot が保存した Discord ミーティングの別トラック録音（.flac/.opus）を
Whisper large-v3（ローカル・無料）で文字起こしし、話者ラベル付き SRT を生成します。

## 必要環境

- [uv](https://docs.astral.sh/uv/)（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
- ffmpeg（`apt install ffmpeg` / `brew install ffmpeg` / `choco install ffmpeg`）
- GPU: 不要（CPU int8 で動作）

## インストール

追加作業不要。`uv run` が初回実行時に仮想環境と依存パッケージを自動でセットアップします。

## 初回実行時の注意

- 初回のみ faster-whisper / onnxruntime が自動インストールされます
- Whisper large-v3 モデル（約 3GB）も初回のみダウンロードされます
- 処理時間の目安（CPU int8、large-v3）: 1 分の音声あたり約 2〜5 分
  - 高速化: `--model medium` で約 2〜4× 速く（精度は若干低下）

## 使い方

```bash
uv run transcribe.py meeting_folder/           # 通常実行
uv run transcribe.py meeting_folder/ --force   # 既存 SRT を確認なしで上書き
uv run transcribe.py meeting_folder/ --model medium  # 高速モード
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

## Step 0: 初回実行前の検証（重要）

Craig Bot のトラックがセッション開始基準で時刻揃えされているか確認:

```bash
for f in meeting_folder/*.flac meeting_folder/*.opus; do
  [ -f "$f" ] || continue
  echo "$f: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f") 秒"
done
# 全ファイルの duration が ±5 秒以内であることを確認
```

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 正常完了 |
| 1 | 入力エラー（ファイルなし・パス不正・中断） |
| 2 | タイムスタンプ不整合（トラック間 duration 差 > 5s） |
| 130 | Ctrl+C による中断 |
