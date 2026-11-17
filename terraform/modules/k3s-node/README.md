# Academic K3s EC2 module

This module creates one Ubuntu 24.04 AMD64 EC2 instance with an encrypted gp3
root volume. It does not create a separate EBS data volume. K3s local-path
storage and application state therefore reside on the root filesystem and are
lost when the instance is terminated unless backed up.

The instance references the existing AWS EC2 key pair `kp251026` in
`ap-south-1` through the dev root's `aws_key_pair` data source. Terraform does
not create, import, or modify that key pair and does not access the matching
private `kp251026.pem`, which remains on the administrator's computer. The
instance has no IAM role or instance profile. Public IPv4 and
outbound access are used for package/release downloads; SSH is limited to the
configured administrator `/32`, and API TCP 6443 is permitted only from the
Jenkins security group.

## Automatic cloud-init behavior

Cloud-init installs `ca-certificates`, `curl`, Python 3, and `tar`, then runs
`/usr/local/sbin/bootstrap-k3s.sh`. The bootstrap script logs to
`/var/log/k3s-bootstrap.log`; cloud-init also records output in
`/var/log/cloud-init-output.log`.

The K3s installer:

1. Reads the instance's private IPv4 using IMDSv2.
2. Writes a root-only K3s configuration with secrets encryption, kubeconfig
   mode `0600`, the private IPv4 TLS SAN, and local-path storage under
   `/var/lib/rancher/k3s/storage` on the encrypted root volume.
3. Downloads the pinned installer from its reviewed Git commit, checks its
   SHA-256, and installs the configured `v1.36.6+k3s1` release.
4. Enables and starts `k3s.service`, keeps the administrative kubeconfig
   root-owned with mode `0600`, and waits up to ten minutes for the node to
   become Ready.
5. Uses the kubectl command provided by K3s, with a root-owned wrapper only if
   the K3s installation did not place one on `PATH`.
6. Installs the official Helm `v4.3.1` Linux AMD64 binary from `get.helm.sh`
   after verifying its release SHA-256.

No administrative kubeconfig is copied to Jenkins. The security group allows
Jenkins-to-K3s API network traffic over the private VPC address, but the
existing Jenkinsfile has no deployment stage. A reviewed deployment identity
and credential-handling workflow are required before Jenkins can deploy.

After launch, verify:

```sh
sudo cloud-init status --long
sudo systemctl status k3s.service
sudo tail -n 200 /var/log/k3s-bootstrap.log
sudo /usr/local/bin/k3s --version
sudo /usr/local/bin/kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get nodes -o wide
sudo /usr/local/bin/helm version --short
```
