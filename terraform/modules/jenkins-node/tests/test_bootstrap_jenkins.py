from __future__ import annotations

import unittest
from pathlib import Path

TEMPLATE = Path(__file__).parents[1] / "files" / "cloud-init.yaml.tftpl"


def bootstrap_script() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    marker = "    content: |\n"
    body = text.split(marker, 1)[1].split("\nruncmd:", 1)[0]
    return "\n".join(line[6:] if line.startswith("      ") else line for line in body.splitlines())


class JenkinsBootstrapTests(unittest.TestCase):
    def test_explicit_java_git_jenkins_and_docker_packages_are_installed(self) -> None:
        script = bootstrap_script()
        for package in (
            "openjdk-21-jdk",
            "git",
            "jenkins",
            "docker-ce",
            "docker-ce-cli",
            "docker-buildx-plugin",
            "docker-compose-plugin",
        ):
            with self.subTest(package=package):
                self.assertIn(package, script)
        self.assertIn("https://pkg.jenkins.io/debian-stable", script)
        self.assertIn("https://download.docker.com/linux/ubuntu", script)

    def test_trivy_uses_the_pinned_official_release_and_checksums(self) -> None:
        script = bootstrap_script()
        self.assertIn("TRIVY_VERSION='0.74.0'", script)
        self.assertIn("trivy_$${TRIVY_VERSION}_Linux-64bit.deb", script)
        self.assertIn(
            "https://github.com/aquasecurity/trivy/releases/download/v$${TRIVY_VERSION}",
            script,
        )
        self.assertIn("trivy_$${TRIVY_VERSION}_checksums.txt", script)
        self.assertIn("cf1e32ec8d4d8823e023096a28cadb14f5b5123ce03f201fb633c5b76aa712dd", script)
        self.assertIn("bc701c3c3ee8b9acbea2c23257e41381e3854888f51281616a6ba5dc96963821", script)
        self.assertIn("dpkg-deb --field", script)
        self.assertNotIn("trivy=0.74.0", script)
        self.assertNotIn("trivy-repo/deb", script)

    def test_checksums_and_package_metadata_are_verified_before_apt_install(self) -> None:
        script = bootstrap_script()
        install_index = script.index("apt-get install -y")
        self.assertLess(script.index("TRIVY_CHECKSUMS_SHA256"), install_index)
        self.assertLess(script.index("sha256sum --check --status"), install_index)
        self.assertLess(script.index('"$TRIVY_DEB_PATH" Version'), install_index)
        self.assertLess(script.index('"$TRIVY_DEB_PATH" Architecture'), install_index)

    def test_exact_trivy_version_services_group_and_daemon_access_are_verified(self) -> None:
        script = bootstrap_script()
        for expected in (
            "java -version",
            'grep -Eq \'version "21',
            "git --version",
            "docker --version",
            "docker buildx version",
            "docker compose version",
            'grep -Fq "Version: $TRIVY_VERSION"',
            "systemctl is-active --quiet docker.service",
            "systemctl is-active --quiet jenkins.service",
            "id -nG jenkins",
            "systemctl restart jenkins.service",
            "runuser -u jenkins -- docker info",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, script)


if __name__ == "__main__":
    unittest.main()
