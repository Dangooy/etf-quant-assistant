import unittest
from pathlib import Path


class InvariantTest(unittest.TestCase):

    def test_network_imports_stay_inside_fetcher(self):
        package_dir = Path(__file__).resolve().parents[1] / "quant_assistant"
        allowed = package_dir / "data" / "fetcher.py"
        forbidden_tokens = (
            "import akshare",
            "from akshare",
            "import requests",
            "from requests",
        )
        offenders = []
        for path in package_dir.rglob("*.py"):
            if path == allowed:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    offenders.append(f"{path.relative_to(package_dir.parent)}: {token}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
