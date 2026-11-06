from __future__ import annotations

import re
from pathlib import Path
from ..config import ROOT

# Files correspond to the official standards listed in docs/standards/README.md.
_FILES = {
 'politics': ('01-义务教育道德与法治', '5.普通高中思想政治'),
 'chinese': ('02-义务教育语文', '2.普通高中语文'),
 'history': ('03-义务教育历史', '6.普通高中历史'),
 'math': ('04-义务教育数学', '3.普通高中数学'),
 'english': ('05-义务教育英语', '4.普通高中英语'),
 'physics': ('10-义务教育物理', '8.普通高中物理'),
 'chemistry': ('11-义务教育化学', '9.普通高中化学'),
 'biology': ('12-义务教育生物学', '10.普通高中生物学'),
}

class CurriculumError(ValueError):
    pass

def _math_content_by_stage(pages: list[tuple[int, str]], grade: int) -> dict[int, str]:
    """Read explicit primary/junior and study-stage headings across pages."""
    target_part = '小学部分' if grade <= 6 else '初中部分'
    target_stage = 1 if grade <= 2 else 2 if grade <= 4 else 3 if grade <= 6 else 4
    part = None
    stage = None
    result = {}
    started = False
    for number, body in pages:
        if re.search(r'目\s*录', body[:200]) or len(re.findall(r'\.{3,}|…{2,}', body)) >= 3:
            continue
        selected = []
        for line in body.splitlines():
            compact = re.sub(r'\s+', '', line)
            if compact in {'小学部分', '初中部分'}:
                started = True
                part = compact
                stage = 4 if part == '初中部分' else None
            elif started and re.match(r'^五[、.]学业质量', compact):
                if selected:
                    result[number] = '\n'.join(selected)
                return result
            elif re.match(r'^[（(][一二三四][）)](?:数与代数|图形与几何|统计与概率|综合与实践)', compact):
                stage = 4 if part == '初中部分' else None
            match = re.match(r'^第([一二三四])学段(?:[（(]|$)', compact)
            if match and part == '小学部分':
                stage = '一二三四'.index(match[1]) + 1
            if part == target_part and stage == target_stage:
                selected.append(line)
        if selected:
            result[number] = '\n'.join(selected)
    return result


def lookup(subject: str, grade: int, topic: str, root: Path = ROOT) -> dict:
    if subject not in _FILES or not 1 <= grade <= 12:
        raise CurriculumError('科目或年级不正确')
    if grade <= 6 and subject in {'physics', 'chemistry', 'biology', 'history'}:
        raise CurriculumError('小学不单设该学科，不能直接使用初中课标出题')
    directory = '义务教育-2022' if grade <= 9 else '普通高中-2017-2020修订'
    folder = root / 'docs' / 'standards' / directory
    prefix = _FILES[subject][grade > 9]
    matches = sorted(folder.glob(prefix + '*.md')) if folder.is_dir() else []
    if len(matches) != 1:
        raise CurriculumError('对应课标文本缺失或不唯一，请检查课标资料库')
    path = matches[0]
    text = path.read_text(encoding='utf-8')
    chunks = re.split(r'^##\s*PDF\s*第\s*(\d+)\s*页\s*$', text, flags=re.M)
    if len(chunks) < 3:
        raise CurriculumError('课标文本缺少 PDF 页码，无法核实依据')
    pages = [(int(chunks[i]), chunks[i + 1].strip()) for i in range(1, len(chunks) - 1, 2)]
    math_scope = _math_content_by_stage(pages, grade) if subject == 'math' and grade <= 9 else None
    if math_scope is not None and not math_scope:
        raise CurriculumError('未定位到该年级对应的数学学段正文，请先核对课标文本')
    query = topic.strip()
    if not query:
        raise CurriculumError('请填写具体知识点')
    # Chinese requirements are often sentences rather than terms. Match substantive
    # contiguous n-grams, and require at least three matching Chinese characters
    # for sentence searches so generic single words do not create a false source.
    stop = {'题目', '出题', '学生', '年级', '学习', '已学', '过的', '需要', '要求', '知识', '内容',
            '生活', '贴近', '避免', '复杂', '计算', '基础', '理解', '掌握', '以及', '包括', '相关',
            '问题', '练习', '进行', '结合', '一个', '根据', '使用', '适合', '小学', '初中', '高中',
            '数学', '语文', '英语', '物理', '化学', '生物', '历史', '政治', '课程', '标准', '难度'}
    blocks = re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9]+', query.lower())
    candidates = set()
    for block in blocks:
        for size in range(2, min(6, len(block)) + 1):
            for offset in range(len(block) - size + 1):
                term = block[offset:offset + size]
                if term not in stop and not any(term.startswith(x) or term.endswith(x) for x in stop):
                    candidates.add(term)
    ranked = []
    overview = {'内容要求': [], '学业质量': []}
    stage_terms = (['第一学段', '1～2年级', '一、二年级'] if grade <= 2 else
                   ['第二学段', '3～4年级', '三、四年级'] if grade <= 4 else
                   ['第三学段', '5～6年级', '五、六年级'] if grade <= 6 else
                   ['第四学段', '7～9年级', '七至九年级'] if grade <= 9 else
                   ['普通高中', '必修', '选择性必修'])
    for number, original_body in pages:
        body = original_body
        is_toc = bool(re.search(r'目\s*录', body[:200]) or len(re.findall(r'\.{3,}|…{2,}', body)) >= 3)
        anchors = {
            '内容要求': r'^\s*(?:[【〖]\s*内容要求\s*[】〗]|[（(][一二三四五六七八九0-9]+[）)]\s*内容要求|内容要求)\s*$',
            '学业质量': r'^\s*(?:[（(][一二三四五六七八九0-9]+[）)]\s*学业质量(?:内涵|水平|要求)?|[一二三四五六七八九]+[、.]\s*学业质量(?:标准|要求)?|学业质量(?:内涵|水平|要求|标准)?)\s*$',
        }
        for heading, pattern in anchors.items():
            if not is_toc and len(re.sub(r'\s+', '', body)) >= 40 and re.search(pattern, body, re.M):
                stage_score = sum(term in body for term in stage_terms)
                overview[heading].append((stage_score, number, body))
        if math_scope is not None:
            body = math_scope.get(number, '')
        found = [term for term in candidates if term in body.lower()]
        longest = max((len(term) for term in found), default=0)
        minimum = 2 if len(query) <= 6 or any(len(block) == 2 and block not in stop and block in body for block in blocks) else 3
        if longest < minimum:
            continue
        score = longest * longest + min(sum(len(term) for term in found), 30)
        # Table-of-contents pages provide navigation rather than substantive text.
        if is_toc:
            score -= 30
        ranked.append((score, number, body))
    if not ranked:
        raise CurriculumError('对应学段未找到该知识点的课标原文，请核对年级或换用课标中的具体术语')
    ranked.sort(key=lambda x: (-x[0], x[1]))
    ranked = [row for row in ranked if row[0] > 0]
    if not ranked:
        raise CurriculumError('只找到目录，未找到可用的课标原文，请更换知识点')
    # Avoid sending identical extracted text twice.
    selected = []
    seen_text = set()
    for row in ranked:
        key = re.sub(r'\s+', '', row[2])
        if key not in seen_text:
            selected.append(row)
            seen_text.add(key)
        if len(selected) == 3:
            break
    missing = []
    for heading, choices in overview.items():
        if any(re.search(anchors[heading], row[2], re.M) for row in selected):
            continue
        # Topic-specific content requirements should never be replaced by an
        # unrelated chapter merely because its heading appears first.
        if heading == '内容要求':
            choices = [row for row in choices if any(term in row[2] for term in candidates if len(term) >= 3)]
        choices = [row for row in choices if re.sub(r'\s+', '', row[2]) not in seen_text]
        if choices:
            choices.sort(key=lambda x: (-x[0], x[1]))
            extra = choices[0]
            selected.append(extra)
            seen_text.add(re.sub(r'\s+', '', extra[2]))
        else:
            missing.append(heading)
    stage = '义务教育' if grade <= 9 else '普通高中'
    return {'path': path.relative_to(root).as_posix(), 'pages': [p for _, p, _ in selected],
            'stage': stage, 'overview_missing': missing, 'text': '\n\n'.join(f'## PDF 第 {p} 页\n{body}' for _, p, body in selected)}
