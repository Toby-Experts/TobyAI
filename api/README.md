# Waitlist API (Azure Functions, Python)

HTTP endpoint that receives waitlist signups from the marketing site and stores
each one as a row in **Azure Table Storage**. Deploy it to an **Australian
region** so signup data stays in Australia, consistent with the site's
"Client data stays in Australia" promise.

- Runtime: Python (Azure Functions v2 programming model)
- Route: `POST /waitlist`
- Store: Table `waitlist` in your storage account
- CORS: handled in code, restricted to `https://tobyai.io` and `https://www.tobyai.io`

## Data residency (must stay in Australia)

Signup data lives wherever the **storage account** is created, so the one rule
that matters: create the storage account (and the function app) in an Australian
region — `australiaeast` (Sydney) is used throughout this guide.

- Australia is a single Azure geo. Even geo-redundant storage (GRS) pairs
  `australiaeast` with `australiasoutheast` (Melbourne) — both in Australia — so
  no redundancy setting ships data offshore.
- Keep the function app in the same region so data is processed in Australia too.
- Do **not** recreate these resources in a non-AU region; that is the only way
  the "Client data stays in Australia" promise would break.

## Files

| File | Purpose |
| --- | --- |
| `function_app.py` | The HTTP-triggered function |
| `requirements.txt` | Python dependencies |
| `host.json` | Host config (`routePrefix: ""` so the route is `/waitlist`, not `/api/waitlist`) |
| `local.settings.json.example` | Template for local settings (copy to `local.settings.json`, never commit the real one) |

## One-time Azure setup (Australia East)

```bash
# Variables
RG=tobyai-rg
LOC=australiaeast
STG=tobyaiwaitlist$RANDOM          # storage account name (lowercase, globally unique)
APP=tobyai-waitlist-fn            # function app name (globally unique)

# Resource group + storage account in Australia
az group create -n $RG -l $LOC
az storage account create -n $STG -g $RG -l $LOC --sku Standard_LRS

# Python Function App (consumption plan) in Australia
az functionapp create -n $APP -g $RG -l $LOC \
  --storage-account $STG --consumption-plan-location $LOC \
  --runtime python --runtime-version 3.11 --functions-version 4 --os-type Linux

# Point the function at the AU storage account for the waitlist table
CONN=$(az storage account show-connection-string -n $STG -g $RG --query connectionString -o tsv)
az functionapp config appsettings set -n $APP -g $RG \
  --settings WAITLIST_TABLE_CONNECTION="$CONN"
```

> **CORS:** leave the Function App's portal CORS list **empty**. CORS is handled
> in `function_app.py`. If you also add origins in the portal you can end up with
> duplicate `Access-Control-Allow-Origin` headers, which browsers reject.

## Deploy

From this `api/` folder, with the [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) installed:

```bash
func azure functionapp publish tobyai-waitlist-fn
```

After deploy, the endpoint is:

```
https://tobyai-waitlist-fn.azurewebsites.net/waitlist
```

## Custom domain (recommended)

The marketing site lives on the apex `tobyai.io` (GitHub Pages), so the API uses
a subdomain. Map **`api.tobyai.io`** to the function app:

1. Add a CNAME `api` -> `tobyai-waitlist-fn.azurewebsites.net` in DNS.
2. In the Function App: **Custom domains** -> add `api.tobyai.io`, then create a
   free **App Service Managed Certificate** and bind it.

The endpoint is then `https://api.tobyai.io/waitlist`, which is what the site's
`WAITLIST_ENDPOINT` is set to in `index.html`.

## Local testing

```bash
cp local.settings.json.example local.settings.json   # fill in WAITLIST_TABLE_CONNECTION
pip install -r requirements.txt
func start
# POST to http://localhost:7071/waitlist
```

## Viewing / exporting signups

Open the storage account in the Azure Portal -> **Storage browser** -> **Tables**
-> `waitlist`, or use Azure Storage Explorer to browse and export to CSV.
