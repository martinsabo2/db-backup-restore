This Python code is for Azure. The code will run on an Ubuntu VM. The VM will use a managed identity for Azure permissions.

The source code is managed by GIT and a GIT repository should be open.

## Create Blob Container Script

The repository now includes a configuration-driven script to create a blob container:

- `create_blob_container.py`

The script uses:

- `DefaultAzureCredential` (managed identity on the VM)
- `BlobServiceClient` from `azure-storage-blob`

It is idempotent: if the container already exists, it logs that and exits successfully.

## Prerequisites

1. Python 3.9+
2. VM managed identity has data-plane permission on the target storage account:
	- `Storage Blob Data Contributor` (or higher)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` values into your environment (or export directly in shell).

Required variables:

- `AZURE_STORAGE_ACCOUNT_NAME`
- `AZURE_BLOB_CONTAINER_NAME`

Optional variables:

- `AZURE_STORAGE_ACCOUNT_URL` (defaults to `https://<account>.blob.core.windows.net`)
- `AZURE_MANAGED_IDENTITY_CLIENT_ID` (for user-assigned identity)
- `AZURE_BLOB_PUBLIC_ACCESS` (`none`, `blob`, or `container`)

Example:

```bash
export AZURE_STORAGE_ACCOUNT_NAME=mystorageacct
export AZURE_BLOB_CONTAINER_NAME=backups
export AZURE_BLOB_PUBLIC_ACCESS=none
```

## Run

```bash
python create_blob_container.py
```
