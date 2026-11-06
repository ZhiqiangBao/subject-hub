import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app.api.parent import router
from app.deps import get_admin_user
from app.models import User
from app.services.curriculum import lookup, CurriculumError
from app.services.generation import GenerationError, generate, validate

REQ = {'subject':'math','grade':7,'difficulty':'medium','type':'single','count':1,'topic':'分数'}
ROW = {'subject':'math','grade':7,'difficulty':'medium','type':'single','title':'分数','left_md':'选择正确答案','tags':[], 'points':5,'parts':[{'id':'main','type':'single','stem':'','points':5,'choices':[{'id':'A','text':'一'},{'id':'B','text':'二'}],'answer':'A'}]}
CFG = {'base_url':'http://test/v1','api_key':'secret','model':'model','chat_path':'/chat/completions','enable_thinking':'0','reasoning_effort':'none'}
SOURCE = {'path':'docs/standards/math.md','pages':[2],'stage':'义务教育','text':'## PDF 第 2 页\n分数的意义'}

class GenerationTests(unittest.TestCase):
    def test_lookup_routing_and_missing(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            root = Path(d)
            folder = root / 'docs/standards/义务教育-2022'
            folder.mkdir(parents=True)
            (folder / '04-义务教育数学课程标准.md').write_text('## PDF 第 1 页\n其他内容\n## PDF 第 2 页\n初中部分\n理解分数的意义', encoding='utf8')
            got = lookup('math', 7, '分数', root)
            self.assertEqual(got['pages'], [2])
            self.assertIn('理解分数', got['text'])
            self.assertEqual(lookup('math', 7, '分数，贴近生活', root)['pages'], [2])
            (folder / '04-义务教育数学课程标准.md').write_text('## PDF 第 2 页\n初中部分\n理解分数。\n## PDF 第 4 页\n第四学段\n内容要求\n基本内容需要理解和掌握课程范围并能够在实践生活当中灵活运用这些知识和方法。\n## PDF 第 6 页\n第四学段\n学业质量\n质量要求包括基本知识技能和核心素养并在具体任务中表现出来，通过多种实际情境体现学生的学习成就。', encoding='utf8')
            context = lookup('math', 7, '分数，贴近生活', root)
            self.assertEqual(context['pages'], [2, 6])
            self.assertEqual(context['overview_missing'], ['内容要求'])
            self.assertIn('PDF 第 6 页', context['text'])
            with self.assertRaises(CurriculumError): lookup('math', 7, '函数', root)
            (folder / '04-义务教育数学课程标准.md').write_text('## PDF 第 1 页\n目录……一次函数……10\n## PDF 第 8 页\n初中部分\n探索一次函数的图像与性质。', encoding='utf8')
            got = lookup('math', 8, '一次函数的图像与性质，已学过正比例函数；贴近生活，避免复杂计算。', root)
            self.assertEqual(got['pages'][0], 8)
            with self.assertRaises(CurriculumError): lookup('math', 8, '分数加减，贴近生活，避免复杂计算。', root)
            with self.assertRaises(CurriculumError): lookup('physics', 3, '分数', root)
            with self.assertRaises(CurriculumError): lookup('math', 10, '分数', root)

    def test_real_math_stage_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(lookup('math', 5, '分数，贴近生活', root)['pages'])
        self.assertTrue(lookup('math', 8, '一次函数', root)['pages'])
        with self.assertRaises(CurriculumError):
            lookup('math', 5, '一元一次方程', root)
        with self.assertRaises(CurriculumError):
            lookup('math', 1, '分数', root)

    def test_strict_validation(self):
        import copy
        self.assertEqual(validate({'items':[ROW]}, REQ)[0]['subject'], 'math')
        for change in ('metadata','answer','duplicate','points'):
            row = copy.deepcopy(ROW)
            if change == 'metadata': row['grade'] = 8
            if change == 'answer': row['parts'][0]['answer'] = 'C'
            if change == 'duplicate': row['parts'][0]['choices'][1]['id'] = 'A'
            if change == 'points': row['points'] = float('nan')
            with self.assertRaises(GenerationError): validate({'items':[row]}, REQ)
        row = copy.deepcopy(ROW)
        row['type'] = row['parts'][0]['type'] = 'blank'
        row['parts'][0]['answer'] = [r'$\frac{1}{2}$']
        with self.assertRaises(GenerationError): validate({'items':[row]}, {**REQ, 'type':'blank'})
        for answer in ('√(2)', '∫(x)dx'):
            row['parts'][0]['answer'] = [answer]
            self.assertEqual(validate({'items':[row]}, {**REQ, 'type':'blank'})[0]['parts'][0]['answer'], [answer])
        row = copy.deepcopy(ROW)
        row['type'] = 'passage'
        row['parts'][0]['stem'] = '回答'
        row['parts'][0]['type'] = 'short'
        row['parts'][0]['reference'] = '答案'
        row['parts'][0]['rubric'] = [{'id':'r1','points':3,'require':'说明'}]
        with self.assertRaises(GenerationError): validate({'items':[row]}, {**REQ, 'type':'passage'})

    @patch('app.services.generation.lookup', return_value=SOURCE)
    @patch('app.services.generation.llm_settings', return_value=CFG)
    @patch('app.services.generation._post_chat')
    def test_generation_and_http_failure(self, post, settings, lookup_mock):
        post.return_value = {'choices':[{'message':{'content':json.dumps({'items':[ROW]}, ensure_ascii=False)}}]}
        result = generate(REQ)
        self.assertEqual(result['sources'][0]['pages'], [2])
        self.assertIn('分数的意义', post.call_args.args[3][0]['content'])
        post.return_value = {'choices': [{'message': {'content': '{"error":"依据不足"}'}}]}
        with self.assertRaisesRegex(GenerationError, '所选年级'):
            generate(REQ)
        post.side_effect = httpx.ConnectError('secret raw detail')
        with self.assertRaises(GenerationError) as exc: generate(REQ)
        self.assertNotIn('secret', str(exc.exception))

    def test_http_chat_request(self):
        seen = []
        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({'items':[ROW]}, ensure_ascii=False)}}]})
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch('app.services.generation.lookup', return_value=SOURCE), patch('app.services.generation.llm_settings', return_value=CFG), patch('app.services.llm.httpx.Client', return_value=client):
            result = generate(REQ)
        self.assertEqual(result['items'][0]['grade'], 7)
        self.assertIn('分数的意义', seen[0]['messages'][0]['content'])
        self.assertEqual(seen[0]['model'], 'model')

    def test_save_duplicate_never_overwrites(self):
        from fastapi import HTTPException
        from app.api.parent import save_generated_item
        from app.schemas import GeneratedItemSaveIn
        slug = 'generated-' + 'a' * 32
        body = GeneratedItemSaveIn(**{**ROW, 'slug': slug})
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            target = Path(d) / (slug + '.yaml')
            target.write_text('existing', encoding='utf8')
            with patch('app.services.ingest.LOCAL_BANK_DIR', Path(d)), patch('app.services.ingest.ensure_dirs'), patch('app.api.parent.bank.items', {}):
                with self.assertRaises(HTTPException) as exc:
                    save_generated_item(body, User(role='parent', subjects_json='*'))
                self.assertEqual(exc.exception.status_code, 409)
                self.assertEqual(target.read_text(encoding='utf8'), 'existing')

    def test_routes_end_to_end(self):
        from fastapi import Request
        from fastapi.testclient import TestClient
        from starlette.middleware.sessions import SessionMiddleware
        from app.db import get_db
        from app.services.bank import item_from_dict
        import yaml
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key='test-only')
        app.include_router(router)
        users = {1: User(role='parent', subjects_json='math'), 2: User(role='student'), 3: User(role='parent', subjects_json='english')}
        class FakeDB:
            def get(self, model, ident): return users.get(ident)
        app.dependency_overrides[get_db] = lambda: FakeDB()
        @app.post('/test-login/{ident}')
        def login(ident: int, request: Request):
            request.session['user_id'] = ident
            return {'ok': True}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            directory = Path(d)
            def read_saved(slug):
                return item_from_dict(yaml.safe_load((directory / (slug + '.yaml')).read_text(encoding='utf8')), 'local')
            response_data = {'choices':[{'message':{'content':json.dumps({'items':[ROW]}, ensure_ascii=False)}}]}
            model_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_data)))
            with patch('app.services.generation.lookup', return_value=SOURCE), patch('app.services.generation.llm_settings', return_value=CFG), patch('app.services.llm.httpx.Client', return_value=model_client), patch('app.services.ingest.LOCAL_BANK_DIR', directory), patch('app.services.ingest.ensure_dirs'), patch('app.api.parent.bank.items', {}), patch('app.api.parent.bank.reload'), patch('app.api.parent.bank.get', side_effect=read_saved):
                with TestClient(app) as client:
                    self.assertEqual(client.post('/api/parent/items/generate', json=REQ).status_code, 401)
                    client.post('/test-login/2')
                    self.assertEqual(client.post('/api/parent/items/generate', json=REQ).status_code, 403)
                    client.post('/test-login/3')
                    self.assertEqual(client.post('/api/parent/items/generate', json=REQ).status_code, 403)
                    client.post('/test-login/1')
                    self.assertEqual(client.post('/api/parent/items/generate', json={**REQ, 'count': 6}).status_code, 422)
                    response = client.post('/api/parent/items/generate', json=REQ)
                    self.assertEqual(response.status_code, 200, response.text)
                    item = response.json()['items'][0]
                    self.assertEqual(list(directory.iterdir()), [])
                    saved = client.post('/api/parent/items/generated/save', json=item)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual(saved.json()['slug'], item['slug'])
                    self.assertEqual(client.post('/api/parent/items/generated/save', json=item).status_code, 409)

    def test_access(self):
        from fastapi import HTTPException
        from app.api.parent import generate_items
        from app.schemas import GenerateItemsIn
        from app.deps import get_admin_user
        with self.assertRaises(HTTPException) as exc:
            generate_items(GenerateItemsIn(**REQ), User(role='parent', subjects_json='english'))
        self.assertEqual(exc.exception.status_code, 403)
        with self.assertRaises(HTTPException) as exc:
            get_admin_user(User(role='student'))
        self.assertEqual(exc.exception.status_code, 403)

if __name__ == '__main__': unittest.main()
