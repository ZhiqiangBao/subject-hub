#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "请在 Ubuntu 评测主机上运行。" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "这里不是 Git 仓库。" >&2; exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "已有未提交的跟踪文件修改；请先自行保存，更新没有改动这些文件。" >&2; exit 1
fi
if ! systemctl is-active --quiet subject-hub.service; then
  echo "服务未运行；请先启动 systemd 服务并确认没有其他进程写入数据，再更新。" >&2; exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" || ! -d "$ROOT/frontend/dist" ]]; then
  echo "旧运行环境或前端构建不完整，无法保证回退，取消更新。" >&2; exit 1
fi
BEFORE="$(git rev-parse HEAD)"
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"
git fetch
AFTER="$(git rev-parse "$UPSTREAM")"
if [[ "$BEFORE" == "$AFTER" ]]; then echo "已经是最新版本。"; exit 0; fi
if ! git merge-base --is-ancestor "$BEFORE" "$AFTER"; then
  echo "远端不能快进；请先自行处理分支，不会覆盖本地修改。" >&2; exit 1
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
VENV_DIR="$ROOT/.venvs/$STAMP"
SAVE="$ROOT/.upgrade-saved/$STAMP"
service_data_dir() {
  local pid
  pid="$(systemctl show --value --property=MainPID subject-hub.service)"
  if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then echo "无法确定服务进程。" >&2; return 1; fi
  # Match config.py's relative-path semantics against the actual process cwd.
  sudo python3 -c '
import os, sys
pid, checkout = sys.argv[1:]
cwd = os.readlink("/proc/" + pid + "/cwd")
env = dict(entry.split(b"=", 1) for entry in open("/proc/" + pid + "/environ", "rb").read().split(b"\0") if b"=" in entry)
root = os.path.abspath(os.path.join(cwd, os.fsdecode(env.get(b"SUBJECT_HUB_ROOT") or os.fsencode(checkout))))
if os.path.realpath(cwd) != os.path.realpath(checkout) or os.path.realpath(root) != os.path.realpath(checkout):
    sys.exit("服务工作目录或 SUBJECT_HUB_ROOT 不属于此安装，取消更新")
data = os.path.abspath(os.path.join(cwd, os.fsdecode(env.get(b"SUBJECT_HUB_DATA") or os.fsencode(os.path.join(root, "data")))))
if "\n" in data or "\r" in data:
    sys.exit("数据路径包含换行，取消更新")
print(data)
' "$pid" "$ROOT"
}
DATA_DIR="$(service_data_dir)"
STAGE="$(mktemp -d "$ROOT/.upgrade-stage.XXXXXX")"
BACKUP_ROOT="${SUBJECT_HUB_BACKUP_ROOT:-$ROOT/../subject-hub-backups}"
BACKUP="$BACKUP_ROOT/$STAMP"
STOPPED=0
SWITCHED=0
cleanup() {
  status=$?
  trap - EXIT
  rm -rf -- "$STAGE"
  if (( status != 0 )); then
    if (( SWITCHED == 0 )); then rm -rf -- "$VENV_DIR"; fi
    if (( STOPPED == 1 && SWITCHED == 0 )); then
      sudo systemctl start subject-hub.service || echo "旧服务未能重启，请检查 systemctl status subject-hub.service" >&2
    fi
    echo "更新失败。升级前版本：$BEFORE；备份（如果已创建）：$BACKUP；保留目录：$SAVE" >&2
    if (( SWITCHED == 1 )); then
      echo "切换已开始，服务保持停止。回退：./scripts/rollback-ubuntu.sh '$SAVE'" >&2
      sudo systemctl stop subject-hub.service || true
    fi
  fi
  exit "$status"
}
trap cleanup EXIT

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "需要 Python 3.10 或更新版本。" >&2; exit 1; }
node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); process.exit((a===22 && (b>22 || (b===22 && c>=2))) || (a===24 && b>=15) || a>=26 ? 0 : 1)' || { echo "需要 Node.js 22.22.2+（22 系列）、24.15+（24 系列）或 26+。" >&2; exit 1; }
# Build a complete candidate without touching the running version.
git archive "$AFTER" | tar -x -C "$STAGE"
mkdir -p "$ROOT/.venvs" "$SAVE" "$BACKUP_ROOT"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -r "$STAGE/backend/requirements.txt"
"$VENV_DIR/bin/python" "$STAGE/scripts/test_backend.py"
(cd "$STAGE/frontend" && npm ci && npm run typecheck && npm test && npm run build)

if [[ "$(git rev-parse HEAD)" != "$BEFORE" || -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "构建期间本地版本或文件已变更，取消更新。" >&2; exit 1
fi
if [[ "$(service_data_dir)" != "$DATA_DIR" ]]; then echo "构建期间服务数据目录已变更，取消更新。" >&2; exit 1; fi
STOPPED=1
sudo systemctl stop subject-hub.service
if systemctl is-active --quiet subject-hub.service; then
  echo "服务仍在运行，取消更新。" >&2; exit 1
fi
python3 "$STAGE/scripts/backup_restore.py" backup --data-dir "$DATA_DIR" --output "$BACKUP" --service-stopped
python3 "$STAGE/scripts/backup_restore.py" verify --backup "$BACKUP"
printf '%s\n' "$BEFORE" > "$SAVE/previous-commit"
printf '%s\n' "$AFTER" > "$SAVE/installed-commit"
printf '%s\n' "$BACKUP" > "$SAVE/backup-path"
printf '%s\n' "$DATA_DIR" > "$SAVE/data-path"
# Fast-forward preserves local commits and refuses untracked-file conflicts.
git merge --ff-only "$AFTER"
SWITCHED=1
if [[ -L "$ROOT/.venv" ]]; then
  old_venv="$(readlink -f -- "$ROOT/.venv")"
  [[ -d "$old_venv" ]] || { echo "旧运行环境链接无效，停止切换。" >&2; exit 1; }
  ln -s -- "$old_venv" "$SAVE/venv"
  rm -- "$ROOT/.venv"
elif [[ -e "$ROOT/.venv" ]]; then
  mv "$ROOT/.venv" "$SAVE/venv"
fi
ln -s "$VENV_DIR" "$ROOT/.venv"
if [[ -e "$ROOT/frontend/dist" ]]; then mv "$ROOT/frontend/dist" "$SAVE/dist"; fi
mv "$STAGE/frontend/dist" "$ROOT/frontend/dist"
sudo systemctl start subject-hub.service
HEALTH_URL="${SUBJECT_HUB_HEALTH_URL:-http://127.0.0.1:8090/api/health}"
healthy=0
for attempt in {1..30}; do
  if systemctl is-active --quiet subject-hub.service && python3 -c 'import json,sys,urllib.request; r=urllib.request.urlopen(sys.argv[1],timeout=1); d=json.load(r); sys.exit(0 if r.status == 200 and d.get("ok") is True else 1)' "$HEALTH_URL" 2>/dev/null; then
    healthy=$((healthy + 1))
    if (( healthy >= 2 )); then break; fi
  else
    healthy=0
  fi
  sleep 1
done
if (( healthy < 2 )); then echo "新服务健康检查超时：$HEALTH_URL" >&2; exit 1; fi
STOPPED=0
echo "更新完成：$AFTER"
echo "升级前备份：$BACKUP"
echo "旧版本环境与前端：$SAVE"
echo "需要回退时：./scripts/rollback-ubuntu.sh '$SAVE'"
