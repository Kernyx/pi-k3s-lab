import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "prepare_host", Path(__file__).resolve().parents[1] / "scripts/prepare-host.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BootParametersTest(unittest.TestCase):
    def test_preserves_existing_parameters(self):
        original = "console=tty1 root=PARTUUID=example rootwait quiet"
        self.assertEqual(module.enable_memory(original),
                         original + " cgroup_memory=1 cgroup_enable=memory\n")

    def test_is_idempotent(self):
        once = module.enable_memory("rootwait\n")
        self.assertEqual(module.enable_memory(once), once)

    def test_existing_combined_controller_setting(self):
        original = "rootwait cgroup_memory=1 cgroup_enable=cpu,memory\n"
        self.assertEqual(module.enable_memory(original), original)

    def test_rejects_ambiguous_input(self):
        for original in ["", "\n", "rootwait\nquiet\n", "rootwait cgroup_memory=0",
                         "rootwait cgroup_disable=cpu,memory"]:
            with self.subTest(original=original), self.assertRaises(ValueError):
                module.enable_memory(original)

    def test_backup_and_second_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            boot = root / "cmdline.txt"
            backup = root / "rollback"
            original = b"rootwait quiet"
            boot.write_bytes(original)
            self.assertTrue(module.prepare(boot, backup))
            self.assertEqual((backup / "cmdline.txt").read_bytes(), original)
            self.assertFalse(module.prepare(boot, backup))
            self.assertEqual((backup / "cmdline.txt").read_bytes(), original)

    def test_refuses_to_overwrite_an_old_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            boot = root / "cmdline.txt"
            backup = root / "rollback"
            backup.mkdir()
            boot.write_text("rootwait quiet")
            (backup / "cmdline.txt").write_text("rootwait")
            with self.assertRaises(ValueError):
                module.prepare(boot, backup)
            self.assertEqual(boot.read_text(), "rootwait quiet")


if __name__ == "__main__":
    unittest.main()
