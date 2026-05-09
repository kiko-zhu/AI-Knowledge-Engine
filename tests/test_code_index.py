import unittest

from app.modules.code_index.service import SendCodeIndexService


class SendCodeIndexTest(unittest.TestCase):
    def test_finds_pc_pclloq_assignment(self):
        result = SendCodeIndexService.find_field("PC", "PCLLOQ")

        self.assertIsNotNone(result)
        expression = result["entries"][0]["expression"]
        self.assertIn("df_tk_info", expression)
        self.assertIn("BLOQ", expression)
        self.assertIn("parse_pc_numeric_value", expression)

    def test_finds_ex_fields_used_by_pc(self):
        result = SendCodeIndexService.find_dependency("PC", "EX")

        self.assertIsNotNone(result)
        self.assertEqual(
            sorted(result["fields"].keys()),
            ["EXENDTC", "EXENDY", "EXSTDTC", "EXSTDY", "EXTPTNUM", "USUBJID"]
        )


if __name__ == "__main__":
    unittest.main()
