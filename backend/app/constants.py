from __future__ import annotations

SUBJECTS: dict[str, str] = {
    "chinese": "语文",
    "english": "英语",
    "math": "数学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "history": "历史",
    "politics": "政治",
}

DIFFICULTIES: dict[str, str] = {
    "easy": "容易",
    "medium": "中等",
    "hard": "较难",
}

TYPES: dict[str, str] = {
    "single": "单选",
    "multiple": "多选",
    "blank": "填空",
    "numeric": "数值",
    "short": "简答",
    "essay": "作文",
    "passage": "材料阅读",
    "steps": "过程题",
}

OBJECTIVE_TYPES = {"single", "multiple", "blank", "numeric"}
SUBJECTIVE_TYPES = {"short", "essay"}
CONTAINER_TYPES = {"passage", "steps"}

GRADE_LABELS = {
    1: "一年级",
    2: "二年级",
    3: "三年级",
    4: "四年级",
    5: "五年级",
    6: "六年级",
    7: "七年级",
    8: "八年级",
    9: "九年级",
    10: "高一",
    11: "高二",
    12: "高三",
}

CHALLENGE_SIZE = 20
DEFAULT_POINTS = {
    "single": 5,
    "multiple": 6,
    "blank": 5,
    "numeric": 5,
    "short": 8,
    "essay": 20,
    "passage": 10,
    "steps": 10,
}


def grade_label(grade: int | None) -> str:
    if not grade:
        return "未选年级"
    return GRADE_LABELS.get(int(grade), f"{grade}年级")


PAPER_SECTIONS: list[dict[str, object]] = [
    {
        "id": "choice",
        "name": "选择题",
        "types": ["single", "multiple"],
        "heading": "选择题（本题共{count}小题，每小题{points}分）",
    },
    {
        "id": "blank",
        "name": "填空题",
        "types": ["blank"],
        "heading": "填空题（本题共{count}小题，每小题{points}分）",
    },
    {
        "id": "numeric",
        "name": "计算题",
        "types": ["numeric"],
        "heading": "计算题（本题共{count}小题，每小题{points}分）",
    },
    {
        "id": "subjective",
        "name": "主观题",
        "types": ["short", "essay"],
        "heading": "主观题（本题共{count}小题，每小题{points}分）",
    },
    {
        "id": "passage",
        "name": "材料题",
        "types": ["passage"],
        "heading": "材料题（本题共{count}小题，每小题{points}分）",
    },
    {
        "id": "steps",
        "name": "过程题",
        "types": ["steps"],
        "heading": "过程题（本题共{count}小题，每小题{points}分）",
    },
]
