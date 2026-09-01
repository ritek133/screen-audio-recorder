# ============================================================
#  ビルド継続監視スクリプト
#
#  役割:
#    - logs\build_status.txt をポーリングして状態を監視
#    - 経過時間・ビルド中間ファイルサイズを定期表示
#    - SUCCESS / FAILED を検出したら結果を報告して終了
#
#  使い方:
#    powershell -ExecutionPolicy Bypass -File scripts\build-watch.ps1
#    powershell -File scripts\build-watch.ps1 -IntervalSec 10 -TimeoutSec 600
# ============================================================
param(
    [int]$IntervalSec = 5,     # ポーリング間隔(秒)
    [int]$TimeoutSec  = 900    # 監視タイムアウト(秒) 既定15分
)

$ErrorActionPreference = "Stop"

# プロジェクトルート (このスクリプトの1つ上)
$root       = Split-Path -Parent $PSScriptRoot
$statusFile = Join-Path $root "logs\build_status.txt"
$logFile    = Join-Path $root "logs\build.log"
$distDir    = Join-Path $root "dist\screen-audio-recorder"

Write-Host "==== ビルド監視開始 ====" -ForegroundColor Cyan
Write-Host "状態ファイル: $statusFile"
Write-Host "間隔: ${IntervalSec}秒 / タイムアウト: ${TimeoutSec}秒"
Write-Host ""

$start = Get-Date

while ($true) {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds

    # タイムアウト判定
    if ($elapsed -ge $TimeoutSec) {
        Write-Host "[TIMEOUT] ${TimeoutSec}秒以内に完了しませんでした。" -ForegroundColor Red
        exit 2
    }

    if (-not (Test-Path $statusFile)) {
        Write-Host ("[{0,4}s] 状態ファイル待機中..." -f $elapsed)
        Start-Sleep -Seconds $IntervalSec
        continue
    }

    $status = (Get-Content $statusFile -Raw).Trim()

    # dist の中間サイズ (進捗の目安)
    $sizeMB = 0
    if (Test-Path $distDir) {
        $sizeMB = [math]::Round(
            ((Get-ChildItem $distDir -Recurse -File -ErrorAction SilentlyContinue |
              Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    }

    switch -Regex ($status) {
        '^RUNNING' {
            Write-Host ("[{0,4}s] ビルド実行中... (dist: {1} MB)" -f $elapsed, $sizeMB)
        }
        '^SUCCESS' {
            Write-Host ""
            Write-Host "=== BUILD SUCCESS ===" -ForegroundColor Green
            Write-Host ("所要時間: 約 {0} 秒 / 成果物: {1} MB" -f $elapsed, $sizeMB)
            Write-Host "出力先: $distDir"
            exit 0
        }
        '^FAILED' {
            Write-Host ""
            Write-Host "=== BUILD FAILED ===" -ForegroundColor Red
            Write-Host "状態: $status"
            Write-Host "--- ログ末尾 30 行 ---" -ForegroundColor Yellow
            if (Test-Path $logFile) { Get-Content $logFile -Tail 30 }
            exit 1
        }
        default {
            Write-Host ("[{0,4}s] 不明な状態: {1}" -f $elapsed, $status)
        }
    }

    Start-Sleep -Seconds $IntervalSec
}
