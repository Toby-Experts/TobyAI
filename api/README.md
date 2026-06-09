# Waitlist API (FastAPI on Azure Container Apps)

A small **FastAPI** service that receives waitlist signups from the marketing
site and stores each one as a row in **Azure Table Storage**. It runs as a
container on **Azure Container Apps** in an **Australian region**, so signup
data stays in Australia.

- Framework: FastAPI (auto OpenAPI docs at `/docs`)
- Endpoint: `POST /waitlist`, plus `GET /healthz` for probes
- Store: Table `waitlist` in your storage account
- CORS: handled by FastAPI middleware, restricted to `https://tobyai.io` and `https://www.tobyai.io`
- Hosting: Azure Container Apps (consumption, scales to zero when idle)

## Scope / architecture note

This is just the signup endpoint, so it's a plain REST API. The **Model Context
Protocol (MCP)** standard applies to TobyAI's product tool layer — how the AI
agent calls the finance/tax-prep tools — and is intentionally **out of scope for
the waitlist**. MCP adds no value to a signup form.

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app: the `/waitlist` endpoint, validation, Table Storage write |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image (uvicorn on port 8000) |
| `.dockerignore` | Files kept out of the image |

## Data residency (must stay in Australia)

Signup data lives wherever the **storage account** is created, so create the
storage account **and** the Container App in an Australian region —
`australiaeast` (Sydney) is used throughout. Australia is a single Azure geo, so
even geo-redundant storage (GRS) pairs `australiaeast` with `australiasoutheast`
(Melbourne) — both in Australia. Do not recreate these resources in a non-AU
region.

## Run locally

```bash
pip install -r requirements.txt
# Point at a real AU storage account, or run Azurite for local Table emulation:
export WAITLIST_TABLE_CONNECTION="UseDevelopmentStorage=true"
uvicorn app.main:app --reload
# POST to http://localhost:8000/waitlist ; interactive docs at /docs
```

## Deploy to Azure Container Apps (Australia East)

```bash
RG=tobyai-rg
LOC=australiaeast
STG=tobyaiwaitlist$RANDOM      # storage account (lowercase, globally unique)
APP=tobyai-waitlist           # container app name

# Resource group + AU storage account
az group create -n $RG -l $LOC
az storage account create -n $STG -g $RG -l $LOC --sku Standard_LRS
CONN=$(az storage account show-connection-string -n $STG -g $RG --query connectionString -o tsv)

# Build the image from the Dockerfile and deploy to Container Apps (AU).
# `az containerapp up` provisions the environment + app and wires up ingress.
az containerapp up \
  -n $APP -g $RG -l $LOC \
  --source . \
  --ingress external --target-port 8000 \
  --env-vars WAITLIST_TABLE_CONNECTION="$CONN"
```

The command prints the app URL, e.g. `https://tobyai-waitlist.<hash>.australiaeast.azurecontainerapps.io`.
The endpoint is that URL + `/waitlist`.

> CORS is enforced in the app (`ALLOWED_ORIGINS` in `app/main.py`). Update that
> list if the site's origin ever changes.

### Scale to zero (optional, cheaper)

```bash
az containerapp update -n $APP -g $RG --min-replicas 0
```

## Custom domain

The marketing site is on the apex `tobyai.io` (GitHub Pages), so the API uses a
subdomain. Map **`api.tobyai.io`** to the container app:

```bash
az containerapp hostname add -n $APP -g $RG --hostname api.tobyai.io
az containerapp hostname bind -n $APP -g $RG --hostname api.tobyai.io \
  --environment <your-containerapp-env> --validation-method CNAME
```

Add the CNAME `api` -> the app's default FQDN in DNS first. The endpoint is then
`https://api.tobyai.io/waitlist`, which is what the site's `WAITLIST_ENDPOINT`
in `index.html` points to.

## Viewing / exporting signups

Open the storage account in the Azure Portal -> **Storage browser** -> **Tables**
-> `waitlist`, or use Azure Storage Explorer to browse and export to CSV.
