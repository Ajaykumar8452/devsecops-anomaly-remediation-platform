from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "files" / "install-k3s.py"
SPEC = importlib.util.spec_from_file_location("install_k3s", SCRIPT)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

VERSION = "v1.36.6+k3s1"
COMMIT = "fa45d6a5ad0c9b8fdf90cf6a2eeeafaccfb60709"
DIGEST = "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad"
PRIVATE_IP = "10.40.1.17"


def metadata() -> dict[str, str]:
    return {
        "k3s_version": VERSION,
        "installer_release_version": VERSION,
        "installer_commit_sha": COMMIT,
        "installer_sha256": DIGEST,
    }


class K3sBootstrapTests(unittest.TestCase):
    def test_metadata_accepts_pinned_version_commit_and_digest(self) -> None:
        self.assertEqual(tool.validate_metadata(metadata())["k3s_version"], VERSION)

    def test_metadata_rejects_version_not_tied_to_installer_release(self) -> None:
        invalid = metadata()
        invalid["installer_release_version"] = "v1.36.5+k3s1"
        with self.assertRaises(tool.InstallError):
            tool.validate_metadata(invalid)

    def test_metadata_rejects_malformed_integrity_values(self) -> None:
        for key, value in (("installer_commit_sha", "bad"), ("installer_sha256", "0" * 63)):
            invalid = metadata()
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(tool.InstallError):
                tool.validate_metadata(invalid)

    def test_config_contains_private_tls_san_and_root_volume_storage_path(self) -> None:
        rendered = tool.desired_k3s_config(PRIVATE_IP)
        self.assertIn(f"  - {PRIVATE_IP}\n", rendered)
        self.assertIn('write-kubeconfig-mode: "0600"', rendered)
        self.assertIn("secrets-encryption: true", rendered)
        self.assertIn("default-local-storage-path: /var/lib/rancher/k3s/storage", rendered)

    def test_config_rejects_public_or_invalid_tls_san(self) -> None:
        for address in ("8.8.8.8", "not-an-ip"):
            with self.subTest(address=address), self.assertRaises(tool.InstallError):
                tool.desired_k3s_config(address)

    def test_installer_url_requires_full_commit_sha(self) -> None:
        self.assertEqual(tool.installer_url(COMMIT), f"{tool.INSTALLER_BASE_URL}/{COMMIT}/install.sh")
        with self.assertRaises(tool.InstallError):
            tool.installer_url("short-sha")

    def test_node_readiness_waits_until_ready(self) -> None:
        ready = json.dumps({"items": [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}}]})
        result = mock.Mock(returncode=0, stdout=ready, stderr="")
        with (
            mock.patch.object(tool, "run_command", return_value=result),
            mock.patch.object(tool.time, "monotonic", side_effect=[0, 0, 1]),
        ):
            tool.wait_for_node_ready()


if __name__ == "__main__":
    unittest.main()
