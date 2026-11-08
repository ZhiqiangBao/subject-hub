#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "请在 Ubuntu 评测主机上运行。"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
SERVICE_SRC="$ROOT/scripts/subject-hub.service"
UNIT="/etc/systemd/system/subject-hub.service"

if [[ -e "$ROOT/.venv" || -L "$ROOT/.venv" ]]; then
  echo "已存在运行环境；为避免覆盖，请用 ./scripts/update-from-github.sh 更新。" >&2
  exit 1
fi
if systemctl is-active --quiet subject-hub.service; then
  echo "服务正在运行，请使用更新脚本。" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nodejs npm

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "需要 Python 3.10 或更新版本（本机已验证 3.13）。" >&2; exit 1; }
node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); process.exit((a===22 && (b>22 || (b===22 && c>=2))) || (a===24 && b>=15) || a>=26 ? 0 : 1)' || { echo "需要 Node.js 22.22.2+（22 系列）、24.15+（24 系列）或 26+；请先安装受支持版本。" >&2; exit 1; }

cd "$ROOT"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python scripts/test_backend.py

if command -v npm >/dev/null; then
  (cd frontend && npm ci && npm run build)
else
  echo "需要 Node.js / npm 才能构建网页。"
  exit 1
fi

sed \
  -e "s|@ROOT@|$ROOT|g" \
  -e "s|@USER@|$USER_NAME|g" \
  "$SERVICE_SRC" | sudo tee "$UNIT" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now subject-hub.service

echo
echo "学科 Hub 已在本机运行。"
echo "家里其他设备打开：http://$(hostname -I | awk '{print $1}'):8090"
echo "如开了 ufw：sudo ufw allow 8090/tcp"
echo "家长在本机注册管理员（可多位）：http://127.0.0.1:8091"
echo "8090 上注册的都是学生，第一个人不会自动变成管理员。"
echo "以后更新：./scripts/update-from-github.sh"
