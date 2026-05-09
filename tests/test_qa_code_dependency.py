import sys
import types
import unittest
import json
from types import SimpleNamespace


search_service_module = types.ModuleType("app.modules.search.service")
search_service_module.SearchService = object
sys.modules.setdefault("app.modules.search.service", search_service_module)

from app.modules.qa.service import QaService


class QaCodeDependencyTest(unittest.TestCase):
    def test_ex_fields_used_by_pc_question_routes_to_code_dependency(self):
        query = "EX 哪些字段在 PC 里面要用"

        self.assertEqual(QaService.extract_domain_codes(query), ["EX", "PC"])
        self.assertEqual(QaService.classify_query_intent(query), "domain_relation")

        result = QaService.build_code_dependency_answer(query)

        self.assertIsNotNone(result)
        answer, payload, sources = result
        self.assertEqual(payload["target_domain"], "PC")
        self.assertEqual(payload["used_domain"], "EX")
        self.assertIn("EXSTDTC", answer)
        self.assertIn("EXENDTC", answer)
        self.assertTrue(sources)

    def test_dependency_reason_followup_uses_previous_structured_answer(self):
        first = QaService.build_code_dependency_answer("EX 哪些字段在 PC 里面要用")
        answer, payload, sources = first
        history = [
            SimpleNamespace(role="user", content="EX 哪些字段在 PC 里面要用"),
            SimpleNamespace(
                role="assistant",
                content=answer,
                answer_type="domain_relation",
                answer_payload=json.dumps(payload, ensure_ascii=False),
                sources=json.dumps(sources, ensure_ascii=False),
            ),
        ]

        result = QaService.build_dependency_reason_followup_answer("为什么要读取这些字段", history)

        self.assertIsNotNone(result)
        followup_answer, followup_payload, followup_sources = result
        self.assertIn("PCRFTDTC", followup_answer)
        self.assertIn("USUBJID", followup_answer)
        self.assertIn("EXTPTNUM", followup_answer)
        self.assertEqual(followup_payload["applicable_stage"], "PC 域生成参考给药时间阶段")
        self.assertTrue(followup_sources)

    def test_pc_overall_logic_uses_code_index_not_relation_template(self):
        query = "PC 域整体逻辑是什么"

        self.assertEqual(QaService.classify_query_intent(query), "domain_logic")
        result = QaService.build_code_domain_logic_answer(query)

        self.assertIsNotNone(result)
        answer, payload, sources = result
        self.assertIn("药物浓度", answer)
        self.assertIn("df_ex", answer)
        self.assertIn("PCRFTDTC", answer)
        self.assertNotIn("作为给药时间基准域", answer)
        self.assertEqual(payload["domain_role"].startswith("PC 域用于生成药物浓度"), True)
        self.assertTrue(sources)


if __name__ == "__main__":
    unittest.main()
