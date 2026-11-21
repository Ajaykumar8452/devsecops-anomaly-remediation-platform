# Kubernetes manifests (Phase 4A.1)

These manifests describe the existing FastAPI backend, Streamlit dashboard,
Prometheus, and Grafana on a single-node k3s cluster. They do not install k3s,
Traefik, or the bundled local-path provisioner, create AWS resources, or migrate
data. Keep one replica and one Uvicorn worker for the backend: its collector,
anomaly evaluator, health watchdog, and readiness monitor run as in-process
threads, and alert state is stored in SQLite.

## Before deployment

1. Select and pin an exact k3s release during Terraform/bootstrap design. These
   Middleware manifests use `apiVersion: traefik.io/v1alpha1`; use k3s 1.32 or
   newer, whose bundled Traefik is v3. Earlier k3s releases bundle Traefik v2
   and may expose the older CRD API group. The exact bundled Traefik chart and
   CRDs vary by k3s release; do not install a second ingress controller. See
   [k3s version-specific Traefik notes](https://docs.k3s.io/upgrades) and the
   [Traefik IP allowlist Middleware reference](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/ipallowlist/).
2. After k3s is installed, verify that its bundled Middleware CRD serves
   `traefik.io/v1alpha1` before applying these resources:

   ```sh
   kubectl get crd middlewares.traefik.io
   kubectl get crd middlewares.traefik.io -o jsonpath='{.spec.versions[?(@.name=="v1alpha1")].served}'
   ```

   The second command must print `true`. Also verify the bundled
   `local-path` StorageClass. Do not install duplicate Traefik or storage
   provisioner components.
3. The academic K3s host uses its encrypted gp3 root EBS volume for bundled
   local-path storage at `/var/lib/rancher/k3s/storage`; there is no separate
   K3s data volume. K3s cloud-init installs and starts the pinned server
   automatically. Back up the root volume and application data because
   `delete_on_termination = true` removes the local PVC data with the instance.
   See [storage/README.md](storage/README.md).
4. Jenkins publishes the backend and dashboard to the public Docker Hub
   repository `ajaykumar8452/devsecops-platform`, with tags
   `backend-<full-40-character-git-sha>` and
   `dashboard-<full-40-character-git-sha>`. The manual-test overlay keeps the
   two image references in separate patches; update those values from the
   successful Jenkins build output. Because the repository is public, the
   backend and dashboard do not require an `imagePullSecret`. This project does
   not create ECR repositories.
5. Configure external access before applying the Ingress resources:
   - Replace `dashboard.example.invalid` and `grafana.example.invalid` in the
     Ingress files with the real DNS names. Grafana's Ingress is optional and
     excluded from the default build.
   - Replace the loopback-only `127.0.0.1/32` source ranges in the allowlist
     Middleware files with the approved administrator CIDR. Keep the EC2
     security group restricted to the same approved sources.
   - Create the `dashboard-tls` Secret in `platform`; create `grafana-tls` in
     `monitoring` only if enabling Grafana Ingress. Supply TLS data out of band.
   - Set the browser-facing Grafana URL consistently in
     `application/dashboard/configmap.yaml` and
     `monitoring/grafana/configmap.yaml`. The dashboard's internal Grafana
     health URL remains the in-cluster Service URL.
   - Do not expose the Kubernetes API publicly.
6. Create the `grafana-admin` Secret in `monitoring` out of band, with keys
   `admin-user` and `admin-password`. Use secure local files or an approved
   secret manager. Do not commit Secret manifests or actual credentials.
7. Plan and review the SQLite import from the authoritative existing database.
   The Docker `alert_data` volume is not reused or copied automatically. Back up
   and integrity-check the source before a separately approved migration.

## Configuration and provisioning

Prometheus uses a Kubernetes-specific copy of the existing scrape configuration
at `monitoring/prometheus/prometheus.yml`, preserving the 15-second scrape
interval and 10-second timeout while targeting
`backend.platform.svc.cluster.local:8000`. Grafana datasource and dashboard
provider provisioning are generated from the existing files under
`monitoring/grafana/provisioning/`. The four existing dashboard JSON files are
referenced directly from `../monitoring/grafana/dashboards/` by the root
Kustomize generator, so they are not duplicated. Consequently, the offline
Kustomize build must allow those deliberate read-only references outside the
`kubernetes/` root:

Render and apply the manifests with this workflow, only after all pre-deployment
requirements above are complete and reviewed:

```sh
kubectl kustomize --load-restrictor LoadRestrictionsNone kubernetes | kubectl apply -f -
```

The load-restrictor is passed to `kubectl kustomize`, which renders the
Kustomization. Do not pass it directly to `kubectl apply -k`; `kubectl apply`
does not support that option. Prometheus and backend Services are ClusterIP
only. There is no Prometheus Ingress. The Grafana Ingress is optional and
excluded from the default Kustomize build. Both Ingress files reference the
namespace-qualified k3s Traefik Middleware allowlists. The default loopback-only
CIDR intentionally blocks remote access until replaced with the approved
administrator CIDR.

## Storage

The manifests request three independent `local-path` claims: 5 GiB for SQLite,
10 GiB for Prometheus TSDB, and 2 GiB for Grafana state. Configure the bundled
provisioner's backing path on the EBS filesystem before creating claims. Local
path storage is node-local and does not provide high availability. EBS and
SQLite backups remain necessary.

## Initial resource budget

The four manifests request a total of about 550m CPU and 1.375 GiB memory;
their limits total about 2.25 CPU and 3.5 GiB memory. These totals exclude
Traefik and Kubernetes system components. Values are starting estimates for the
2-vCPU, 8-GiB demonstration node; measure actual usage and reserve adequate
capacity for Ubuntu, k3s, CNI, and Traefik before deployment.

## Scope and known limitations

- `system_cpu_percent` and `system_memory_percent` are psutil operating-system
  views from inside the backend container. They are not Pod or Deployment
  metrics. Add Kubernetes-aware node/container collection separately if those
  views are required.
- The Streamlit `/_stcore/health` probe validates Streamlit availability but
  does not itself check the backend. The dashboard handles API failure in its
  UI; this probe does not guarantee backend connectivity.
- The backend readiness endpoint depends on SQLite and fresh internal threads.
  The readiness probe may initially fail while startup completes; the startup
  probe allows up to two minutes for the process to begin serving.
- PVCs use the pre-existing k3s `local-path` StorageClass. No StorageClass,
  provisioner, Traefik controller, Terraform, or Jenkins configuration is
  created here.
- Exact k3s/Traefik versions, ECR account/repository names, public DNS names,
  TLS issuance, the admin CIDR, EBS layout, and Grafana secret creation remain
  deployment prerequisites.

No Kubernetes operation, AWS provisioning, image runtime validation, database
migration, or Docker volume modification is part of this manifest-authoring
phase.

For the first tunnel-only deployment, use the ingress-free
[manual-test overlay](manual-test/README.md). It keeps the application and
monitoring Services internal and does not require dashboard TLS. The regular
Ingress resources remain available for a later DNS/TLS setup.
