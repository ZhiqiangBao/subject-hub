import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ItemAnswer, Paper, PaperAttempt
from app.services.bank import Item, Part
from app.services.answers import machine_grade_row
from app.services.grade_jobs import GradeJob, _claim, _restore_legacy_pending, _run_one, enqueue
from app.services import llm


class GradeJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.engine = create_engine('sqlite:///' + (Path(self.tmp.name) / 'jobs.db').as_posix())
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.item = Item(slug='q', title='题', subject='math', grade=7, difficulty='medium', type='short',
                         tags=[], points=5, left_md='原题', source='test',
                         parts=[Part(id='main', type='short', stem='问', points=5, reference='答案')])
        with self.sessions.begin() as db:
            db.add(Paper(id=1, title='卷', subject='math', slugs_json='["q"]', created_by=2,
                         grading_started_at=datetime.utcnow()))
            db.add(PaperAttempt(id=1, paper_id=1, user_id=1, status='submitted'))
            db.add(ItemAnswer(id=1, user_id=1, context_type='paper', context_id=1, item_slug='q',
                              part_id='main', status='pending', value_json='"原答案"', photos_json='[]', max_score=5,
                              submitted_at=datetime.utcnow()))

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def queue(self, retry=False):
        with self.sessions.begin() as db:
            return enqueue(db, db.get(ItemAnswer, 1), self.item, retry=retry)

    def test_commit_rollback_dedup_and_retry(self):
        with self.sessions() as db:
            self.assertTrue(enqueue(db, db.get(ItemAnswer, 1), self.item))
            with self.sessions() as reader:
                self.assertIsNone(reader.get(GradeJob, 1))
            db.rollback()
        self.assertFalse(_run_one(self.sessions))
        self.assertTrue(self.queue())
        self.assertFalse(self.queue())
        with self.sessions() as db:
            first = db.get(GradeJob, 1).generation
        self.assertTrue(self.queue(retry=True))
        with self.sessions() as db:
            self.assertNotEqual(first, db.get(GradeJob, 1).generation)

    def test_real_grading_entry_rolls_back_with_answer(self):
        with self.sessions() as db:
            row = db.get(ItemAnswer, 1)
            row.status = 'submitted'
            machine_grade_row(row, self.item)
            db.rollback()
        self.assertFalse(_run_one(self.sessions))
        with self.sessions() as db:
            self.assertIsNone(db.get(GradeJob, 1))

    def test_legacy_pending_backfill_uses_context_item_once(self):
        with patch('app.services.snapshots.context_item', return_value=self.item) as lookup:
            _restore_legacy_pending(self.sessions)
            _restore_legacy_pending(self.sessions)
            lookup.assert_called_once()
        with self.sessions() as db:
            self.assertEqual(json.loads(db.get(GradeJob, 1).item_json)['left_md'], '原题')

    def test_recover_and_frozen_input(self):
        self.queue()
        with self.sessions.begin() as db:
            job = db.get(GradeJob, 1)
            job.state = 'running'
            job.lease_until = datetime.utcnow() - timedelta(seconds=1)
        self.item.left_md = '题库已修改'
        def grade(item, part, text, photos):
            self.assertEqual(item.left_md, '原题')
            self.assertEqual(text, '原答案')
            return {'total': 4, 'comment': '好'}, '', False
        with patch.object(llm, 'grade_part_attempt', side_effect=grade):
            self.assertTrue(_run_one(self.sessions))
        with self.sessions() as db:
            self.assertEqual(db.get(ItemAnswer, 1).score, 4)
            self.assertEqual(db.get(GradeJob, 1).state, 'done')

    def test_stale_result_cannot_overwrite_new_answer_or_manual_override(self):
        for mode in ('new_answer', 'override', 'retry'):
            with self.subTest(mode=mode):
                with self.sessions.begin() as db:
                    row = db.get(ItemAnswer, 1)
                    row.status, row.value_json, row.score = 'pending', '"原答案"', None
                    row.override_score = row.override_by = None
                    row.override_comment = row.llm_comment = row.llm_json = None
                self.queue(retry=True)
                def grade(*args):
                    with self.sessions.begin() as db:
                        row = db.get(ItemAnswer, 1)
                        if mode == 'new_answer':
                            row.value_json = '"新答案"'
                        elif mode == 'override':
                            row.override_score, row.override_by, row.status = 2, 4, 'overridden'
                        else:
                            enqueue(db, row, self.item, retry=True)
                    return {'total': 5}, '', False
                with patch.object(llm, 'grade_part_attempt', side_effect=grade):
                    _run_one(self.sessions)
                with self.sessions() as db:
                    row = db.get(ItemAnswer, 1)
                    self.assertIsNone(row.score)
                    if mode == 'override':
                        self.assertEqual(row.override_score, 2)
                    if mode == 'retry':
                        self.assertEqual(db.get(GradeJob, 1).state, 'queued')

    def test_failure_remains_pending_and_can_retry(self):
        self.queue()
        with patch.object(llm, 'grade_part_attempt', return_value=(None, '无法看图', False)):
            _run_one(self.sessions)
        with self.sessions() as db:
            row = db.get(ItemAnswer, 1)
            self.assertEqual(row.status, 'pending')
            self.assertIn('无法看图', row.llm_comment)
            self.assertIsNone(row.score)
        self.assertTrue(self.queue(retry=True))

    def test_expired_worker_cannot_apply_after_another_claim(self):
        self.queue()
        def grade(*args):
            with self.sessions.begin() as db:
                db.get(GradeJob, 1).lease_until = datetime.utcnow() - timedelta(seconds=1)
            with self.sessions() as db:
                self.assertIsNotNone(_claim(db))
            return {'total': 5}, '', False
        with patch.object(llm, 'grade_part_attempt', side_effect=grade):
            _run_one(self.sessions)
        with self.sessions() as db:
            self.assertIsNone(db.get(ItemAnswer, 1).score)
            self.assertEqual(db.get(GradeJob, 1).state, 'running')

    def test_explicit_manual_regrade_updates_only_reference(self):
        with self.sessions.begin() as db:
            row = db.get(ItemAnswer, 1)
            row.status, row.override_score, row.override_comment, row.override_by = 'overridden', 3, '人工', 9
            row.score, row.llm_comment = 1, '旧模型评语'
            self.assertFalse(enqueue(db, row, self.item))
            self.assertTrue(enqueue(db, row, self.item, retry=True))
        with patch.object(llm, 'grade_part_attempt', return_value=({'total': 5, 'comment': '新模型评语'}, '', False)):
            _run_one(self.sessions)
        with self.sessions() as db:
            row = db.get(ItemAnswer, 1)
            self.assertEqual((row.score, row.llm_comment, row.override_score, row.override_comment, row.status),
                             (5, '新模型评语', 3, '人工', 'overridden'))
            self.assertEqual(db.get(GradeJob, 1).state, 'done')
        self.queue(retry=True)
        with patch.object(llm, 'grade_part_attempt', return_value=(None, '超时', True)):
            _run_one(self.sessions)
        with self.sessions() as db:
            row = db.get(ItemAnswer, 1)
            self.assertEqual((row.score, row.llm_comment, row.override_score, row.status),
                             (5, '新模型评语', 3, 'overridden'))
            self.assertEqual(db.get(GradeJob, 1).state, 'failed')

    def test_invalidated_jobs_skip_model_and_late_results(self):
        for when in ('before', 'during'):
            for change in ('release', 'manual', 'answer'):
                with self.subTest(when=when, change=change):
                    with self.sessions.begin() as db:
                        paper, row = db.get(Paper, 1), db.get(ItemAnswer, 1)
                        paper.scores_released_at = None
                        row.status, row.value_json, row.score = 'pending', '"原答案"', None
                        row.override_score = row.override_by = None
                        row.override_comment = row.llm_comment = row.llm_json = None
                    self.queue(retry=True)
                    def invalidate():
                        with self.sessions.begin() as db:
                            row = db.get(ItemAnswer, 1)
                            if change == 'release':
                                db.get(Paper, 1).scores_released_at = datetime.utcnow()
                            elif change == 'manual':
                                row.status, row.override_score = 'overridden', 2
                            else:
                                row.value_json = '"新作答"'
                    if when == 'before':
                        invalidate()
                    def grade(*args):
                        if when == 'during':
                            invalidate()
                        return {'total': 5}, '', False
                    with patch.object(llm, 'grade_part_attempt', side_effect=grade) as call:
                        _run_one(self.sessions)
                        self.assertEqual(call.call_count, 0 if when == 'before' else 1)
                    with self.sessions() as db:
                        self.assertIsNone(db.get(ItemAnswer, 1).score)
                        self.assertEqual(db.get(GradeJob, 1).state, 'cancelled')

    def test_rubric_results_require_valid_complete_consistent_scores(self):
        part = Part(id='p', type='short', stem='', points=5, reference='参考',
                    rubric=[{'id':'a', 'points':2, 'require':'甲'}, {'id':'b', 'points':3, 'require':'乙'}])
        valid = {'分项': [{'要点':'a', '分数':'2分'}, {'要点':'b', '分数': '1.5'}], '总分': '3.5', '评语':'好'}
        self.assertEqual(llm._coerce_grade(valid, part)['total'], 3.5)
        bad = [
            {'items': [{'id':'a', 'score':2}], 'total':2},
            {'items': [{'id':'a', 'score':2}, {'id':'x', 'score':1}], 'total':3},
            {'items': [{'id':'a', 'score':2}, {'id':'a', 'score':1}], 'total':3},
            {'items': [{'id':'a', 'score':3}, {'id':'b', 'score':1}], 'total':4},
            {'items': [{'id':'a', 'score':-1}, {'id':'b', 'score':1}], 'total':0},
            {'items': [{'id':'a', 'score':2}, {'id':'b', 'score':1}], 'total':2.99},
            {'items': [{'id':'a', 'score':float('nan')}, {'id':'b', 'score':1}], 'total':1},
            {'items': [{'id':'a', 'score':2}, {'id':'b', 'score':1}], 'total':float('inf')},
            {'total': 3},
        ]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(llm._coerce_grade(value, part))

    def test_invalid_model_json_never_becomes_a_score(self):
        self.item.parts[0].rubric = [{'id':'a', 'points':2, 'require':'甲'},
                                     {'id':'b', 'points':3, 'require':'乙'}]
        self.queue()
        cfg = {'base_url':'http://test', 'model':'mock', 'chat_path':'/chat/completions', 'api_key':''}
        response = {'choices': [{'message': {'content': json.dumps(
            {'items': [{'id':'a', 'score':2}, {'id':'b', 'score':1}], 'total': 4})}}]}
        with patch.object(llm, 'llm_settings', return_value=cfg), patch.object(llm, '_post_chat', return_value=response):
            _run_one(self.sessions)
        with self.sessions() as db:
            answer = db.get(ItemAnswer, 1)
            self.assertEqual(answer.status, 'pending')
            self.assertIsNone(answer.score)
            self.assertEqual(db.get(GradeJob, 1).state, 'failed')

    def test_photo_failure_never_falls_back_to_text(self):
        cfg = {'base_url':'http://test', 'model':'vision', 'chat_path':'/chat/completions', 'api_key':''}
        with patch.object(llm, 'llm_settings', return_value=cfg), patch.object(llm, '_post_chat') as post:
            result, error, _ = llm.grade_part_attempt(self.item, self.item.parts[0], '答案', ['missing.jpg'])
            self.assertIsNone(result)
            self.assertIn('图片', error)
            post.assert_not_called()
        with tempfile.TemporaryDirectory(dir=self.tmp.name) as d:
            (Path(d) / 'answer.jpg').write_bytes(b'photo')
            with patch.object(llm, 'UPLOAD_DIR', Path(d)), patch.object(llm, 'llm_settings', return_value=cfg), patch.object(llm, '_post_chat', side_effect=RuntimeError('unsupported images')) as post:
                result, _, _ = llm.grade_part_attempt(self.item, self.item.parts[0], '答案', ['answer.jpg'])
                self.assertIsNone(result)
                self.assertEqual(post.call_count, 1)
                self.assertIsInstance(post.call_args.args[3][1]['content'], list)
            for i in range(4):
                (Path(d) / f'{i}.jpg').write_bytes(b'photo')
            response = {'choices': [{'message': {'content': '{"total": 4, "comment": "好"}'}}]}
            with patch.object(llm, 'UPLOAD_DIR', Path(d)), patch.object(llm, 'llm_settings', return_value=cfg), patch.object(llm, '_post_chat', return_value=response) as post:
                result, _, _ = llm.grade_part_attempt(self.item, self.item.parts[0], '答案', [f'{i}.jpg' for i in range(4)])
                self.assertEqual(result['total'], 4)
                self.assertEqual(len(post.call_args.args[3][1]['content']), 5)


if __name__ == '__main__':
    unittest.main()
