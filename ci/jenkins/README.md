# Jenkins CI controller and application pipeline

The Terraform dev environment defines a Jenkins controller host restricted by
an administrator CIDR and a
root-level [`Jenkinsfile`](../../Jenkinsfile). The pipeline checks out `dev`,
runs the Python test suite in a Python 3.13 container, scans the filesystem and
both built images with pinned Trivy `0.74.0`, builds the backend and dashboard,
then pushes full-commit-SHA tags to Docker Hub. It does not deploy to Kubernetes
or run Terraform.

## Jenkins security and administration

The Jenkins security group permits SSH (TCP 22) and the UI (TCP 8080) only
from the configured `admin_cidr`. Set it to the administrator's current public
IPv4 `/32` before applying. The explicitly supported `0.0.0.0/0` academic
override exposes both ports to every IPv4 address and is unsafe for normal
operation. This design does not attach an SSM role or use Session Manager.

Connect from the trusted administrator workstation using the existing local
private key, then browse to `http://<JENKINS_PUBLIC_IP>:8080`:

```sh
ssh -i <path-to-local-kp251026-private-key> ubuntu@<jenkins_public_ip>
```

Complete the first-login wizard. If the initial password is required, retrieve
it only in the authorized SSH session:

```sh
sudo cat /var/lib/jenkins/secrets/initialAdminPassword
```

Do not put this password in Terraform output, user data, logs, or Git. Install
the suggested plugins and ensure the Git, Pipeline, and Credentials Binding
plugins are available.

> **Docker privilege:** The bootstrap adds the `jenkins` service account to
> the `docker` group so jobs can build and scan images. Membership in this group
> grants effectively root-level control of the Jenkins host. This is an
> isolated academic lab design; do not reuse it for a shared production Jenkins
> controller without a separately reviewed isolated build architecture.

## Jenkins credentials

Add credentials in **Manage Jenkins → Credentials → System → Global credentials**:

| ID | Kind | Value |
|---|---|---|
| `dockerhub-token` | Username with password | Docker Hub username; password is a Docker Hub access token with permission to push to `ajaykumar8452/devsecops-platform`. |
| `github-readonly` | Username/password or supported Git credential | Read-only access to the private GitHub repository, if required by the SCM checkout. |

Never place either credential in the Jenkinsfile, Terraform, cloud-init, or
repository files. Configure `github-readonly` in the job's SCM settings when
GitHub requires authentication. The Docker token is consumed through Jenkins
Credentials Binding and passed to `docker login --password-stdin` without
printing it.

## Create the application Pipeline job

Create a Jenkins **Pipeline** job and configure:

1. Definition: **Pipeline script from SCM**.
2. SCM: Git; repository URL:
   `https://github.com/Ajaykumar8452/devsecops-anomaly-remediation-platform.git`.
3. Credentials: `github-readonly` when required by the private repository.
4. Branch specifier: `*/dev`.
5. Script Path: `Jenkinsfile`.
6. Enable periodic SCM polling every five minutes. The Jenkinsfile also declares
   `H/5 * * * *`; do not expose a public webhook endpoint for this lab.

Run the first build manually and inspect its test/scan/build stages. After a
successful push, verify these immutable tags in Docker Hub:

```text
ajaykumar8452/devsecops-platform:backend-<full-40-character-git-sha>
ajaykumar8452/devsecops-platform:dashboard-<full-40-character-git-sha>
```

The full commit SHA prevents a later pipeline from overwriting an earlier
commit's tag by convention. Before the first push, enable Docker Hub tag
immutability for this repository and configure rules matching
`^backend-[0-9a-f]{40}$` and `^dashboard-[0-9a-f]{40}$`. Docker Hub tags are
otherwise mutable by default, so commit-specific names alone do not enforce
immutability. Verify that this feature is available for the account and that
the push credential is permitted to publish under the policy. The Jenkins
pipeline intentionally has no Kubernetes deployment stage. Deployment and
namespace-scoped Kubernetes credentials require a later approved phase.
