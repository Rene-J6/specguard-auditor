import importlib
import unittest


class AppImportTests(unittest.TestCase):
    def test_import_app_main_from_package_context(self):
        module = importlib.import_module("app.main")
        self.assertTrue(hasattr(module, "app"))


if __name__ == "__main__":
    unittest.main()
