# Secure GeoLAB / Destatis RAG Deployment

This deployment isolates GeoLAB into two containers:

- `geolab-backend` (FastAPI)
- `geolab-frontend` (static React app served by Caddy)

The frontend is the only web entrypoint. The backend is only reachable on the internal Docker network plus an optional localhost debug port.

## What the containers can see

The backend only receives these explicit mounts:

- `destatis_advanced.faiss`
- `destatis_full_metadata.json`
- `genesis_metadata/`
- `curated_apis.json`
- `region_map.csv`
- `soep_metadata_output/`
- `soep_metadata_pdf.json`
- `soep_metadata_manual.json`
- a dedicated writable cache volume for SOEP RAG embeddings/index files

It does **not** receive your repo root, SSH keys, notebooks, or unrelated host directories.

The backend is configured to use CUDA by default for sentence-transformer retrieval and the SOEP cross-encoder, as soon as Docker's NVIDIA runtime is available on the host.

## Start locally

```bash
cd /home/ubuntu/destatis-rag/deploy/secure-geolab
cp .env.example .env
docker compose up -d --build
```

Local-only URLs:

- frontend: `http://127.0.0.1:15173`
- backend debug port: `http://127.0.0.1:18000`

## GPU prerequisites

Before starting the stack, verify host GPU passthrough works:

- `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`

If that fails, install and configure the NVIDIA Container Toolkit first.

Official docs:

- NVIDIA Container Toolkit install guide: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

## Add Cloudflare Tunnel

1. Put your Cloudflare tunnel credentials at:
   - `deploy/secure-geolab/cloudflare/credentials.json`
2. Edit:
   - `deploy/secure-geolab/cloudflare/geolab-cloudflared.yml`
3. Start the tunnel sidecar:

```bash
docker compose --profile cloudflare up -d
```

## Cloudflare Access setup

Create a **Self-hosted** Access application for the GeoLAB hostname and configure:

- Login method: **One-time PIN**
- Include: only the guest emails you invite
- Require: **purpose justification**
- Temporary authentication / approval workflow: **enabled**
- Approvals required: `1`
- Approver: **your email**
- Short session duration, for example `1h`

Official docs:

- Tunnel: https://developers.cloudflare.com/tunnel/
- Self-hosted Access apps: https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/
- One-time PIN: https://developers.cloudflare.com/cloudflare-one/identity/one-time-pin/
- Temporary auth / approvals: https://developers.cloudflare.com/cloudflare-one/access-controls/policies/temporary-auth/
