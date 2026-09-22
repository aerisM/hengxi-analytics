from __future__ import annotations

import re
from typing import Any

from ..database import SCHEMA
from ..retrieval.service import SYNONYMS
from ..security import AccessScope


class QueryIntentGuard:
    """校验排名查询的必要业务口径，而非匹配特定查询对象。"""

    _ranking_cues = re.compile(r"排名|排行|最高|最低|最多|最少|最好|最佳|前\s*\d+|\btop\s*\d*|\brank(?:ing)?\b", re.I)

    @classmethod
    def missing_ranking_metric(
        cls,
        query: str,
        extraction: dict[str, Any],
        confirmed_parameters: dict[str, Any],
        access_scope: dict[str, Any],
    ) -> bool:
        operations = " ".join(str(item) for item in extraction.get("operations") or [])
        if not cls._ranking_cues.search(query) and not cls._ranking_cues.search(operations):
            return False
        scope = AccessScope.from_dict(access_scope)
        aliases = cls._metric_aliases(scope)
        supplied = str(confirmed_parameters.get("ranking_metric") or "").strip()
        return not cls._matches_metric(supplied or query, aliases)

    @staticmethod
    def _matches_metric(text: str, aliases: set[str]) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        return any(alias in normalized for alias in aliases)

    @staticmethod
    def _metric_aliases(scope: AccessScope) -> set[str]:
        aliases: set[str] = set()
        for table in SCHEMA:
            database = str(table.get("database") or "askdata_mock")
            if not scope.allows_table(database, str(table["id"])):
                continue
            for field in table.get("fields", []):
                names = [
                    str(field.get("label") or ""),
                    *(str(item) for item in field.get("aliases") or []),
                    *(str(item) for item in SYNONYMS.get(field.get("name"), [])),
                ]
                if field.get("role") == "metric":
                    aliases.update(name.lower() for name in names if len(name) >= 2)
                elif field.get("role") == "identifier":
                    aliases.update(
                        name.lower() for name in names
                        if len(name) >= 2 and any(marker in name for marker in ("数", "量", "笔"))
                    )
        return aliases
