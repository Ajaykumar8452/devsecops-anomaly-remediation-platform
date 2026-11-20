from __future__ import annotations

import re
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).parents[1] / "files" / "cloud-init.yaml.tftpl"
JENKINSFILE = Path(__file__).parents[4] / "Jenkinsfile"


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

    def test_java_is_installed_and_verified_in_a_separate_apt_transaction(self) -> None:
        script = bootstrap_script()
        java_install = script.index(
            "DEBIAN_FRONTEND=noninteractive apt-get install -y openjdk-21-jdk"
        )
        java_verification = script.index("if ! grep -Eq")
        apt_install_starts = [
            match.start()
            for match in re.finditer(
                r"DEBIAN_FRONTEND=noninteractive apt-get install -y", script
            )
        ]
        self.assertEqual(len(apt_install_starts), 2)
        tools_install = apt_install_starts[1]
        java_install_block = script[java_install:java_verification]
        tools_install_block = script[tools_install:script.index("systemctl daemon-reload", tools_install)]

        self.assertLess(script.index("apt-get update"), java_install)
        self.assertLess(java_install, java_verification)
        self.assertLess(java_verification, tools_install)
        self.assertIn("update-alternatives --set java", java_install_block)
        self.assertIn("test -x", java_install_block)
        self.assertNotIn("jenkins", java_install_block)
        self.assertNotIn("openjdk-21-jdk", tools_install_block)
        self.assertIn("jenkins", tools_install_block)
        self.assertIn("docker-ce", tools_install_block)

    def test_jenkins_startup_occurs_after_java_and_tool_installation(self) -> None:
        script = bootstrap_script()
        java_verification = script.index("if ! grep -Eq")
        tools_install = script.index("jenkins \"$TRIVY_DEB_PATH\"")
        daemon_reload = script.index("systemctl daemon-reload")
        docker_start = script.index("systemctl enable --now docker.service")
        jenkins_enable = script.index("systemctl enable jenkins.service")
        jenkins_start = script.index("systemctl start jenkins.service")

        self.assertLess(java_verification, tools_install)
        self.assertLess(tools_install, daemon_reload)
        self.assertLess(daemon_reload, docker_start)
        self.assertLess(docker_start, jenkins_enable)
        self.assertLess(jenkins_enable, jenkins_start)
        self.assertIn("systemctl reset-failed jenkins.service", script)

    def test_trivy_uses_the_pinned_official_release_and_checksums(self) -> None:
        script = bootstrap_script()
        self.assertIn("TRIVY_VERSION='0.76.2'", script)
        self.assertIn("trivy_$${TRIVY_VERSION}_Linux-64bit.deb", script)
        self.assertIn(
            "https://github.com/aquasecurity/trivy/releases/download/v$${TRIVY_VERSION}",
            script,
        )
        self.assertIn("trivy_$${TRIVY_VERSION}_checksums.txt", script)
        self.assertIn(
            "7edaf64c8a2a0ae02137f776c6e56adf285fc36ec76b045274afdc462f20f092",
            script,
        )
        self.assertIn(
            "802e4ac1418ed967cd3c4b901f4f71ca00b7363ede67778665a22d9f13f58c83",
            script,
        )
        self.assertIn("dpkg-deb --field", script)
        self.assertNotIn("trivy-repo/deb", script)

    def test_host_trivy_version_matches_the_jenkins_pipeline_image(self) -> None:
        script = bootstrap_script()
        host_version = re.search(r"(?m)^\s*TRIVY_VERSION='([^']+)'", script)
        pipeline_version = re.search(
            r"(?m)^\s*TRIVY_IMAGE\s*=\s*'aquasec/trivy:([^']+)'",
            JENKINSFILE.read_text(encoding="utf-8"),
        )

        self.assertIsNotNone(host_version)
        self.assertIsNotNone(pipeline_version)
        self.assertEqual(host_version.group(1), pipeline_version.group(1))

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
