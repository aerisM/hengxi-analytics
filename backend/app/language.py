"""Response language policy, independent of model rewrites and schema language."""
from __future__ import annotations

import re
from typing import Literal

Language = Literal['zh', 'en']


def response_language(query: str) -> Language:
    # Ignore quoted data values/identifiers when determining the request language.
    prose = re.sub(r'`[^`]*`|"[^"]*"|“[^”]*”|\'[^\']*\'', '', query)
    overrides = list(re.finditer(
        r'(?:用|以)(英文|英语|中文|汉语)(?:回答|回复|解释|作答)|'
        r'\b(?:answer|respond|reply|explain)\s+in\s+(English|Chinese)\b', prose, re.I
    ))
    if overrides:
        name = next(value for value in overrides[-1].groups() if value).lower()
        return 'en' if name in {'英文', '英语', 'english'} else 'zh'
    if re.search(r'[\u4e00-\u9fff]', prose):
        return 'zh'
    return 'en' if re.search(r'[a-zA-Z]', prose) else 'zh'


def language_instruction(language: str) -> str:
    name = 'English' if language == 'en' else 'Simplified Chinese'
    return (
        f'\nResponse language: {name}. Write all user-facing prose, titles, explanations, '
        'clarification questions, option labels/descriptions, report text and chart titles '
        f'in {name}. Use {name} for newly generated SQL output aliases. '
        'Keep JSON keys, action names, option IDs, physical table/column names, existing '
        'result column references, data values and SQL filter literals unchanged. '
        'The schema or conversation history language must not override this policy.\n'
    )


def choose(language: str, chinese: str, english: str) -> str:
    return english if language == 'en' else chinese
