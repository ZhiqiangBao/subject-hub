import unittest
from app.services.bank import Part
from app.services.blank import equivalent_blank
from app.services.grade import grade_objective

class BlankTests(unittest.TestCase):
    def test_numeric_representations_and_tolerance(self):
        part = Part('main', 'numeric', '', 5, answer=0.5)
        for answer in ('1/2', '50%', '０．５', '2/4'):
            self.assertEqual(grade_objective(part, answer, 'math'), 5)
        for answer in ('1/0', 'nan', 'inf', True, None):
            self.assertEqual(grade_objective(part, answer, 'math'), 0)
        part.answer = 1 / 3
        part.tolerance = 0.001
        self.assertEqual(grade_objective(part, '1/3', 'math'), 5)
        self.assertEqual(grade_objective(part, '0.33', 'math'), 0)
        part.answer = 1e100
        self.assertEqual(grade_objective(part, '1e100', 'physics'), 5)

    def assertMatch(self, got, expected, subject='math'):
        self.assertTrue(equivalent_blank(got, expected, subject), (got, expected))
    def assertDifferent(self, got, expected, subject='math'):
        self.assertFalse(equivalent_blank(got, expected, subject), (got, expected))

    def test_empty_and_zero(self):
        for value in (None, '', '  '):
            self.assertDifferent(value, [None, ''])
        self.assertMatch(0, ['0'])
        self.assertDifferent(None, [0])
        part = Part('main', 'blank', '', 5, answer=[None, ''])
        self.assertEqual(grade_objective(part, None, 'math'), 0)
        part.answer = [0]
        self.assertEqual(grade_objective(part, 0, 'math'), 5)

    def test_numbers_limited_to_science(self):
        self.assertMatch('0.5', ['1/2'])
        self.assertMatch('0001⁄0002', '0.5')
        self.assertMatch('1E3', '1000')
        self.assertMatch('50%', '0.5')
        self.assertMatch('2+50%', '2.5')
        self.assertDifferent('2+50%', '0.52')
        self.assertMatch('(2+50)%', '0.52')
        self.assertMatch('2*50%+1', '2')
        self.assertMatch('6.02*10^23', '6.02e23', 'physics')
        self.assertMatch('10^-23', '1e-23', 'chemistry')
        self.assertDifferent('10^31', '10^31')
        self.assertDifferent('5%2', '5%2')
        self.assertDifferent('50%%', '0.5')
        self.assertMatch('(1+1)%', '0.02')
        self.assertMatch('√(4)', '2')
        self.assertDifferent('√(2)', '1')
        self.assertDifferent('1%2', '0.01')
        self.assertDifferent('1e1000', '1e1000')
        self.assertDifferent('50%', '0.5', 'english')
        self.assertMatch('（１＋２）÷６', '0.5', 'physics')
        self.assertMatch('2×3−1', '5')
        self.assertDifferent('1', '01', 'english')
        self.assertDifferent('1/(2+1)', '1/2+1')
        self.assertDifferent('1/0', '1/0')
        self.assertDifferent('9^100', '9^100')
        self.assertDifferent('1'*300, '1'*300)
        self.assertDifferent('__import__("os").system("whoami")', '1')

    def test_machine_grading_receives_subject(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from app.services.answers import machine_grade_row
        from app.services.bank import item_from_dict
        row = SimpleNamespace(part_id='main', value_json='"0.5"', photo_paths_json='[]')
        item = item_from_dict({'slug':'test', 'subject':'math', 'grade':7, 'type':'blank', 'stem':'题', 'answer':['1/2'], 'points':5}, 'local')
        with patch('app.services.answers._photos', return_value=[]), patch('app.services.answers.apply_llm_score') as apply:
            machine_grade_row(row, item)
            apply.assert_called_once_with(row, 5)
            item.subject = 'english'
            apply.reset_mock()
            machine_grade_row(row, item)
            apply.assert_called_once_with(row, 0)

    def test_symbol_scope_and_case(self):
        self.assertMatch('x²', 'x^(2)')
        self.assertMatch('√(2)', 'sqrt(2)')
        self.assertDifferent('√(2+1)', '√(2)+1')
        self.assertMatch('H₂O', 'H2O', 'chemistry')
        self.assertDifferent('H²O', 'H₂O', 'chemistry')
        self.assertDifferent('Co', 'CO', 'chemistry')
        self.assertDifferent('A', 'a')
        self.assertDifferent('a part', 'apart', 'english')
        self.assertMatch('a   part', 'a part', 'english')
        self.assertMatch('don’t', "don't", 'english')
        self.assertMatch('students’', "students'", 'english')
        self.assertDifferent('dont', "don't", 'english')
        self.assertDifferent('it’s', 'its', 'english')
        self.assertMatch('A ⟶ B', 'A→B', 'chemistry')

if __name__ == '__main__': unittest.main()
