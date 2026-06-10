# Deep Interview Spec: Discord ミーティング文字起こし（Craig Bot トラック統合）

## Metadata
- Interview ID: di-discord-transcription-001
- Rounds: 8
- Final Ambiguity Score: 10.6%
- Type: greenfield
- Generated: 2026-06-11
- Threshold: 0.2
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.90 | 0.40 | 0.36 |
| Constraint Clarity | 0.88 | 0.30 | 0.264 |
| Success Criteria | 0.90 | 0.30 | 0.27 |
| **Total Clarity** | | | **0.894** |
| **Ambiguity** | | | **10.6%** |

## Topology

| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| 音声ファイル入力 | active | ミーティングフォルダ内の .flac/.opus ファイルを取り込む | ✓ Craig Bot 形式、ディレクトリ引数として指定 |
| 音声→テキスト変換（STT） | active | 各トラックを Whisper large-v3 で文字起こし | ✓ ローカル Whisper、日本語、無料 |
| 話者マージ・タイムライン統合 | active | 複数トラックの結果を時系列でマージ | ✓ ファイル名を話者名として使用 |
| 結果出力 | active | SRT ファイルとして保存 | ✓ 統合 SRT、話者ラベル付き、同フォルダに保存 |

## Goal

Craig Bot が保存した Discord ミーティングの各ユーザー別音声ファイル（.flac/.opus）を格納したフォルダを受け取り、Python CLI ツールが各トラックを Whisper large-v3（ローカル・無料）で日本語音声認識し、全話者の発言を時系列に統合した 1 つの SRT ファイルを同フォルダに出力する。

## Constraints

- 入力: Craig Bot が生成した .flac または .opus ファイル、ミーティングごとのフォルダに格納済み
- STT エンジン: OpenAI Whisper large-v3（ローカル実行、無料）
- 言語: 日本語のみ
- 実行方法: Python スクリプト（CLI）— `python transcribe.py <meeting_folder>`
- 出力形式: SRT（.srt）— 統合 1 ファイル、話者ラベル付き
- 出力先: 入力フォルダと同じ場所（`<meeting_folder>/transcript.srt`）
- インターネット不要（ローカル完結）
- 外部 API へのデータ送信なし

## Non-Goals

- リアルタイム文字起こし（Discord 常駐ボット）
- 話者別の個別 SRT ファイル出力
- 英語その他の言語対応（今回は日本語のみ）
- GUI インターフェース
- 翻訳・要約機能
- VTT 形式出力（SRT のみ）

## Acceptance Criteria

- [ ] `python transcribe.py meeting_folder/` を実行すると処理が開始される
- [ ] フォルダ内の全 .flac および .opus ファイルを自動検出する
- [ ] 各ファイルを Whisper large-v3 で日本語音声認識し、タイムスタンプ付きセグメントを取得する
- [ ] ファイル名（拡張子除く）を話者ラベルとして使用する（例: `alice.flac` → `[alice]`）
- [ ] 全話者のセグメントを開始時刻順にソートして統合する
- [ ] `meeting_folder/transcript.srt` として SRT 形式で出力する
- [ ] SRT 各エントリの字幕テキストは `[話者名] 発言内容` の形式になっている
- [ ] 同時発話があっても SRT エントリが重複・欠落しない
- [ ] 既存の `transcript.srt` がある場合は上書きするか確認するか、またはタイムスタンプ付きで別名保存する

## Assumptions Exposed & Resolved

| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| ファイルはすでに存在する | リアルタイム録音の可能性を確認 | バッチ処理（既存ファイル）と確定 |
| 高品質 STT が必要 | 有料 API vs ローカルの確認 | 無料・高品質 → ローカル Whisper large-v3 |
| 日本語音声 | 言語を明示確認 | 日本語のみと確定 |
| Craig Bot 形式 | ツール名とファイル拡張子を確認 | Craig Bot (.flac/.opus) と確定 |
| SRT 形式 | 出力フォーマットの期待を確認 | SRT（話者ラベル付き統合ファイル）と確定 |
| フォルダ単位で管理 | ディレクトリ構造を確認 | ミーティングごとにフォルダがある構成と確定 |

## Technical Context

### 入力ファイル仕様
- ツール: Craig Bot（Discord 用録音 Bot）
- 形式: ユーザーごとに `.flac` または `.opus`
- 命名規則: `<discord_username>.<ext>`（例: `alice.flac`, `bob.opus`）
- 格納: `<meeting_folder>/` にフラットに配置

### 推奨実装スタック
```
Python 3.9+
openai-whisper または faster-whisper（Whisper large-v3）
ffmpeg（.opus デコード用）
```

### CLI インターフェース
```
python transcribe.py <meeting_folder>
```

### 処理フロー
```
1. meeting_folder/ から *.flac, *.opus を列挙
2. 各ファイルに対して:
   a. Whisper large-v3 で transcribe(language="ja")
   b. segments（start, end, text）を取得
   c. speaker = filename.stem でラベル付け
3. 全 segments を start 時刻でソート
4. SRT フォーマットに変換（[speaker] text）
5. meeting_folder/transcript.srt に書き出し
```

### SRT 出力例
```
1
00:00:01,000 --> 00:00:05,230
[alice] こんにちは、今日はよろしくお願いします。

2
00:00:06,100 --> 00:00:09,800
[bob] こちらこそ、よろしくお願いします。

3
00:00:10,200 --> 00:00:15,500
[alice] では早速ですが、本日の議題に入りましょう。
```

## Ontology (Key Entities)

| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| Meeting | core domain | folder_path, date | has many AudioTrack, produces SRTFile |
| AudioTrack | core domain | file_path, format (flac/opus), speaker_name | belongs to Meeting, has many TranscriptSegment |
| Speaker | core domain | name (from filename stem) | owns AudioTrack |
| TranscriptSegment | core domain | start_time, end_time, text, speaker_name | belongs to AudioTrack, part of SRTFile |
| SRTFile | output artifact | file_path, entries | aggregates TranscriptSegment |

## Ontology Convergence

| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 4 | 4 | - | - | N/A |
| 2 | 5 | 1 | 0 | 4 | 80% |
| 3-7 | 5 | 0 | 0 | 5 | 100% |
| 8 (final) | 5 | 0 | 0 | 5 | 100% |

## Interview Transcript

<details>
<summary>Full Q&A (8 rounds)</summary>

### Round 0 (Topology)
**Q:** 4つのコンポーネント（音声ファイル入力、STT変換、話者マージ、結果出力）で合っているか？
**A:** 正しい（4つで合っている）

### Round 1
**Q:** すでにあるファイルを処理したい vs リアルタイム録音？
**A:** すでにあるファイルを処理したい
**Ambiguity:** 72% (Goal: 0.40, Constraints: 0.30, Criteria: 0.10)

### Round 2
**Q:** 最終出力の形式（話者名付きテキスト / SRT / JSON / 形式不問）？
**A:** SRT/VTT字幕ファイル
**Ambiguity:** 60% (Goal: 0.50, Constraints: 0.30, Criteria: 0.35)

### Round 3
**Q:** STTサービス（Whisper ローカル / API / その他）？
**A:** 無料で高品質なものがいい → Whisper ローカルを推奨
**Ambiguity:** 55% (Goal: 0.60, Constraints: 0.35, Criteria: 0.35)

### Round 4
**Q:** 入力ファイルの録音ツール・形式（Craig Bot / 手動 / OBS など）？
**A:** Craig Bot（.flacまたは.opus）
**Ambiguity:** 47% (Goal: 0.65, Constraints: 0.50, Criteria: 0.40)

### Round 5
**Q:** 音声の言語？
**A:** 日本語のみ
**Ambiguity:** 40% (Goal: 0.72, Constraints: 0.60, Criteria: 0.45)

### Round 6
**Q:** 実行方法（Python CLI / GUI / Shell など）？
**A:** Pythonスクリプト（CLI）
**Ambiguity:** 30.5% (Goal: 0.80, Constraints: 0.65, Criteria: 0.60)

### Round 7
**Q:** SRTの出力構成（統合1ファイル / 話者別 / 両方）？
**A:** 1つの統合SRT（話者ラベル付き）
**Ambiguity:** 20.4% (Goal: 0.85, Constraints: 0.72, Criteria: 0.80)

### Round 8
**Q:** ディレクトリ構成とCLI引数の形式？
**A:** ミーティングごとのフォルダ → python transcribe.py meeting_folder/
**Ambiguity:** 10.6% (Goal: 0.90, Constraints: 0.88, Criteria: 0.90)

</details>
