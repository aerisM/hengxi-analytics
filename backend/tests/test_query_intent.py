import unittest

from app.security import AccessController
from app.workflows.query_intent import QueryIntentGuard


class QueryIntentGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scope = AccessController().resolve("demo_current_sales").public()

    def missing(self, query: str, operations: list[str] | None = None, metric: str = "") -> bool:
        return QueryIntentGuard.missing_ranking_metric(
            query,
            {"operations": operations or []},
            {"ranking_metric": metric} if metric else {},
            self.scope,
        )

    def test_unspecified_ranking_metric_is_entity_independent(self) -> None:
        self.assertTrue(self.missing("查询2026年8月表现最好的客户"))
        self.assertTrue(self.missing("找出表现最好的商品"))
        self.assertTrue(self.missing("列出前10名门店"))

    def test_explicit_schema_metric_or_confirmed_metric_passes(self) -> None:
        self.assertFalse(self.missing("按实付金额排名客户"))
        self.assertFalse(self.missing("订单数最多的客户"))
        self.assertFalse(self.missing("表现最好的客户", metric="销售额"))

    def test_model_ranking_operation_can_trigger_without_fixed_phrase(self) -> None:
        self.assertTrue(self.missing("最有价值的客户", ["ranking"]))
        self.assertFalse(self.missing("统计各地区销售额"))
        self.assertTrue(self.missing("表现最好的客户", metric="利润"))


if __name__ == "__main__":
    unittest.main()
