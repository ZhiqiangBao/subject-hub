#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != Linux || $# != 1 ]]; then
  echo "用法：./scripts/rollback-ubuntu.sh 更新时打印的旧版目录" >&2; exit 1
fi
SAVE="$(realpath -e -- "$1")"
case "$SAVE" in "$ROOT"/.upgrade-saved/*) ;; *) echo "旧版目录不在本安装的 .upgrade-saved 下。" >&2; exit 1;; esac
for path in previous-commit installed-commit backup-path data-path venv dist; do
  if [[ ! -e "$SAVE/$path" && ! -L "$SAVE/$path" ]]; then echo "缺少回退材料：$SAVE/$path" >&2; exit 1; fi
done
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "已有未提交的跟踪文件修改；请先自行保存。" >&2; exit 1
fi
BEFORE="$(cat "$SAVE/previous-commit")"
INSTALLED="$(cat "$SAVE/installed-commit")"
if [[ "$(git rev-parse HEAD)" != "$INSTALLED" ]]; then
  echo "当前版本与本次安装版本不同，可能有后续提交；拒绝回退。" >&2; exit 1
fi
BACKUP="$(cat "$SAVE/backup-path")"
DATA_DIR="$(cat "$SAVE/data-path")"
if systemctl is-active --quiet subject-hub.service; then
  pid="$(systemctl show --value --property=MainPID subject-hub.service)"
  if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]]; then echo "无法确定服务进程，取消回退。" >&2; exit 1; fi
  actual_data="$(sudo python3 -c '
import os, sys
pid, checkout = sys.argv[1:]
cwd = os.readlink("/proc/" + pid + "/cwd")
env = dict(entry.split(b"=", 1) for entry in open("/proc/" + pid + "/environ", "rb").read().split(b"\0") if b"=" in entry)
root = os.path.abspath(os.path.join(cwd, os.fsdecode(env.get(b"SUBJECT_HUB_ROOT") or os.fsencode(checkout))))
if os.path.realpath(cwd) != os.path.realpath(checkout) or os.path.realpath(root) != os.path.realpath(checkout):
    sys.exit("服务工作目录或 SUBJECT_HUB_ROOT 不属于此安装，取消回退")
data = os.path.abspath(os.path.join(cwd, os.fsdecode(env.get(b"SUBJECT_HUB_DATA") or os.fsencode(os.path.join(root, "data")))))
if "\n" in data or "\r" in data:
    sys.exit("数据路径包含换行，取消回退")
print(data)
' "$pid" "$ROOT")"
  if [[ "$actual_data" != "$DATA_DIR" ]]; then echo "运行中服务的数据目录与记录不一致，取消回退。" >&2; exit 1; fi
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RESTORED="${DATA_DIR}.restore-$STAMP"
PRESERVED="${DATA_DIR}.before-rollback-$STAMP"
ROLLBACK_BACKUP="$(dirname "$BACKUP")/before-rollback-$STAMP"
for path in "$RESTORED" "$PRESERVED" "$ROLLBACK_BACKUP" "$SAVE/failed-venv" "$SAVE/failed-dist"; do
  if [[ -e "$path" || -L "$path" ]]; then echo "目标已存在：$path" >&2; exit 1; fi
done
failure() {
  status=$?
  if (( status != 0 )); then
    sudo systemctl stop subject-hub.service || true
    echo "回退未完成，服务保持停止。旧备份：$BACKUP；当前数据保留路径：$PRESERVED；恢复副本：$RESTORED；旧版目录：$SAVE" >&2
  fi
}
trap failure EXIT
sudo systemctl stop subject-hub.service
if systemctl is-active --quiet subject-hub.service; then echo "服务仍在运行，取消回退。" >&2; exit 1; fi
python3 "$ROOT/scripts/backup_restore.py" verify --backup "$BACKUP"
python3 "$ROOT/scripts/backup_restore.py" backup --data-dir "$DATA_DIR" --output "$ROLLBACK_BACKUP" --service-stopped
python3 "$ROOT/scripts/backup_restore.py" restore --backup "$BACKUP" --output "$RESTORED"
if [[ "$(git rev-parse HEAD)" != "$INSTALLED" || -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "回退准备期间版本或跟踪文件已变更，拒绝回退。" >&2; exit 1
fi
git reset --keep "$BEFORE"
if [[ -L "$ROOT/.venv" ]]; then
  current_venv="$(readlink -f -- "$ROOT/.venv")"
  [[ -d "$current_venv" ]] || { echo "当前运行环境链接无效，停止回退。" >&2; exit 1; }
  ln -s -- "$current_venv" "$SAVE/failed-venv"
  rm -- "$ROOT/.venv"
elif [[ -e "$ROOT/.venv" ]]; then
  mv "$ROOT/.venv" "$SAVE/failed-venv"
fi
mv "$SAVE/venv" "$ROOT/.venv"
if [[ -e "$ROOT/frontend/dist" ]]; then mv "$ROOT/frontend/dist" "$SAVE/failed-dist"; fi
mv "$SAVE/dist" "$ROOT/frontend/dist"
mv "$DATA_DIR" "$PRESERVED"
mv "$RESTORED" "$DATA_DIR"
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
if (( healthy < 2 )); then echo "旧服务健康检查超时：$HEALTH_URL" >&2; exit 1; fi
echo "已恢复升级前版本和数据。升级后的数据保留在：$PRESERVED"
echo "回退前数据的独立备份：$ROLLBACK_BACKUP"
