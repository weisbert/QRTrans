@echo off
REM 在黄区（有网的 Windows 机器）上执行此脚本，
REM 为红区（Linux）和本机（Windows）各自下载对应的离线 wheel 包。
REM 下载完成后，将整个项目文件夹（含 wheels\）拷入红区。

echo ========================================
echo 正在下载 Windows 离线包到 wheels\windows\
echo ========================================
pip download ^
    "qrcode[pil]==7.4.2" ^
    "Pillow==10.3.0" ^
    "numpy==1.26.4" ^
    "opencv-python==4.9.0.80" ^
    "pyzbar==0.1.9" ^
    -d wheels\windows\ ^
    --python-version 3.11 ^
    --platform win_amd64 ^
    --only-binary=:all:

if errorlevel 1 (
    echo [ERROR] Windows wheels 下载失败，请检查网络和 pip 版本
    pause
    exit /b 1
)

echo.
echo ========================================
echo 正在下载 Linux 离线包到 wheels\linux\
echo （opencv 使用 headless 版，无 GUI 依赖）
echo ========================================
pip download ^
    "qrcode[pil]==7.4.2" ^
    "Pillow==10.3.0" ^
    "numpy==1.26.4" ^
    "opencv-python-headless==4.9.0.80" ^
    "pyzbar==0.1.9" ^
    -d wheels\linux\ ^
    --python-version 3.11 ^
    --platform manylinux2014_x86_64 ^
    --only-binary=:all:

if errorlevel 1 (
    echo [ERROR] Linux wheels 下载失败，请检查网络和 pip 版本
    pause
    exit /b 1
)

echo.
echo ========================================
echo 全部完成！
echo   Windows 安装: install_offline.bat
echo   Linux   安装: bash install_offline.sh
echo 将整个项目目录（含 wheels\）拷入红区即可
echo ========================================
pause
