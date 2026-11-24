@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "WINDOW_MATERIAL=none"
set "WINDOW_LABEL=无窗口 / none"

if "%~1"=="" (
    echo.
    echo [PDV Studio 一键分析 - !WINDOW_LABEL!]
    echo 请将一个或多个 .csv / .dat 原始波形文件直接拖拽到本脚本图标上。
    echo 默认参数: 自动列识别 --auto-columns / s / V / 1550 nm / 0 deg / !WINDOW_MATERIAL!
    echo.
    pause
    exit /b 1
)

set "PDV_EXE="
if exist "%~dp0..\pdv.exe" set "PDV_EXE=%~dp0..\pdv.exe"
if not defined PDV_EXE (
    for /f "delims=" %%P in ('where pdv.exe 2^>nul') do (
        if not defined PDV_EXE set "PDV_EXE=%%~fP"
    )
)
if not defined PDV_EXE if exist "!LOCALAPPDATA!\Programs\PDV Studio\pdv.exe" (
    set "PDV_EXE=!LOCALAPPDATA!\Programs\PDV Studio\pdv.exe"
)
if not defined PDV_EXE if exist "!ProgramFiles!\PDV Studio\pdv.exe" (
    set "PDV_EXE=!ProgramFiles!\PDV Studio\pdv.exe"
)

if not defined PDV_EXE (
    echo.
    echo [错误] 未找到 pdv.exe。请先运行 PDV-Studio-Setup-x64.exe 安装 PDV Studio。
    echo.
    pause
    exit /b 1
)

echo 使用 CLI: "!PDV_EXE!"
echo 分析预设: 1550 nm / !WINDOW_LABEL! / 0 deg
set /a OK_COUNT=0
set /a FAIL_COUNT=0

for %%F in (%*) do call :analyze_one "%%~fF"

echo.
echo 全部处理完成: 成功 !OK_COUNT! 个, 失败 !FAIL_COUNT! 个。
pause
if !FAIL_COUNT! GTR 0 exit /b 1
exit /b 0

:analyze_one
set "SRC=%~f1"
if not exist "!SRC!" (
    echo [跳过] 文件不存在: !SRC!
    set /a FAIL_COUNT+=1
    goto :eof
)
if exist "!SRC!\*" (
    echo [跳过] 不支持文件夹, 请拖入 .csv 或 .dat 文件: !SRC!
    set /a FAIL_COUNT+=1
    goto :eof
)

set "SRC_DIR=%~dp1"
if "!SRC_DIR:~-1!"=="\" set "SRC_DIR=!SRC_DIR:~0,-1!"
set "BASE_PARENT=!SRC_DIR!"
set "RAW_TEST=!SRC_DIR:\data\raw=!"
if /i not "!RAW_TEST!"=="!SRC_DIR!" (
    set "BASE_PARENT=!USERPROFILE!\Desktop\PDV_Results"
)

if not exist "!BASE_PARENT!" mkdir "!BASE_PARENT!" >nul 2>nul
set "OUT_DIR=!BASE_PARENT!\%~n1_pdv_out"
if exist "!OUT_DIR!" (
    set /a SUFFIX=2
    :next_suffix
    set "CAND=!BASE_PARENT!\%~n1_pdv_out_!SUFFIX!"
    if exist "!CAND!" (
        set /a SUFFIX+=1
        goto :next_suffix
    )
    set "OUT_DIR=!CAND!"
)

echo.
echo 正在分析: !SRC!
echo 输出目录: !OUT_DIR!
"!PDV_EXE!" analyze "!SRC!" --auto-columns --time-unit s --voltage-units V --wavelength-m 1.55e-6 --angle-deg 0 --window-material !WINDOW_MATERIAL! --out "!OUT_DIR!"
if errorlevel 1 (
    echo [失败] 分析未完成: !SRC!
    set /a FAIL_COUNT+=1
) else (
    echo [成功] 结果已输出至: !OUT_DIR!
    set /a OK_COUNT+=1
)
goto :eof
