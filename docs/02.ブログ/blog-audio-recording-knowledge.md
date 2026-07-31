# Windows で Python 音声録音のとぎれとぎれ問題を解決した話

## はじめに

Python で Windows 向けの画面・音声録画アプリを開発した際、**音声録音がとぎれとぎれになる問題**に何度もぶつかりました。最終的に解決できたので、試行錯誤の過程と得られた知見をまとめます。

## 環境

- Windows 10/11
- Python 3.14
- PyAudioWPatch（WASAPI ループバック対応）
- PyInstaller でexe配布

## やりたかったこと

- マイク音声とシステム音声（PC出力音）を同時に録音
- WAV ファイルとして保存
- 途切れなく連続録音

## 失敗した方法（5回以上試行錯誤）

### 方法1: stream.read() ポーリング + キュー + ミックスワーカー

```
PyAudio stream.read() → Queue → ミックスワーカースレッド → Queue → エンコーダスレッド → ffmpeg stdin
```

**問題:** 3段のキューを経由するため、スレッドスケジューリングの遅延でデータが欠落。特に `get_nowait()` でポーリングすると、データがない瞬間にスキップされる。

### 方法2: stream.read() ポーリング + 直接 WAV 書き込み

```
PyAudio stream.read() → WAV ファイル直接書き込み
```

**問題:** `stream.read()` はブロッキング呼び出しだが、Python の GIL とスレッドスケジューリングにより、読み取りが間に合わないことがある。特に `CHUNK_SIZE=1024`（約23ms）だと、44100Hz で毎秒43回の read が必要で、タイミングがシビア。

### 方法3: PyAudio コールバックモード + 1つの WAV に2スレッドから書き込み

```
PyAudio callback(システム音声) → WAV ファイル
PyAudio callback(マイク) → 同じ WAV ファイル
```

**問題:** 2つのコールバックが同じ WAV ファイルに書き込むと、データが交互に混ざって途切れる。ロック（`threading.Lock`）を使っても、ロック競合でコールバックがブロックされてデータが欠落。

### 方法4: sounddevice ライブラリ

```
sounddevice.InputStream(callback) → WAV ファイル
```

**問題:** `sounddevice`（PortAudio ベース）は WASAPI ループバック（システム音声キャプチャ）に対応していない。通常の入力デバイス（マイク）しか使えないため、システム音声が無音になる。

### 方法5: ffmpeg stdin パイプに音声データを書き込み

```
PyAudio stream.read() → ffmpeg subprocess stdin パイプ
```

**問題:** Windows のパイプバッファ制限（約64KB）を超えるデータを一度に書き込むと `[Errno 22] Invalid argument` が発生。分割書き込みしても、パイプのバッファリングで途切れが発生。

## 成功した方法: 別々の WAV + 後でマージ

```
PyAudio callback(システム音声) → system.wav（独立した WAV ファイル）
PyAudio callback(マイク)       → mic.wav（独立した WAV ファイル）
                                    ↓ 録音停止後
                              ffmpeg amix → merged.wav
```

### ポイント

1. **PyAudioWPatch のコールバックモードを使う**（`stream_callback` パラメータ）
2. **各音声ソースを独立した WAV ファイルに書き込む**（ロック競合なし）
3. **録音停止後に ffmpeg でマージする**（リアルタイム処理不要）

### コード（核心部分）

```python
import pyaudiowpatch as pyaudio
import wave

CHUNK_SIZE = 4096  # 大きめに設定（途切れ防止）

# システム音声用 WAV
sys_wav = wave.open("system.wav", "wb")
sys_wav.setnchannels(device_channels)
sys_wav.setsampwidth(2)  # 16bit
sys_wav.setframerate(device_rate)

# コールバック: ドライバから直接データを受け取り WAV に書き込む
def sys_callback(in_data, frame_count, time_info, status):
    sys_wav.writeframes(in_data)
    return (None, pyaudio.paContinue)

# コールバックモードでストリームを開く
pa = pyaudio.PyAudio()
stream = pa.open(
    format=pyaudio.paInt16,
    channels=device_channels,
    rate=device_rate,
    input=True,
    input_device_index=loopback_device_index,
    frames_per_buffer=CHUNK_SIZE,
    stream_callback=sys_callback,  # ← これが重要
)
stream.start_stream()

# マイクも同様に別の WAV + 別のコールバックで録音
# ...

# 録音停止後にマージ
# ffmpeg -i system.wav -i mic.wav -filter_complex amix=inputs=2 merged.wav
```

## 学んだこと

### 1. コールバックモード vs ポーリングモード

| | ポーリング (`stream.read()`) | コールバック (`stream_callback`) |
|---|---|---|
| データ取得 | Python スレッドが能動的に読む | オーディオドライバが直接呼ぶ |
| GIL の影響 | 大きい（read のタイミングがずれる） | 小さい（C レベルで呼ばれる） |
| 途切れリスク | 高い | 低い |
| 実装の複雑さ | シンプル | やや複雑 |

**結論:** 音声録音は必ずコールバックモードを使うべき。

### 2. WASAPI ループバックの注意点

- **PyAudioWPatch** が必要（標準の PyAudio では WASAPI ループバックが使えない）
- ループバックデバイスのサンプルレートは OS のデフォルト出力デバイスに依存（多くの場合 **48000Hz**、44100Hz ではない）
- WAV ファイルのサンプルレートをデバイスのネイティブレートに合わせないと、再生速度がおかしくなる
- `sounddevice` ライブラリは WASAPI ループバックに対応していない

### 3. 複数音声ソースの同時録音

- **同じファイルに2スレッドから書き込むのは NG**（ロック競合でデータ欠落）
- **別々のファイルに書き込んで後でマージ**が最も安定
- ffmpeg の `amix` フィルターで簡単にマージできる

### 4. CHUNK_SIZE の選び方

| CHUNK_SIZE | 1回の read 時間 (44100Hz) | 途切れリスク |
|---|---|---|
| 512 | 約12ms | 非常に高い |
| 1024 | 約23ms | 高い |
| 4096 | 約93ms | 低い |
| 8192 | 約186ms | 非常に低い（遅延大） |

**推奨:** `4096`（途切れと遅延のバランスが良い）

### 5. PyInstaller でのパッケージング注意点

- `dxcam` は PyInstaller 環境で DXGI Duplicator の初期化に失敗することがある → `mss` をフォールバックに使う
- `janome` の辞書データ（`sysdic/`）を `datas` に含める必要がある
- `ffmpeg` バイナリは `imageio-ffmpeg` パッケージで取得して同梱するのが楽
- `libx264` は幅・高さが **2の倍数** でないとエラーになる → 解像度を `& ~1` で偶数に丸める
- 全画面キャプチャのフレーム（約6MB）を `stdin.write()` で一度に書き込むと Windows のパイプバッファ制限で `[Errno 22]` → 32KB ずつ分割書き込み

## まとめ

Python での Windows 音声録音は、一見シンプルに見えて罠が多いです。特に：

- **コールバックモードを使う**（ポーリングは途切れる）
- **複数ソースは別ファイルに録音して後でマージ**（同時書き込みは NG）
- **デバイスのネイティブサンプルレートを使う**（44100Hz 固定は NG）

この3つを守れば、途切れのない安定した録音が実現できます。
