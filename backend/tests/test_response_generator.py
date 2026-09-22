import unittest

from app.querying.models import SqlExecution
from app.querying.response_generator import ResponseGenerator


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, system: str, user: str) -> dict:
        self.calls += 1
        return {"valid": True, "title": "模型说明", "analysis": "由模型生成的说明"}


class ResponseGeneratorTest(unittest.TestCase):
    def test_simple_grouped_result_skips_model(self) -> None:
        model = CountingModel()
        execution = SqlExecution(
            sql='SELECT member_level AS "客户等级", SUM(paid_amount) AS "销售额" '
                'FROM orders GROUP BY member_level',
            success=True,
            columns=["客户等级", "销售额"],
            rows=[{"客户等级": "普通会员", "销售额": 580336.2900000002}],
        )

        result = ResponseGenerator(model).finalize(
            "按客户等级统计销售额", execution, "", ""
        )

        self.assertEqual(model.calls, 0)
        self.assertEqual(result["analysis"], "已按客户等级汇总销售额，返回1行结果。")
        self.assertNotIn("580336.2900000002", result["analysis"])

    def test_complex_result_still_uses_model(self) -> None:
        model = CountingModel()
        execution = SqlExecution(
            sql="SELECT region, amount FROM orders",
            success=True,
            columns=["region", "amount"],
            rows=[{"region": "华东", "amount": 12}],
        )

        result = ResponseGenerator(model).finalize("分析明细", execution, "", "")

        self.assertEqual(model.calls, 1)
        self.assertEqual(result["analysis"], "由模型生成的说明")


if __name__ == "__main__":
    unittest.main()
