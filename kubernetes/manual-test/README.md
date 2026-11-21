# Manual K3s test overlay

This overlay deploys the FastAPI backend, Streamlit dashboard, Prometheus,
Grafana, their existing Services and PVCs, and the existing provisioning
ConfigMaps. It deliberately excludes all Ingress and Traefik Middleware
resources. Services remain `ClusterIP`; use SSH tunnels and `kubectl
port-forward` for browser access. No administrative application port is opened
publicly by these manifests.

## Image tags

The backend and dashboard Deployments and patches use the immutable image tags
reported as pulled into the K3s containerd store for commit
`bae2169bddf41426e2de7ea21ad8075bec4cb7dd`:

- `ajaykumar8452/devsecops-platform:backend-bae2169bddf41426e2de7ea21ad8075bec4cb7dd`
- `ajaykumar8452/devsecops-platform:dashboard-bae2169bddf41426e2de7ea21ad8075bec4cb7dd`

After each successful Jenkins build, update only the `image` value in the two
patches to the exact full image references printed by that build. The Docker
Hub repository is public, so these workloads do not need an image pull Secret.

## Secret prerequisite

Create the namespaces first, then create the Grafana admin Secret out of band.
Do not put Grafana passwords in manifests or command-line literal values.
Prepare protected files containing the Grafana admin username and password.
For PowerShell, for example:

```powershell
kubectl apply -f kubernetes/namespaces/platform.yaml -f kubernetes/namespaces/monitoring.yaml

kubectl create secret generic grafana-admin `
  --namespace monitoring `
  --from-file=admin-user="C:\secure\grafana\admin-user.txt" `
  --from-file=admin-password="C:\secure\grafana\admin-password.txt" `
  --dry-run=client -o yaml | kubectl apply -f -
```

Only the Grafana Secret is referenced by a workload. Backend, dashboard,
Prometheus, and Grafana images are public and do not require a pull Secret. This
overlay does not reference `dashboard-tls` or `grafana-tls`; keep those TLS
Secrets for a later Ingress deployment only.

## Storage and existing SQLite data

The backend PVC is mounted at `/app/data`, where
`ALERT_DATABASE_PATH=/app/data/alerts.db`. It requests 5 GiB from K3s
`local-path`; Prometheus and Grafana request separate 10 GiB and 2 GiB claims.
On the current single-node design, local-path data resides on the K3s root EBS
filesystem. PVC creation does not import the existing Docker volume or its
SQLite records. If existing alerts must be retained, restore the independently
verified SQLite backup into the backend PVC before allowing the backend
Deployment to start.

## Render and deploy

First verify the K3s Traefik Middleware CRD and the bundled storage class even
though this overlay does not install or expose Ingress:

```powershell
kubectl get nodes
kubectl get storageclass local-path
kubectl get crd middlewares.traefik.io
```

Render and inspect the manual-test resources before applying them:

```powershell
kubectl kustomize --load-restrictor LoadRestrictionsNone kubernetes/manual-test
kubectl kustomize --load-restrictor LoadRestrictionsNone kubernetes/manual-test | kubectl apply -f -
```

The load restrictor is needed because the existing dashboard JSON files and
Grafana dashboard-provider file are referenced outside this overlay directory.
Confirm the image patch values match the latest Jenkins output before the
apply command. Verify rollout and storage afterward:

```powershell
kubectl -n platform rollout status deployment/backend
kubectl -n platform rollout status deployment/dashboard
kubectl -n monitoring rollout status deployment/prometheus
kubectl -n monitoring rollout status deployment/grafana
kubectl -n platform get pods,services,pvc
kubectl -n monitoring get pods,services,pvc
```

## SSH-tunnel browser access

On the K3s host, run these in separate SSH sessions:

```sh
sudo kubectl -n platform port-forward --address 127.0.0.1 service/dashboard 8501:8501
sudo kubectl -n monitoring port-forward --address 127.0.0.1 service/grafana 3000:3000
```

From the administrator workstation, forward local ports to the K3s host's
loopback ports:

```sh
ssh -i <local-kp251026-private-key> -L 8501:127.0.0.1:8501 -L 3000:127.0.0.1:3000 ubuntu@<K3S_PUBLIC_IP>
```

Then browse to `http://localhost:8501` and `http://localhost:3000`. The
dashboard's backend URL remains the internal Service DNS name. Both the
dashboard's Grafana browser URL and Grafana's `GF_SERVER_ROOT_URL` are
configured as `http://localhost:3000/` for this tunnel-only test. No public DNS
or TLS Secret is needed for this overlay. Before using external Grafana ingress,
change both URLs to the real HTTPS Grafana hostname.
