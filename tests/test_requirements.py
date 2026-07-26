import unittest
from pathlib import Path


class RequirementsTests(unittest.TestCase):
    def test_stdlib_modules_are_not_declared_as_pip_requirements(self):
        requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        declared = []

        for line in requirements_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            declared.append(stripped.split("#", 1)[0].strip().lower())

        invalid = [name for name in declared if name in {"sqlite3", "asyncio"}]
        self.assertEqual([], invalid, "stdlib modules should not be listed as pip requirements")


if __name__ == "__main__":
    unittest.main()
