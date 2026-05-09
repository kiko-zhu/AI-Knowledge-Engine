import unittest
import sys
import types
from unittest.mock import patch

search_service_module = types.ModuleType("app.modules.search.service")
search_service_module.SearchService = object
sys.modules.setdefault("app.modules.search.service", search_service_module)

from app.modules.qa.service import QaService


class QaExplanationTest(unittest.TestCase):
    def test_returns_tuple_when_model_call_fails(self):
        with patch("app.modules.qa.service.chat", side_effect=RuntimeError("llm unavailable")):
            answer, payload = QaService.build_explanation_answer("解释一下", [{"content": "测试片段"}])

        self.assertIsNone(answer)
        self.assertIsNone(payload)

    def test_returns_tuple_when_model_output_is_not_json(self):
        with patch("app.modules.qa.service.chat", return_value="不是 JSON"):
            answer, payload = QaService.build_explanation_answer("解释一下", [{"content": "测试片段"}])

        self.assertIsNone(answer)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
