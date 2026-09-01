@echo off
REM ============================================================
REM  screen-audio-recorder build batch (PyInstaller)
REM
REM  - Build spec with venv PyInstaller
REM  - Write progress to logs\build_status.txt (RUNNING/SUCCESS/FAILED)
REM  - Record all output to logs\build.log
REM
REM  build-watch.ps1 polls build_status.txt and reports result.
REM  NOTE: ASCII only. Do not add non-ASCII text to this file.
REM ============================================================
setlocal

REM Move to project root (parent of this batch dir)
cd /d "%~dp0.."

set "LOG_DIR=logs"
set "STATUS_FILE=%LOG_DIR%\build_status.txt"
set "LOG_FILE=%LOG_DIR%\build.log"
set "SPEC=screen_audio_recorder.spec"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Prefer venv Python, fall back to PATH python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

REM Init status (record start time)
> "%STATUS_FILE%" echo RUNNING %date% %time%

echo ============================================================>> "%LOG_FILE%"
echo [BUILD START] %date% %time%>> "%LOG_FILE%"
echo ============================================================>> "%LOG_FILE%"

REM Run build (stdout + stderr to log)
"%PY%" -m PyInstaller "%SPEC%" --noconfirm >> "%LOG_FILE%" 2>&1

if %ERRORLEVEL% EQU 0 (
    > "%STATUS_FILE%" echo SUCCESS %date% %time%
    echo [BUILD SUCCESS] %date% %time%>> "%LOG_FILE%"
) else (
    > "%STATUS_FILE%" echo FAILED %date% %time% exitcode=%ERRORLEVEL%
    echo [BUILD FAILED] exitcode=%ERRORLEVEL% %date% %time%>> "%LOG_FILE%"
)

endlocal
