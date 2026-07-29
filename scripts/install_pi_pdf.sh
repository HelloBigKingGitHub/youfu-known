#!/usr/bin/env bash
# scripts/install_pi_pdf.sh
# 一键装 Pi 上 PDF OCR 依赖 (Tesseract chi_sim + eng)
#
# 用法 (在 Pi 上跑):
#   sudo bash scripts/install_pi_pdf.sh

set -o pipefail

log_step() { echo -e "\n\033[1;34m=== $1 ===\033[0m"; }

log_step "youfu-known PDF OCR 安装 (Tesseract chi_sim + eng)"

echo "=== 1. apt install tesseract-ocr + chi_sim + eng ==="
sudo apt-get update -q
sudo apt-get install -y tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng

echo "=== 2. pip install pytesseract + Pillow ==="
if [ -f .venv/bin/pip ]; then
    .venv/bin/pip install pytesseract==0.3.13 Pillow==10.4.0
else
    pip install pytesseract==0.3.13 Pillow==10.4.0
fi

echo "=== 3. verify ==="
tesseract --version 2>&1 | head -3
echo
echo "Installed languages:"
tesseract --list-langs 2>&1 | grep -E "chi_sim|^eng$" | head -5

echo
echo "✅ Tesseract installed. youfu-known PDF OCR ready."
echo "Restart uvicorn to enable OCR: bash scripts/restart.sh"