import json
import os
import socket
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

root = Path(os.environ['SUBJECT_HUB_ROOT'])
(root / 'frontend/dist').mkdir(parents=True)
(root / 'frontend/dist/assets').mkdir()
(root / 'frontend/dist/index.html').write_text('test site', encoding='utf8')
(root / 'secret.txt').write_text('SENSITIVE-FILE-MARKER', encoding='utf8')
from app.main import app, initialize
from app.db import engine


def question(slug, kind, subject='math', allow_photo=False):
    data = {'slug': slug, 'title': '原题' + slug, 'subject': subject, 'grade': 7, 'difficulty': 'medium',
            'type': kind, 'stem': '原题干' + slug, 'points': 5, 'allow_photo': allow_photo}
    if kind == 'short':
        data.update(reference='原参考答案', rubric=[{'id': 'r1', 'points': 5, 'require': '原细则'}])
    else:
        data['answer'] = ['42']
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


class ApiWorkflow(unittest.TestCase):
    def ok(self, response, status=200):
        self.assertEqual(response.status_code, status, f'{response.request.method} {response.request.url}: {response.text}')
        return response.json()

    def register(self, client, name, password, subjects=None):
        return self.ok(client.post('/api/auth/register', json={'username': name, 'password': password,
                                                               'subjects': subjects or []}))

    def test_everything(self):
        # No lifespan: initialize the real application explicitly, with no server or worker.
        initialize()
        admin = TestClient(app, base_url='http://testserver:8091')
        other_admin = TestClient(app, base_url='http://testserver:8091')
        alice = TestClient(app, base_url='http://testserver:8090')
        bob = TestClient(app, base_url='http://testserver:8090')
        anon = TestClient(app, base_url='http://testserver:8090')
        self.addCleanup(engine.dispose)
        for client in (admin, other_admin, alice, bob, anon):
            self.addCleanup(client.close)
        for path in ('/%2e%2e/secret.txt', '/%2e%2e%2fsecret.txt', '/%2e%2e%5csecret.txt',
                     '/api/uploads/file/%2e%2e%2fsecret.txt'):
            response = anon.get(path)
            self.assertNotIn('SENSITIVE-FILE-MARKER', response.text, path)
        password = '长密码安全测试' * 8
        self.assertLessEqual(len(password), 64)
        self.assertGreater(len(password.encode('utf8')), 72)
        teacher = self.register(admin, '数学老师', password, ['math'])
        self.assertEqual(teacher['role'], 'admin')
        self.register(other_admin, '语文老师', 'pass', ['chinese'])
        a = self.register(alice, '学生甲', password)
        b = self.register(bob, '学生乙', 'pass')
        self.assertEqual(a['role'], 'student')
        self.ok(admin.post('/api/auth/logout'))
        self.ok(admin.post('/api/auth/login', json={'username': '数学老师', 'password': password}))
        self.ok(alice.post('/api/auth/logout'))
        self.ok(alice.post('/api/auth/login', json={'username': '学生甲', 'password': password}))
        self.assertEqual(alice.post('/api/auth/login', json={'username': '学生甲', 'password': password[:-1] + '另'}).status_code, 401)
        local = root / 'data/local-bank'
        source = question('short-one', 'short', allow_photo=True)
        self.ok(admin.post('/api/parent/ingest/paste?preview=true', json={'text': source}))
        self.assertFalse(list(local.glob('*.yaml')))
        for text, code in ((question('../outside', 'short'), 400),
                           (question('duplicate', 'short') + '\n---\n' + question('duplicate', 'short'), 409),
                           (question('outside-subject', 'short', 'chinese'), 403)):
            self.assertEqual(admin.post('/api/parent/ingest/paste', json={'text': text}).status_code, code)
        self.assertFalse(list(local.glob('*.yaml')))
        self.assertFalse((root / 'data/outside.yaml').exists())
        self.ok(admin.post('/api/parent/ingest/paste', json={'text': source}))
        self.ok(admin.post('/api/parent/ingest/paste', json={'text': question('blank-one', 'blank')}))
        self.assertEqual(admin.post('/api/parent/ingest/paste', json={'text': source}).status_code, 409)
        self.assertEqual(len(list(local.glob('*.yaml'))), 2)
        group = self.ok(admin.post('/api/parent/groups', json={'name': '七年级一组', 'kind': 'group'}))['id']
        self.ok(admin.post(f'/api/parent/groups/{group}/members', json={'student_id': a['id']}))
        paper = self.ok(admin.post('/api/parent/assemble', json={'subject': 'math', 'grade': 7, 'count': 2}))
        self.assertEqual({x['slug'] for x in paper['items']}, {'short-one', 'blank-one'})
        paper_id = paper['id']
        now = datetime.utcnow()
        window = {'opens_at': (now - timedelta(minutes=1)).isoformat(),
                  'closes_at': (now + timedelta(hours=1)).isoformat(), 'audiences': [{'group_id': group}]}
        self.ok(admin.post(f'/api/parent/papers/{paper_id}/release', json=window))
        attempt = self.ok(alice.post(f'/api/papers/{paper_id}/open'))['attempt_id']
        self.assertEqual(bob.post(f'/api/papers/{paper_id}/open').status_code, 403)
        self.ok(alice.put(f'/api/papers/attempts/{attempt}/item/short-one/draft', json={'parts': {'main': '我的答案'}}))
        self.ok(alice.put(f'/api/papers/attempts/{attempt}/item/blank-one/draft', json={'parts': {'main': '42'}}))
        photo = {'file': ('photo.png', b'\x89PNG\r\n\x1a\nfixture', 'image/png')}
        def upload(client, ident=attempt, slug='short-one'):
            return client.post(f'/api/uploads/paper/{ident}/{slug}/main', files=photo)
        self.assertEqual(upload(bob).status_code, 404)
        self.assertEqual(upload(alice, ident=999999).status_code, 404)
        self.assertEqual(upload(alice, slug='blank-one').status_code, 400)
        name = self.ok(upload(alice))['photos'][0]
        image_path = f'/api/uploads/file/{name}'
        self.assertEqual(alice.get(image_path).content, photo['file'][1])
        self.assertEqual(bob.get(image_path).status_code, 404)
        self.assertEqual(other_admin.get(image_path).status_code, 404)
        self.assertEqual(admin.get(image_path).content, photo['file'][1])
        self.ok(alice.post(f'/api/papers/attempts/{attempt}/submit'))
        editor = self.ok(admin.get('/api/parent/items/short-one'))
        editor['left_md'] = '改过的题干'
        editor['parts'][0]['reference'] = '改过的参考答案'
        editor['parts'][0]['rubric'][0]['require'] = '改过的评分细则'
        self.ok(admin.put('/api/parent/items/short-one', json=editor))
        old = self.ok(alice.get(f'/api/papers/attempts/{attempt}/item/short-one'))
        self.assertEqual(old['left_md'], '原题干short-one')
        self.assertEqual(self.ok(admin.get('/api/parent/items/short-one'))['left_md'], '改过的题干')
        window['closes_at'] = (now - timedelta(seconds=1)).isoformat()
        self.ok(admin.post(f'/api/parent/papers/{paper_id}/window', json=window))
        self.assertEqual(upload(alice).status_code, 409)
        self.ok(admin.post(f'/api/parent/papers/{paper_id}/start-grade'))
        review = self.ok(admin.get(f'/api/parent/review/paper/{attempt}'))
        short = next(row for row in review['items'] if row['slug'] == 'short-one')
        self.assertEqual(short['left_md'], '原题干short-one')
        part = short['parts'][0]
        self.assertEqual(part['reference'], '原参考答案')
        self.assertEqual(part['rubric'][0]['require'], '原细则')
        self.assertEqual(part['photos'], [name])
        self.assertEqual(part['status'], 'pending')
        self.assertEqual(other_admin.get(f'/api/parent/review/paper/{attempt}').status_code, 403)
        self.ok(admin.post('/api/parent/grade', json={'answer_id': part['answer_id'], 'score': 4, 'comment': '人工评分'}))
        self.ok(admin.post(f'/api/parent/papers/{paper_id}/release-scores'))
        final = self.ok(alice.get(f'/api/papers/attempts/{attempt}/item/short-one'))
        self.assertEqual(final['answers']['main']['score'], 4)
        self.assertEqual(final['answers']['main']['comment'], '人工评分')


if __name__ == '__main__':
    with patch.object(socket, 'create_connection', side_effect=AssertionError('external network prohibited')):
        unittest.main(verbosity=2)
