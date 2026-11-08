import importlib.util
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('backup_restore', Path(__file__).resolve().parents[1] / 'scripts/backup_restore.py')
backup_restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_restore)

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.db = sqlite3.connect(self.data / 'subject-hub.db')
        self.db.execute('pragma journal_mode=wal')
        self.db.execute('create table items (value text)')
        self.db.execute("insert into items values ('saved')")
        self.db.commit()
        (self.data / 'local-bank').mkdir()
        (self.data / 'local-bank' / 'q.yaml').write_text('题目', encoding='utf-8')
        (self.data / 'uploads').mkdir()
        (self.data / 'uploads' / 'photo.bin').write_bytes(b'photo')
        (self.data / 'llm.env').write_text('key=secret', encoding='utf-8')
        self.copy = self.root / 'backup'

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_round_trip_including_wal_and_config(self):
        backup_restore.backup(self.data, self.copy)
        backup_restore.verify(self.copy)
        dest = self.root / 'restored'
        backup_restore.restore(self.copy, dest)
        with closing(sqlite3.connect(dest / 'subject-hub.db')) as db:
            self.assertEqual(db.execute('select value from items').fetchall(), [('saved',)])
        self.assertEqual((dest / 'local-bank/q.yaml').read_text(encoding='utf-8'), '题目')
        self.assertEqual((dest / 'uploads/photo.bin').read_bytes(), b'photo')
        self.assertEqual((dest / 'llm.env').read_text(encoding='utf-8'), 'key=secret')
        with self.assertRaises(ValueError): backup_restore.restore(self.copy, dest)
        self.assertEqual((dest / 'uploads/photo.bin').read_bytes(), b'photo')

    def test_corruption_and_unexpected_file_rejected(self):
        backup_restore.backup(self.data, self.copy)
        (self.copy / 'uploads/photo.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError): backup_restore.verify(self.copy)
        with self.assertRaises(ValueError): backup_restore.restore(self.copy, self.root / 'restored')
        self.assertFalse((self.root / 'restored').exists())

    def test_manifest_traversal_rejected(self):
        backup_restore.backup(self.data, self.copy)
        manifest = self.copy / 'manifest.json'
        raw = json.loads(manifest.read_text(encoding='utf-8'))
        raw['files']['../outside'] = 'anything'
        manifest.write_text(json.dumps(raw), encoding='utf-8')
        with self.assertRaises(ValueError): backup_restore.restore(self.copy, self.root / 'restored')
        self.assertFalse((self.root / 'outside').exists())

    def test_link_rejected(self):
        try:
            (self.data / 'uploads/link').symlink_to(self.data / 'llm.env')
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links unavailable')
        with self.assertRaises(ValueError): backup_restore.backup(self.data, self.copy)
        self.assertFalse(self.copy.exists())

if __name__ == '__main__': unittest.main()
