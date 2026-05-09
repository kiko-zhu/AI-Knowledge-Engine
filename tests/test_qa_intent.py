import unittest

from app.modules.qa.intent import extract_field_tokens, extract_target_domain_code


class QaIntentTest(unittest.TestCase):
    def test_extracts_field_token_before_chinese_suffix(self):
        query = "怎么计算VS域的VSTPT字段"

        self.assertEqual(extract_target_domain_code(query), "VS")
        self.assertEqual(extract_field_tokens(query), ["VSTPT"])

    def test_domain_code_is_not_treated_as_field_token(self):
        query = "如何计算EX域的EXSTDTC字段"

        self.assertEqual(extract_target_domain_code(query), "EX")
        self.assertEqual(extract_field_tokens(query), ["EXSTDTC"])

    def test_extracts_domain_when_field_comes_after_possessive(self):
        query = "VS域的VSORRESU怎么计算的"

        self.assertEqual(extract_target_domain_code(query), "VS")
        self.assertEqual(extract_field_tokens(query), ["VSORRESU"])

    def test_extracts_standalone_domain_code_without_chinese_suffix(self):
        query = "PC 的 PCLLOQ 怎么算"

        self.assertEqual(extract_target_domain_code(query), "PC")
        self.assertEqual(extract_field_tokens(query), ["PCLLOQ"])

    def test_dependency_domains_are_not_field_tokens(self):
        query = "EX 哪些字段在 PC 里面要用"

        self.assertEqual(extract_target_domain_code(query), "EX")
        self.assertEqual(extract_field_tokens(query), [])


if __name__ == "__main__":
    unittest.main()
