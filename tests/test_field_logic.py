import unittest

from app.modules.qa.field_logic import build_field_logic_payload_from_contexts
from app.modules.qa.field_logic import has_substantive_field_logic


class FieldLogicTest(unittest.TestCase):
    def test_extracts_vsorresu_rules_from_markdown_context(self):
        contexts = [{
            "content": """
#### 2.3 测量结果与单位

**原始结果(VSORRES)**:
```python
VSORRES = f"%.2f" % float(item[test_name])
```

**原始单位(VSORRESU)**:
- 从 `df_terminology` 中获取对应测试的 `unit` 字段

**标准化结果(VSSTRESC/VSSTRESN/VSSTRESU)**:
- `VSSTRESU`: 标准化单位,与 `VSORRESU` 相同
"""
        }]

        payload = build_field_logic_payload_from_contexts("VSORRESU", contexts)

        self.assertTrue(has_substantive_field_logic(payload))
        self.assertEqual(payload["field_name"], "VSORRESU")
        self.assertIn("从 df_terminology 中获取对应测试的 unit 字段", payload["calculation_rules"])
        self.assertIn("从 df_terminology 中获取对应测试的 unit 字段", payload["dependencies"])
        self.assertIn("VSSTRESU: 标准化单位,与 VSORRESU 相同", payload["related_outputs"])


if __name__ == "__main__":
    unittest.main()
