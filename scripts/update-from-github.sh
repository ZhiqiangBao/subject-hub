#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "请在 Ubuntu 评测主机上运行。"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "这里还不是 git 仓库。请先从 GitHub 克隆。"
  exit 1
fi

BEFORE="$(git rev-parse HEAD)"
git pull --ff-only
AFTER="$(git rev-parse HEAD)"

changed() {
  git diff --name-only "$BEFORE" "$AFTER" | grep -q "$1"
}

if [[ "$BEFORE" != "$AFTER" ]]; then
  if changed '^backend/requirements.txt'; then
    "$ROOT/.venv/bin/pip" install -r backend/requirements.txt
  fi
  if changed '^frontend/'; then
    (cd frontend && npm install && npm run build)
  fi
fi

if systemctl is-enabled subject-hub >/dev/null 2>&1; then
  sudo systemctl restart subject-hub
  echo "已更新并重启学科 Hub。"
else
  echo "已拉取。请运行 ./scripts/run-ubuntu.sh 或先执行 setup。"
fi
