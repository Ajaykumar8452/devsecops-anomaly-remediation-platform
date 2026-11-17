#!/usr/bin/env python3
"""Install the pinned official Helm binary after checking its release SHA-256."""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

HELM_VERSION = "v4.3.1"
HELM_SHA256 = "0403a88ae20913d11b10a2467b50087721fea7581736da6b9d3992f5357fe54b"
HELM_URL = f"https://get.helm.sh/helm-{HELM_VERSION}-linux-amd64.tar.gz"
HELM_PATH = Path("/usr/local/bin/helm")
MAX_ARCHIVE_SIZE = 30 * 1024 * 1024
MAX_BINARY_SIZE = 100 * 1024 * 1024


class HelmInstallError(RuntimeError):
    """Raised when official Helm installation or verification fails."""


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, capture_output=True, check=False, shell=False)
    except OSError as exc:
        raise HelmInstallError(f"Could not run {args[0]}: {exc}") from exc


def existing_version() -> str | None:
    if not HELM_PATH.exists():
        return None
    result = run([str(HELM_PATH), "version", "--short"])
    if result.returncode != 0:
        raise HelmInstallError("Existing Helm installation is not executable; refusing to replace it.")
    match = re.match(r"^(v\d+\.\d+\.\d+)", result.stdout.strip())
    if not match:
        raise HelmInstallError("Existing Helm installation reported an unknown version.")
    return match.group(1)


def download_archive() -> bytes:
    request = urllib.request.Request(HELM_URL, headers={"User-Agent": "academic-platform-helm-bootstrap"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "get.helm.sh":
                raise HelmInstallError("Helm download redirected away from the official get.helm.sh host.")
            content = response.read(MAX_ARCHIVE_SIZE + 1)
    except HelmInstallError:
        raise
    except Exception as exc:
        raise HelmInstallError(f"Could not download the pinned Helm release: {exc}") from exc
    if len(content) > MAX_ARCHIVE_SIZE:
        raise HelmInstallError("Helm release archive exceeds the size limit.")
    if hashlib.sha256(content).hexdigest() != HELM_SHA256:
        raise HelmInstallError("Helm release SHA-256 does not match the official pinned checksum.")
    return content


def extract_helm(content: bytes) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            matches = [member for member in archive.getmembers() if member.name == "linux-amd64/helm"]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > MAX_BINARY_SIZE:
                raise HelmInstallError("Official Helm archive does not contain exactly one expected Linux AMD64 binary.")
            file_obj = archive.extractfile(matches[0])
            if file_obj is None:
                raise HelmInstallError("Could not read the Helm binary from its verified archive.")
            binary = file_obj.read(MAX_BINARY_SIZE + 1)
    except HelmInstallError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise HelmInstallError(f"Could not safely read Helm archive: {exc}") from exc
    if not binary.startswith(b"\x7fELF") or len(binary) > MAX_BINARY_SIZE:
        raise HelmInstallError("Extracted Helm payload is not a valid-sized ELF binary.")
    return binary


def install() -> str:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise HelmInstallError("Helm installation requires root privileges.")
    current = existing_version()
    if current == HELM_VERSION:
        return current
    if current is not None:
        raise HelmInstallError(f"Existing Helm version {current} differs from pinned {HELM_VERSION}; refusing replacement.")

    content = extract_helm(download_archive())
    fd, temp_name = tempfile.mkstemp(prefix=".helm.", dir=HELM_PATH.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temp_name, 0o755)
        os.chown(temp_name, 0, 0)
        os.link(temp_name, HELM_PATH)
    except FileExistsError as exc:
        raise HelmInstallError("A Helm binary appeared concurrently; refusing to overwrite it.") from exc
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    installed = existing_version()
    if installed != HELM_VERSION:
        raise HelmInstallError("Installed Helm version failed post-install verification.")
    mode = stat.S_IMODE(HELM_PATH.stat().st_mode)
    if mode != 0o755 or HELM_PATH.stat().st_uid != 0:
        raise HelmInstallError("Installed Helm binary must be root-owned with mode 0755.")
    return installed


def main() -> int:
    try:
        print(f"Helm {install()} installed and verified.", flush=True)
        return 0
    except (HelmInstallError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
