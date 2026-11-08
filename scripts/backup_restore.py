#!/usr/bin/env python3
"""Create, verify and restore an offline Subject Hub data backup."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath

MANIFEST = 'manifest.json'
DATABASE = 'subject-hub.db'


def safe_root(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError(f'不允许符号链接: {entry}')
    return path


def scan(root: Path) -> tuple[list[str], list[str]]:
    if not root.is_dir():
        raise ValueError(f'目录不存在: {root}')
    dirs, files = [], []
    for current, names, filenames in os.walk(root, followlinks=False):
        for name in names + filenames:
            path = Path(current) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError(f'不允许符号链接或特殊文件: {path}')
            rel = path.relative_to(root).as_posix()
            (dirs if stat.S_ISDIR(mode) else files).append(rel)
    return sorted(dirs), sorted(files)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_sqlite(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        result = db.execute('PRAGMA integrity_check').fetchall()
        if result != [('ok',)]:
            raise ValueError('SQLite 完整性检查失败')


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('备份路径无效')
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')) or ':' in value:
        raise ValueError('备份包含不安全路径')
    return value


def verify(backup: Path) -> None:
    backup = safe_root(backup)
    dirs, files = scan(backup)
    manifest_path = backup / MANIFEST
    if MANIFEST not in files:
        raise ValueError('缺少备份清单')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('version') != 1:
        raise ValueError('不支持的备份格式')
    recorded_files, recorded_dirs = manifest.get('files'), manifest.get('directories')
    if not isinstance(recorded_files, dict) or not isinstance(recorded_dirs, list):
        raise ValueError('备份清单无效')
    for rel in list(recorded_files) + recorded_dirs:
        safe_relative(rel)
    if len(recorded_dirs) != len(set(recorded_dirs)):
        raise ValueError('备份清单重复目录')
    if set(files) != set(recorded_files) | {MANIFEST} or set(dirs) != set(recorded_dirs):
        raise ValueError('备份文件与清单不一致')
    if DATABASE not in recorded_files:
        raise ValueError('备份缺少数据库')
    for rel, expected in recorded_files.items():
        if not isinstance(expected, str) or digest(backup / rel) != expected:
            raise ValueError(f'备份校验失败: {rel}')
    check_sqlite(backup / DATABASE)


def backup(data: Path, output: Path) -> None:
    data, output = safe_root(data), safe_root(output)
    if data == output or data in output.parents or output in data.parents:
        raise ValueError('备份目录不能位于数据目录内或其上级')
    dirs, files = scan(data)
    if DATABASE not in files:
        raise ValueError('数据目录没有数据库，未创建备份')
    if MANIFEST in files:
        raise ValueError('数据目录含保留文件名 manifest.json')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for rel in dirs:
            (output / rel).mkdir(mode=0o700)
        for rel in files:
            if rel in {DATABASE, DATABASE + '-wal', DATABASE + '-shm'}:
                continue
            shutil.copyfile(data / rel, output / rel)
            os.chmod(output / rel, 0o600)
        with closing(sqlite3.connect((data / DATABASE).as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(output / DATABASE)) as target:
                source.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
        os.chmod(output / DATABASE, 0o600)
        _, copied = scan(output)
        manifest = {'version': 1, 'directories': dirs, 'files': {rel: digest(output / rel) for rel in copied}}
        (output / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chmod(output / MANIFEST, 0o600)
        verify(output)
    except BaseException:
        shutil.rmtree(output)
        raise


def restore(backup_dir: Path, output: Path) -> None:
    backup_dir, output = safe_root(backup_dir), safe_root(output)
    if output.exists() or output == backup_dir or backup_dir in output.parents or output in backup_dir.parents:
        raise ValueError('恢复目标必须是备份之外不存在的新目录')
    verify(backup_dir)
    tmp = Path(tempfile.mkdtemp(prefix='.subject-hub-restore-', dir=output.parent))
    try:
        dirs, files = scan(backup_dir)
        for rel in dirs:
            (tmp / rel).mkdir(mode=0o700)
        for rel in files:
            if rel != MANIFEST:
                shutil.copyfile(backup_dir / rel, tmp / rel)
                os.chmod(tmp / rel, 0o600)
        # Refuse any concurrent creation instead of replacing user data.
        os.mkdir(output, 0o700)
        try:
            for child in tmp.iterdir():
                child.rename(output / child.name)
        except BaseException:
            # Keep partial output for inspection; never delete a user-visible target.
            raise
    finally:
        shutil.rmtree(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('backup')
    create.add_argument('--data-dir', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--service-stopped', action='store_true', required=True, help='确认已停止所有写入数据目录的服务')
    check = commands.add_parser('verify')
    check.add_argument('--backup', type=Path, required=True)
    recover = commands.add_parser('restore')
    recover.add_argument('--backup', type=Path, required=True)
    recover.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            backup(args.data_dir, args.output)
        elif args.command == 'verify':
            verify(args.backup)
        else:
            restore(args.backup, args.output)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f'失败：{exc}', file=sys.stderr)
        return 1
    print('完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
