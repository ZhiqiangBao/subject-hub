from __future__ import annotations
import json
import math
import re
import uuid
from typing import Any
import httpx
from ..config import llm_settings
from ..constants import CONTAINER_TYPES, SUBJECTIVE_TYPES, TYPES
from .bank import bank
from .curriculum import lookup
from .ingest import item_from_editor
from .llm import _assistant_text, _auth_headers, _post_chat

class GenerationError(ValueError):
    pass

def _positive(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

def _validate_part(part: Any) -> None:
    if not isinstance(part, dict) or part.get('type') not in TYPES or part['type'] in CONTAINER_TYPES:
        raise GenerationError('模型返回的小问题型无效')
    if not _positive(part.get('points')):
        raise GenerationError('模型返回的分值无效')
    t = part['type']
    if t in {'single', 'multiple'}:
        choices = part.get('choices')
        if not isinstance(choices, list) or len(choices) < 2 or any(not isinstance(c, dict) or not isinstance(c.get('id'), str) or not c['id'].strip() or not isinstance(c.get('text'), str) or not c['text'].strip() for c in choices):
            raise GenerationError('模型返回的选项不完整')
        ids = [c['id'] for c in choices]
        texts = [c['text'].strip() for c in choices]
        if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
            raise GenerationError('模型返回的选项不唯一')
        a = part.get('answer')
        if t == 'single':
            valid = isinstance(a, str) and a in ids
        else:
            valid = isinstance(a, list) and bool(a) and all(isinstance(x, str) and x in ids for x in a) and len(set(a)) == len(a)
        if not valid:
            raise GenerationError('模型返回的正确选项无效')
    elif t == 'blank':
        a = part.get('answer')
        if not isinstance(a, list) or not a or any(not isinstance(x, str) or not x.strip() for x in a):
            raise GenerationError('模型返回的填空答案无效')
        if any('$' in x or re.search(r'\\[A-Za-z]+', x) for x in a):
            raise GenerationError('填空答案须使用普通文本，不能使用 LaTeX')
    elif t == 'numeric':
        a = part.get('answer')
        if not isinstance(a, (int, float)) or isinstance(a, bool) or not math.isfinite(a):
            raise GenerationError('模型返回的数值答案无效')
        tol = part.get('tolerance', 0)
        if not isinstance(tol, (int, float)) or isinstance(tol, bool) or not math.isfinite(tol) or tol < 0:
            raise GenerationError('模型返回的误差范围无效')
    elif t in SUBJECTIVE_TYPES:
        rubric = part.get('rubric')
        if not isinstance(part.get('reference'), str) or not part['reference'].strip() or not isinstance(rubric, list) or not rubric:
            raise GenerationError('模型返回的参考答案或评分细则不完整')
        if any(not isinstance(r, dict) or not isinstance(r.get('id'), str) or not r['id'].strip() or not isinstance(r.get('require'), str) or not r['require'].strip() or not _positive(r.get('points')) for r in rubric):
            raise GenerationError('模型返回的评分细则无效')
        if len({r['id'] for r in rubric}) != len(rubric) or not math.isclose(sum(r['points'] for r in rubric), part['points'], abs_tol=1e-6):
            raise GenerationError('模型返回的评分细则与总分不符')

def validate(raw: Any, request: dict) -> list[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get('items'), list) or len(raw['items']) != request['count']:
        raise GenerationError('模型返回的题目数量不符')
    result = []
    for row in raw['items']:
        if not isinstance(row, dict) or any(row.get(k) != request[k] for k in ('subject', 'grade', 'difficulty', 'type')) or isinstance(row.get('grade'), bool):
            raise GenerationError('模型返回的科目、年级、难度或题型不符')
        if not isinstance(row.get('title'), str) or not row['title'].strip() or not isinstance(row.get('left_md'), str) or not row['left_md'].strip() or not _positive(row.get('points')):
            raise GenerationError('模型返回的题目或分值不完整')
        if not isinstance(row.get('tags', []), list) or any(not isinstance(t, str) for t in row.get('tags', [])):
            raise GenerationError('模型返回的标签无效')
        parts = row.get('parts')
        if not isinstance(parts, list) or not parts or (row['type'] not in CONTAINER_TYPES and len(parts) != 1):
            raise GenerationError('模型返回的小问数量无效')
        ids = []
        for part in parts:
            _validate_part(part)
            if not isinstance(part.get('id'), str) or not part['id'].strip():
                raise GenerationError('模型返回的小问编号无效')
            ids.append(part['id'])
            if row['type'] in CONTAINER_TYPES and (not isinstance(part.get('stem'), str) or not part['stem'].strip()):
                raise GenerationError('模型返回的小问题干为空')
            if row['type'] not in CONTAINER_TYPES and part['type'] != row['type']:
                raise GenerationError('模型返回的小问题型不符')
        if len(set(ids)) != len(ids) or not math.isclose(sum(p['points'] for p in parts), row['points'], abs_tol=1e-6):
            raise GenerationError('模型返回的小问编号或分值无效')
        slug = 'generated-' + uuid.uuid4().hex
        while slug in bank.items:
            slug = 'generated-' + uuid.uuid4().hex
        result.append(item_from_editor(slug, row['subject'], row['type'], row).editor())
    return result

def generate(request: dict) -> dict:
    source = lookup(request['subject'], request['grade'], request['topic'])
    cfg = llm_settings()
    if not cfg['base_url'] or not cfg['model']:
        raise GenerationError('请先在模型设置中配置模型')
    notice = '课标检索覆盖对应学段，所选页面可能含其他年级内容；课标不保证单一年级教材顺序，请结合已学进度审题。高中内容须区分必修和选择性必修。'
    if source.get('overview_missing'):
        notice += '未定位到独立标题的' + '、'.join(source['overview_missing']) + '页，请人工核对。'
    if request['subject'] == 'english' and request['grade'] <= 2:
        notice += '英语一、二年级是否开设由学校安排，不能据此推断为必修。'
    prompt = ('请根据给定课标原文出题，只输出严格 JSON 对象 {"items": [...]}。每项必须包含 '
              'subject, grade, difficulty, type, title, left_md, tags, points, parts。parts 每项含 id,type,stem,points；'
              '选择题含 choices（id,text）和 answer；填空 answer 为可接受写法数组；数值 answer 为数字；'
              '简答和作文含 reference 与 rubric（id,points,require）。材料题和过程题的小问有独立 stem；'
              '非材料题只有一个小问，题干在 left_md。分值为正，题目总分等于小问分值之和，评分细则分值等于小问分值。'
              '题目必须原创，并自检题目、答案和评分细则一致。填空答案只写普通文本，禁止 LaTeX 和美元符号；根号、积分用 √(...) 和 ∫(...)dx 括号明确表示范围。'
              '题干和选项不透露正确答案；参考答案和评分细则放在专用字段。tags使用课标中的知识点词，不填科目、年级、难度或题型。'
              '课标文本可能有 OCR 错误，遇到不清晰的公式不得自行补全或作为确定依据。'
              '如果知识点超出目标学段，或原文不能支持出题，请只返回 {"error":"依据不足"}，不要编造题目。'
              '只用给出的课标原文，尊重目标年级与用户描述的已学进度，页面中其他年级内容不可直接当作已学；高中区分必修和选择性必修，不声称该年级必学。\n请求：' + json.dumps(request, ensure_ascii=False) + '\n' + notice + '\n课标：\n' + source['text'])
    try:
        data = _post_chat(cfg['base_url'].rstrip('/') + cfg['chat_path'], _auth_headers(cfg['api_key']), cfg['model'],
            [{'role': 'user', 'content': prompt}], cfg['enable_thinking'] == '1', cfg['reasoning_effort'],
            temperature=0, max_tokens=8000, timeout=180, want_json=True)
        content = _assistant_text(data)
        parsed = json.loads(content)
    except httpx.TimeoutException:
        raise GenerationError('模型请求超时，请稍后重试') from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        raise GenerationError('模型请求失败或返回格式无效，请检查模型设置后重试') from None
    if isinstance(parsed, dict) and parsed.get('error'):
        raise GenerationError('该知识点暂不能按所选年级出题，请核对学段、已学进度或课标依据')
    items = validate(parsed, request)
    return {'items': items, 'sources': [{k: source[k] for k in ('path', 'pages', 'stage')}], 'notice': notice}
