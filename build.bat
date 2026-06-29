@echo off
REM ==========================================================================
REM  LAN Voice Call - Windows build script
REM  Produces dist\LANVoiceCall\LANVoiceCall.exe (one-folder distribution)
REM ==========================================================================
setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo   LAN Voice Call - Windows Build
echo ============================================================
echo.

REM --- 1. Check Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.10/3.11/3.12 from https://python.org
    echo         Make sure to tick "Add Python to PATH" during install.
    exit /b 1
)
echo [1/6] Python found:
python --version

REM --- 2. Install dependencies ---
echo.
echo [2/6] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r "%~dp0lan_voice_call\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    exit /b 1
)

REM --- 3. Download libopus.dll if missing ---
set "DLL_DIR=%~dp0dll"
if not exist "%DLL_DIR%" mkdir "%DLL_DIR%"
set "OPUS_DLL=%DLL_DIR%\opus.dll"

if exist "%OPUS_DLL%" (
    echo.
    echo [3/6] opus.dll already present, skipping download.
) else (
    echo.
    echo [3/6] Downloading libopus DLL...
    REM Try PowerShell first (Win10+)
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ProgressPreference='SilentlyContinue';" ^
      "$url='https://github.com/xiph/opus/releases/download/v1.5.2/opus-1.5.2.zip';" ^
      "$tmp=Join-Path $env:TEMP 'opus.zip';" ^
      "try { Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing } catch { Write-Host 'Download failed:' $_.Exception.Message; exit 1 };" ^
      "Expand-Archive -Path $tmp -DestinationPath (Join-Path $env:TEMP 'opus_extract') -Force;" ^
      "$src = Get-ChildItem -Path (Join-Path $env:TEMP 'opus_extract') -Recurse -Filter 'opus.dll' ^| Select-Object -First 1;" ^
      "if (-not $src) { $src = Get-ChildItem -Path (Join-Path $env:TEMP 'opus_extract') -Recurse -Filter 'libopus-0.dll' ^| Select-Object -First 1 };" ^
      "if (-not $src) { Write-Host 'opus.dll not found in archive'; exit 1 };" ^
      "Copy-Item $src.FullName '%OPUS_DLL%' -Force;" ^
      "Write-Host 'Downloaded opus.dll (' $src.Name ')'"
    if errorlevel 1 (
        echo.
        echo [WARNING] Automatic download failed.
        echo   Please download opus.dll manually:
        echo     1. Go to https://opus-codec.org/downloads/
        echo     2. Or grab the Windows binary from
        echo        https://github.com/xiph/opus/releases
        echo     3. Place the file as: %OPUS_DLL%
        echo.
        echo   Continuing anyway - the app will fall back to raw PCM
        echo   (larger bandwidth but same functionality).
    )
)

REM --- 4. Make sure portaudio is bundled with sounddevice ---
echo.
echo [4/6] Ensuring PortAudio is bundled...
python -c "import sounddevice; print('  sounddevice at:', sounddevice.__file__)"
python -c "import _sounddevice_data; print('  PortAudio data:', _sounddevice_data.__path__)" 2>nul

REM --- 5. Build the exe ---
echo.
echo [5/6] Building exe with PyInstaller...
cd /d "%~dp0"
pyinstaller --noconfirm --clean LANVoiceCall.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

REM --- 6. Copy opus.dll next to the exe (PyInstaller spec picks it up via dll/) ---
echo.
echo [6/6] Verifying build output...
set "DIST_DIR=%~dp0dist\LANVoiceCall"
if not exist "%DIST_DIR%\LANVoiceCall.exe" (
    echo [ERROR] Build output not found: %DIST_DIR%\LANVoiceCall.exe
    exit /b 1
)
echo   Build OK: %DIST_DIR%\LANVoiceCall.exe

REM Show final size
powershell -NoProfile -Command "$size = (Get-ChildItem -Recurse '%DIST_DIR%' ^| Measure-Object -Property Length -Sum).Sum; Write-Host ('  Total size: ' + [math]::Round($size/1MB, 1) + ' MB')"

echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo.
echo   Your app is ready at:
echo     %DIST_DIR%\LANVoiceCall.exe
echo.
echo   To distribute: zip the entire "LANVoiceCall" folder and
echo   send it to other PCs on your LAN. No Python install needed.
echo.
echo   First run on each PC: just double-click LANVoiceCall.exe.
echo   Windows may show a SmartScreen warning - click "More info"
echo   then "Run anyway" (the app is not code-signed).
echo.
pause
endlocal
