"""Look up source pages: python scripts/lookup_standard.py SUBJECT GRADE TOPIC."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.curriculum import CurriculumError, lookup

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

parser = argparse.ArgumentParser(description='查找课标原文页，输出 JSON')
parser.add_argument('subject')
parser.add_argument('grade', type=int)
parser.add_argument('topic')
args = parser.parse_args()
try:
    print(json.dumps(lookup(args.subject, args.grade, args.topic), ensure_ascii=False, indent=2))
except CurriculumError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
