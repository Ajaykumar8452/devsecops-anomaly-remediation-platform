#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a /var/log/k3s-bootstrap.log) 2>&1
trap 'status=$?; echo "K3s bootstrap failed at line ${LINENO} (exit ${status})"; exit "$status"' ERR

echo "Starting pinned single-node K3s bootstrap at $(date --iso-8601=seconds)."
python3 /usr/local/sbin/install-k3s.py
python3 /usr/local/sbin/install-helm.py

echo "K3s version: $(/usr/local/bin/k3s --version | head -n 1)"
/usr/local/bin/k3s --version | grep -Fq 'v1.36.6+k3s1'
echo "kubectl version: $(/usr/local/bin/kubectl version --client --output=yaml | sed -n '1,4p')"
helm_version="$(/usr/local/bin/helm version --short)"
echo "Helm version: $helm_version"
[[ "$helm_version" == v4.3.1* ]]
systemctl is-active --quiet k3s.service
/usr/local/bin/kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml wait --for=condition=Ready nodes --all --timeout=60s
/usr/local/bin/kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml get nodes -o wide
/usr/local/bin/helm --kubeconfig /etc/rancher/k3s/k3s.yaml list --all-namespaces
echo "K3s service, Kubernetes node readiness, kubectl, and Helm verification passed at $(date --iso-8601=seconds)."
