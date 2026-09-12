import importlib
import unittest

from tests.acceptance_traceability import ACCEPTANCE_TRACEABILITY


def _iter_manifest_paths():
    seen = set()
    for entry in ACCEPTANCE_TRACEABILITY.values():
        for dotted in entry.get("tests", []):
            if dotted not in seen:
                seen.add(dotted)
                yield dotted


def resolve_dotted_test_path(dotted: str):
    module_name, class_name, method_name = dotted.rsplit(".", 2)
    module = importlib.import_module(module_name)
    test_class = getattr(module, class_name)
    return getattr(test_class, method_name)


class AcceptanceManifestTests(unittest.TestCase):
    def test_all_manifest_paths_resolve(self):
        paths = list(_iter_manifest_paths())
        self.assertTrue(paths, "ACCEPTANCE_TRACEABILITY has no test paths")
        unresolved = []
        for dotted in paths:
            try:
                resolve_dotted_test_path(dotted)
            except (ImportError, AttributeError) as exc:
                unresolved.append(f"{dotted}: {exc}")
        self.assertEqual([], unresolved, f"unresolvable manifest paths: {unresolved}")


if __name__ == "__main__":
    unittest.main()
