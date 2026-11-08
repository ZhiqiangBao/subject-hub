import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import ItemAnswer, Paper, PaperAttempt, User
from app.schemas import DraftIn, GradeIn
from app.api.parent import grade, get_answer, get_grade_job, retry_pending
from app.api.papers import paper_draft, _force_submit
from app.services.answers import grade_paper_attempts, score_context, paper_can_release_scores
from app.services.bank import Item, Part, bank
from app.services.review import review_paper
from app.services.snapshots import backfill_legacy_papers, freeze_paper, paper_item


def question(slug='q'):
    return Item(slug, '原题', 'math', 7, 'medium', 'single', ['旧标签'], 5, '原材料',
                [Part('main', 'single', '原问题', 5, choices=[{'id':'A','text':'甲'}, {'id':'B','text':'乙'}], answer='A', reference='依据', rubric=[{'id':'r','points':5,'require':'理由'}])], 'local')


class PaperSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.teacher = User(username='teacher', password_hash='x', role='admin', subjects_json='*')
        self.student = User(username='student', password_hash='x', role='student')
        self.db.add_all([self.teacher, self.student]); self.db.flush()
        self.paper = Paper(title='测验', subject='math', slugs_json='["q"]', created_by=self.teacher.id,
                           released_at=datetime.utcnow(), closes_at=datetime.utcnow()-timedelta(minutes=1))
        self.db.add(self.paper); self.db.flush()
        self.attempt = PaperAttempt(paper_id=self.paper.id, user_id=self.student.id, status='draft')
        self.db.add(self.attempt); self.db.flush()
        self.saved = bank.items
        bank.items = {'q': question()}

    def tearDown(self):
        bank.items = self.saved
        self.db.close()
        self.engine.dispose()

    def test_frozen_version_survives_bank_edit_and_removal(self):
        freeze_paper(self.paper)
        bank.items['q'] = question()
        bank.items['q'].parts[0].answer = 'B'
        bank.items['q'].parts[0].points = 999
        bank.items['q'].tags = ['新标签']
        bank.items['q'].left_md = '新材料'
        _force_submit(self.db, self.attempt, self.paper)
        row = self.db.query(ItemAnswer).one()
        row.value_json = '"A"'
        self.paper.grading_started_at = datetime.utcnow()
        grade_paper_attempts(self.db, self.paper)
        self.assertEqual(row.score, 5)
        self.assertEqual(score_context(self.db, self.student.id, 'paper', self.attempt.id, ['q'])['max_score'], 5)
        del bank.items['q']
        item = paper_item(self.paper, 'q')
        self.assertEqual((item.left_md, item.tags, item.parts[0].answer, item.parts[0].reference), ('原材料', ['旧标签'], 'A', '依据'))
        self.assertEqual(item.parts[0].rubric[0]['require'], '理由')
        review = review_paper(self.db, self.attempt.id)
        self.assertEqual(review['items'][0]['title'], '原题')
        self.assertEqual(review['items'][0]['max_score'], 5)

    def test_legacy_missing_is_never_fabricated(self):
        bank.items = {}
        backfill_legacy_papers(self.db)
        self.assertEqual(json.loads(self.paper.items_snapshot_json), {'q': None})
        bank.items['q'] = question()
        self.assertIsNone(paper_item(self.paper, 'q'))
        self.paper.grading_started_at = datetime.utcnow()
        self.assertFalse(paper_can_release_scores(self.db, self.paper))
        old = ItemAnswer(user_id=self.student.id, context_type='paper', context_id=self.attempt.id,
                         item_slug='q', part_id='main', status='graded', score=3, max_score=5)
        self.db.add(old); self.db.flush()
        totals = score_context(self.db, self.student.id, 'paper', self.attempt.id, ['q'])
        self.assertEqual((totals['score'], totals['max_score']), (3, 5))
        missing = review_paper(self.db, self.attempt.id)['items'][0]
        self.assertTrue(missing['missing'])
        self.assertEqual((missing['score'], missing['max_score']), (3, 5))

    def test_draft_cross_paper_rejected(self):
        freeze_paper(self.paper)
        self.paper.closes_at = datetime.utcnow() + timedelta(hours=1)
        bank.items['other'] = question('other')
        with self.assertRaises(HTTPException) as caught:
            paper_draft(self.attempt.id, 'other', DraftIn(parts={'main':'A'}), self.student, self.db)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.db.query(ItemAnswer).count(), 0)

    def test_migration_preserves_known_old_maximum(self):
        self.db.add(ItemAnswer(user_id=self.student.id, context_type="paper", context_id=self.attempt.id,
                               item_slug="q", part_id="main", status="graded", score=2, max_score=3))
        self.db.flush()
        backfill_legacy_papers(self.db)
        self.assertIsNone(paper_item(self.paper, "q"))
        freeze_paper(self.paper)
        self.assertIsNone(paper_item(self.paper, "q"))
        score = score_context(self.db, self.student.id, "paper", self.attempt.id, ["q"])
        self.assertEqual((score["score"], score["max_score"]), (2, 3))

    def test_manual_score_bounds_stage_and_regrade_type(self):
        freeze_paper(self.paper)
        _force_submit(self.db, self.attempt, self.paper)
        row = self.db.query(ItemAnswer).one()
        self.paper.grading_started_at = datetime.utcnow()
        for value in (-1, 6, 999, float('nan'), float('inf')):
            with self.assertRaises(HTTPException):
                grade(GradeIn(answer_id=row.id, score=value), self.teacher, self.db)
        with self.assertRaises(HTTPException):
            grade(GradeIn(answer_id=row.id, regrade=True), self.teacher, self.db)
        grade(GradeIn(answer_id=row.id, score=4), self.teacher, self.db)
        self.assertEqual(row.override_score, 4)
        self.paper.scores_released_at = datetime.utcnow()
        with self.assertRaises(HTTPException):
            grade(GradeIn(answer_id=row.id, score=2), self.teacher, self.db)
        self.assertEqual(row.override_score, 4)

    def test_manual_regrade_and_anonymous_job_status(self):
        item = bank.items['q']
        item.type = item.parts[0].type = 'short'
        freeze_paper(self.paper)
        _force_submit(self.db, self.attempt, self.paper)
        row = self.db.query(ItemAnswer).one()
        self.paper.grading_started_at = datetime.utcnow()
        self.db.commit()
        grade(GradeIn(answer_id=row.id, score=4, comment='人工'), self.teacher, self.db)
        row.score, row.llm_comment = 2, '旧参考'
        self.db.commit()
        response = grade(GradeIn(answer_id=row.id, regrade=True), self.teacher, self.db)
        self.assertEqual((response['score'], response['llm_score'], response['status'], response['job_state']),
                         (4, 2, 'overridden', 'queued'))
        status = get_grade_job(row.id, self.teacher, self.db)
        self.assertEqual((status['score'], status['llm_score'], status['job_state']), (4, 2, 'queued'))
        self.assertNotIn('student', status)
        other_teacher = User(username='other', password_hash='x', role='admin', subjects_json='chinese')
        with self.assertRaises(HTTPException) as forbidden:
            get_grade_job(row.id, other_teacher, self.db)
        self.assertEqual(forbidden.exception.status_code, 403)
        self.assertEqual(retry_pending(self.teacher, self.db)['count'], 0)
        with self.assertRaises(HTTPException):
            get_answer(row.id, self.teacher, self.db)
        grade(GradeIn(answer_id=row.id, score=3, comment='修改人工'), self.teacher, self.db)
        self.assertEqual(get_grade_job(row.id, self.teacher, self.db)['job_state'], 'cancelled')
        self.paper.scores_released_at = datetime.utcnow()
        self.db.commit()
        self.assertEqual(get_answer(row.id, self.teacher, self.db)['job_state'], 'cancelled')
        with self.assertRaises(HTTPException):
            grade(GradeIn(answer_id=row.id, regrade=True), self.teacher, self.db)
        with self.assertRaises(HTTPException):
            get_grade_job(row.id, self.teacher, self.db)

if __name__ == '__main__': unittest.main()
