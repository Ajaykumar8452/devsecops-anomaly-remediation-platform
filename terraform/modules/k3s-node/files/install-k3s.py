#!/usr/bin/env python3
"""Install the reviewed K3s server and wait for its single node to become Ready."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

INSTALL_CONFIG = Path("/etc/k3s/install-config.json")
K3S_CONFIG = Path("/etc/rancher/k3s/config.yaml")
K3S_BINARY = Path("/usr/local/bin/k3s")
KUBECTL = Path("/usr/local/bin/kubectl")
KUBECONFIG = Path("/etc/rancher/k3s/k3s.yaml")
INSTALLER_BASE_URL = "https://raw.githubusercontent.com/k3s-io/k3s"
MAX_INSTALLER_BYTES = 2 * 1024 * 1024
INSTALLER_TEMP_DIR = Path("/run")
K3S_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+\+k3s\d+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
METADATA_TOKEN_URL = "http://169.254.169.254/latest/api/token"
METADATA_PRIVATE_IP_URL = "http://169.254.169.254/latest/meta-data/local-ipv4"
METADATA_TIMEOUT_SECONDS = 5
NODE_READY_TIMEOUT_SECONDS = 600
NODE_READY_POLL_SECONDS = 5


class InstallError(RuntimeError):
    """Raised when the pinned K3s installation cannot complete safely."""


def require_root() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise InstallError("K3s installation requires root privileges.")


def run_command(args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, env=env, shell=False, check=False)
    except OSError as exc:
        raise InstallError(f"Could not execute {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no command output"
        raise InstallError(f"Command {args[0]} failed ({result.returncode}): {detail}")
    return result


def validate_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise InstallError("K3s installation metadata must be a JSON object.")
    version = value.get("k3s_version")
    commit = value.get("installer_commit_sha")
    digest = value.get("installer_sha256")
    pinned_version = value.get("installer_release_version")
    if not isinstance(version, str) or not K3S_VERSION_PATTERN.fullmatch(version):
        raise InstallError("K3s version metadata is invalid.")
    if version != pinned_version:
        raise InstallError("K3s version does not match the integrity-pinned installer release.")
    if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
        raise InstallError("K3s installer commit must be a full lowercase commit SHA.")
    if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
        raise InstallError("K3s installer SHA-256 is invalid.")
    return {"k3s_version": version, "installer_commit_sha": commit, "installer_sha256": digest}


def load_metadata(path: Path = INSTALL_CONFIG) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise InstallError(f"Root-owned installation metadata is missing or unsafe: {path}.")
    try:
        metadata_stat = path.stat()
        if (os.name == "posix" and metadata_stat.st_uid != 0) or stat.S_IMODE(metadata_stat.st_mode) & 0o077:
            raise InstallError("Installation metadata must be root-owned and inaccessible to group/other users.")
        return validate_metadata(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Cannot read installation metadata: {exc}") from exc


def get_instance_private_ip() -> str:
    token_request = urllib.request.Request(
        METADATA_TOKEN_URL,
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    try:
        with urllib.request.urlopen(token_request, timeout=METADATA_TIMEOUT_SECONDS) as response:
            token = response.read(4096).decode("ascii").strip()
        if not token:
            raise InstallError("IMDSv2 returned an empty token.")
        ip_request = urllib.request.Request(
            METADATA_PRIVATE_IP_URL,
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(ip_request, timeout=METADATA_TIMEOUT_SECONDS) as response:
            address = response.read(128).decode("ascii").strip()
        parsed = ipaddress.ip_address(address)
        if not isinstance(parsed, ipaddress.IPv4Address) or not parsed.is_private:
            raise InstallError("EC2 metadata did not return a private IPv4 address.")
        return str(parsed)
    except InstallError:
        raise
    except Exception as exc:
        raise InstallError(f"Could not securely obtain the K3s private IPv4 address from IMDSv2: {exc}") from exc


def desired_k3s_config(private_ip: str) -> str:
    try:
        parsed = ipaddress.ip_address(private_ip)
    except ValueError as exc:
        raise InstallError("K3s TLS SAN must be the instance's private IPv4 address.") from exc
    if not isinstance(parsed, ipaddress.IPv4Address) or not parsed.is_private:
        raise InstallError("K3s TLS SAN must be the instance's private IPv4 address.")
    return (
        'write-kubeconfig-mode: "0600"\n'
        "secrets-encryption: true\n"
        "default-local-storage-path: /var/lib/rancher/k3s/storage\n"
        "tls-san:\n"
        f"  - {parsed}\n"
    )


def ensure_k3s_config(private_ip: str) -> None:
    desired = desired_k3s_config(private_ip).encode("utf-8")
    K3S_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if K3S_CONFIG.is_symlink():
        raise InstallError("K3s configuration path is a symlink; refusing to replace it.")
    if K3S_CONFIG.exists():
        current_stat = K3S_CONFIG.stat()
        if not stat.S_ISREG(current_stat.st_mode) or (os.name == "posix" and current_stat.st_uid != 0):
            raise InstallError("Existing K3s configuration must be a root-owned regular file.")
        if K3S_CONFIG.read_bytes() != desired or stat.S_IMODE(current_stat.st_mode) != 0o600:
            raise InstallError("Existing K3s configuration differs from the expected private-IP configuration.")
        return
    fd, temporary_name = tempfile.mkstemp(prefix=".k3s-config.", dir=K3S_CONFIG.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(desired)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_name, 0o600)
        if hasattr(os, "chown"):
            os.chown(temporary_name, 0, 0)
        os.link(temporary_name, K3S_CONFIG)
    except FileExistsError as exc:
        raise InstallError("K3s configuration appeared concurrently; refusing to overwrite it.") from exc
    except OSError as exc:
        raise InstallError(f"Could not safely create K3s configuration: {exc}") from exc
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def installer_url(commit_sha: str) -> str:
    if not COMMIT_PATTERN.fullmatch(commit_sha):
        raise InstallError("Installer source must be pinned to a full lowercase commit SHA.")
    return f"{INSTALLER_BASE_URL}/{commit_sha}/install.sh"


def download_installer(commit_sha: str, expected_sha256: str) -> Path:
    if not SHA256_PATTERN.fullmatch(expected_sha256):
        raise InstallError("Expected installer SHA-256 is invalid.")
    request = urllib.request.Request(installer_url(commit_sha), headers={"User-Agent": "academic-k3s-bootstrap"})
    temporary_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "raw.githubusercontent.com":
                raise InstallError("K3s installer redirected away from official HTTPS raw source.")
            content = response.read(MAX_INSTALLER_BYTES + 1)
        if len(content) > MAX_INSTALLER_BYTES or not content.startswith(b"#!/bin/sh"):
            raise InstallError("Downloaded K3s installer is invalid or exceeds the size limit.")
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise InstallError("K3s installer SHA-256 does not match the reviewed pin.")
        fd, name = tempfile.mkstemp(prefix="k3s-install-", suffix=".sh", dir=INSTALLER_TEMP_DIR)
        temporary_path = Path(name)
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), 0o600)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != expected_sha256:
            raise InstallError("Temporary K3s installer changed after verification.")
        return temporary_path
    except Exception as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if isinstance(exc, InstallError):
            raise
        raise InstallError(f"Could not download verified K3s installer: {exc}") from exc


def installed_version() -> str | None:
    if not K3S_BINARY.exists():
        return None
    result = run_command([str(K3S_BINARY), "--version"], check=False)
    match = re.search(r"\bk3s version (v\d+\.\d+\.\d+\+k3s\d+)\b", result.stdout + result.stderr)
    if result.returncode != 0 or not match:
        raise InstallError("Existing K3s installation has an unrecognized version; refusing to replace it.")
    return match.group(1)


def ensure_kubectl() -> None:
    if shutil.which("kubectl"):
        return
    wrapper = b"#!/bin/sh\nexec /usr/local/bin/k3s kubectl \"$@\"\n"
    KUBECTL.parent.mkdir(parents=True, exist_ok=True)
    if KUBECTL.exists() or KUBECTL.is_symlink():
        if KUBECTL.is_file() and KUBECTL.read_bytes() == wrapper:
            return
        raise InstallError("A non-K3s kubectl already exists at /usr/local/bin/kubectl; refusing to replace it.")
    fd, temporary_name = tempfile.mkstemp(prefix=".kubectl.", dir=KUBECTL.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(wrapper)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary_name, 0o755)
        if hasattr(os, "chown"):
            os.chown(temporary_name, 0, 0)
        os.link(temporary_name, KUBECTL)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def wait_for_node_ready() -> None:
    deadline = time.monotonic() + NODE_READY_TIMEOUT_SECONDS
    last_error = "Kubernetes API did not report a node."
    while time.monotonic() < deadline:
        result = run_command(
            [str(K3S_BINARY), "kubectl", "--kubeconfig", str(KUBECONFIG), "get", "nodes", "-o", "json"],
            check=False,
        )
        if result.returncode == 0:
            try:
                nodes = json.loads(result.stdout).get("items", [])
                if nodes and all(
                    any(condition.get("type") == "Ready" and condition.get("status") == "True"
                        for condition in node.get("status", {}).get("conditions", []))
                    for node in nodes
                ):
                    return
                last_error = "Kubernetes node has not reached Ready."
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                last_error = f"Kubernetes returned invalid node status: {exc}"
        else:
            last_error = result.stderr.strip() or result.stdout.strip() or last_error
        time.sleep(NODE_READY_POLL_SECONDS)
    raise InstallError(f"K3s did not become healthy within {NODE_READY_TIMEOUT_SECONDS} seconds: {last_error}")


def install() -> dict[str, str]:
    require_root()
    metadata = load_metadata()
    private_ip = get_instance_private_ip()
    ensure_k3s_config(private_ip)
    target_version = metadata["k3s_version"]
    current_version = installed_version()
    if current_version is not None and current_version != target_version:
        raise InstallError(f"Existing K3s {current_version} differs from pinned {target_version}; refusing upgrade/downgrade.")
    if current_version is None:
        installer = download_installer(metadata["installer_commit_sha"], metadata["installer_sha256"])
        environment = {key: value for key, value in os.environ.items() if not key.startswith("INSTALL_K3S_")}
        environment.update({"INSTALL_K3S_VERSION": target_version, "INSTALL_K3S_EXEC": "server"})
        try:
            result = run_command(["sh", str(installer)], env=environment, check=False)
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "installer failed"
                raise InstallError(f"Pinned K3s installer failed ({result.returncode}): {detail}")
        finally:
            installer.unlink(missing_ok=True)
    if not K3S_BINARY.is_file() or not KUBECONFIG.is_file():
        raise InstallError("K3s installer did not create the server binary and administrative kubeconfig.")
    kubeconfig_stat = KUBECONFIG.stat()
    if (os.name == "posix" and kubeconfig_stat.st_uid != 0) or stat.S_IMODE(kubeconfig_stat.st_mode) != 0o600:
        raise InstallError("K3s administrative kubeconfig must remain root-owned with mode 0600.")
    if run_command(["systemctl", "enable", "--now", "k3s.service"], check=False).returncode != 0:
        raise InstallError("Could not enable and start k3s.service.")
    if run_command(["systemctl", "is-active", "--quiet", "k3s.service"], check=False).returncode != 0:
        raise InstallError("k3s.service is not active after startup.")
    ensure_kubectl()
    wait_for_node_ready()
    return {"k3s_version": target_version, "private_ip": private_ip, "status": "ready"}


def main() -> int:
    try:
        print(json.dumps(install(), indent=2, sort_keys=True), flush=True)
        return 0
    except (InstallError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
