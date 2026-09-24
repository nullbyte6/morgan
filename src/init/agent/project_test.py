import unittest
from pathlib import Path

from .project import _repository_root, discover_project


class ProjectInventoryTest(unittest.TestCase):
    def test_inventory_contains_only_files_from_discovered_repository(self):
        root = Path(__file__).resolve().parents[3]
        context = discover_project(str(root))
        repository_root = Path(context.repository_root)
        self.assertTrue(context.discovered_files)
        self.assertTrue(all(
            _repository_root((repository_root / path).parent) == repository_root
            for path in context.discovered_files
        ))


if __name__ == "__main__":
    unittest.main()
