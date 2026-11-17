from __future__ import annotations

import hashlib
import importlib.util
import io
import tarfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "files" / "install-helm.py"
SPEC = importlib.util.spec_from_file_location("install_helm", SCRIPT)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class SyntheticBinary:
    def __init__(self, size: int, valid_elf: bool = True) -> None:
        self.size = size
        self.valid_elf = valid_elf

    def __len__(self) -> int:
        return self.size

    def startswith(self, prefix: bytes) -> bool:
        return self.valid_elf and prefix == b"\x7fELF"


class SyntheticReader:
    def __init__(self, content: SyntheticBinary) -> None:
        self.content = content

    def read(self, _limit: int) -> SyntheticBinary:
        return self.content


class SyntheticArchive:
    def __init__(self, members: list[tarfile.TarInfo], content: SyntheticBinary) -> None:
        self.members = members
        self.content = content

    def __enter__(self) -> SyntheticArchive:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getmembers(self) -> list[tarfile.TarInfo]:
        return self.members

    def extractfile(self, _member: tarfile.TarInfo) -> SyntheticReader:
        return SyntheticReader(self.content)


class FakeResponse:
    def __init__(self, url: str, content: bytes) -> None:
        self.url = url
        self.content = content

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _limit: int) -> bytes:
        return self.content


class HelmInstallerTests(unittest.TestCase):
    def _archive(self, name: str = "linux-amd64/helm", payload: bytes = b"\x7fELF academic test binary") -> bytes:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
        return output.getvalue()

    def _synthetic_extract(self, size: int, *, name: str = "linux-amd64/helm", valid_elf: bool = True):
        member = tarfile.TarInfo(name)
        member.size = size
        archive = SyntheticArchive([member], SyntheticBinary(size, valid_elf))
        with mock.patch.object(tool.tarfile, "open", return_value=archive):
            return tool.extract_helm(b"synthetic archive")

    def test_release_download_is_pinned_to_official_version_host_and_checksum(self) -> None:
        self.assertEqual(tool.HELM_VERSION, "v4.3.1")
        self.assertIn(tool.HELM_VERSION, tool.HELM_URL)
        self.assertEqual(tool.urllib.parse.urlparse(tool.HELM_URL).scheme, "https")
        self.assertEqual(tool.urllib.parse.urlparse(tool.HELM_URL).hostname, "get.helm.sh")
        self.assertEqual(
            tool.HELM_SHA256,
            "0403a88ae20913d11b10a2467b50087721fea7581736da6b9d3992f5357fe54b",
        )

    def test_official_archive_sha256_is_checked_before_extraction(self) -> None:
        payload = self._archive()
        digest = hashlib.sha256(payload).hexdigest()
        response = FakeResponse(tool.HELM_URL, payload)
        with (
            mock.patch.object(tool, "HELM_SHA256", digest),
            mock.patch.object(tool.urllib.request, "urlopen", return_value=response),
        ):
            self.assertEqual(tool.download_archive(), payload)

    def test_download_rejects_wrong_archive_sha256(self) -> None:
        payload = self._archive()
        response = FakeResponse(tool.HELM_URL, payload)
        with (
            mock.patch.object(tool, "HELM_SHA256", "0" * 64),
            mock.patch.object(tool.urllib.request, "urlopen", return_value=response),
            self.assertRaises(tool.HelmInstallError),
        ):
            tool.download_archive()

    def test_extracts_expected_amd64_binary(self) -> None:
        archive = self._archive()
        self.assertEqual(tool.extract_helm(archive), b"\x7fELF academic test binary")

    def test_accepts_official_63_24_mib_binary_with_100_mib_limit(self) -> None:
        official_size = 66_314_400
        self.assertEqual(tool.MAX_BINARY_SIZE, 100 * 1024 * 1024)
        extracted = self._synthetic_extract(official_size)
        self.assertEqual(len(extracted), official_size)

    def test_rejects_binary_over_100_mib_limit_without_large_allocation(self) -> None:
        with self.assertRaises(tool.HelmInstallError):
            self._synthetic_extract(tool.MAX_BINARY_SIZE + 1)

    def test_rejects_wrong_archive_path_and_duplicate_expected_entries(self) -> None:
        with self.assertRaises(tool.HelmInstallError):
            tool.extract_helm(self._archive("other/helm"))
        member_a = tarfile.TarInfo("linux-amd64/helm")
        member_b = tarfile.TarInfo("linux-amd64/helm")
        archive = SyntheticArchive([member_a, member_b], SyntheticBinary(10))
        with mock.patch.object(tool.tarfile, "open", return_value=archive):
            with self.assertRaises(tool.HelmInstallError):
                tool.extract_helm(b"synthetic archive")

    def test_rejects_non_regular_member_and_non_elf_binary(self) -> None:
        member = tarfile.TarInfo("linux-amd64/helm")
        member.type = tarfile.SYMTYPE
        member.linkname = "other"
        archive = SyntheticArchive([member], SyntheticBinary(10))
        with mock.patch.object(tool.tarfile, "open", return_value=archive):
            with self.assertRaises(tool.HelmInstallError):
                tool.extract_helm(b"synthetic archive")
        with self.assertRaises(tool.HelmInstallError):
            self._synthetic_extract(20, valid_elf=False)

    def test_atomic_install_retains_root_ownership_and_executable_mode(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("os.chmod(temp_name, 0o755)", source)
        self.assertIn("os.chown(temp_name, 0, 0)", source)
        self.assertIn("os.link(temp_name, HELM_PATH)", source)
        self.assertIn("mode != 0o755", source)

    def test_bootstrap_checks_k3s_and_helm_using_explicit_kubeconfig(self) -> None:
        bootstrap = SCRIPT.parents[0] / "bootstrap-k3s.sh"
        text = bootstrap.read_text(encoding="utf-8")
        kubeconfig = "/etc/rancher/k3s/k3s.yaml"
        self.assertIn("v1.36.6+k3s1", text)
        self.assertIn("v4.3.1", text)
        self.assertIn(f"kubectl --kubeconfig {kubeconfig} wait", text)
        self.assertIn(f"helm --kubeconfig {kubeconfig} list --all-namespaces", text)


if __name__ == "__main__":
    unittest.main()
