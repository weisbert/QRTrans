#!/bin/bash
# Linux 红区离线安装脚本
# 前提：项目目录中已包含 wheels/linux/ 子目录（由黄区 prepare_wheels.bat 生成）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# pyzbar 依赖系统库 libzbar，必须用包管理器提前安装
echo "========================================"
echo "注意：pyzbar 需要系统库 libzbar"
echo "  CentOS/RHEL: sudo yum install zbar"
echo "  Debian/Ubuntu: sudo apt install libzbar0"
echo "  请确认已安装，否则 pyzbar 导入会失败"
echo "  （程序仍可运行，会 fallback 到 opencv 识别）"
echo "========================================"
echo ""

echo "Installing QR DataBridge dependencies from local wheels (Linux)..."
pip install --no-index --find-links="$SCRIPT_DIR/wheels/linux/" -r "$SCRIPT_DIR/requirements-linux.txt"

echo ""
echo "Done. 启动方式: python main.py"
