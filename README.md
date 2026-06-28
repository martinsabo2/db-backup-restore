This Python code is for Azure. The code will run on an Ubuntu VM. The VM will use a managed identity for Azure permissions.

The source code is managed by GIT and a GIT repository should be open.

## Create Blob Container Script

The repository now includes a configuration-driven script to:

1. Create a blob container in a storage account.
2. Restore data from the Backup Vault's latest recovery point into that blob container by using the Backup Vault REST API.

Script:

- `create_blob_container.py`

The script uses:

- `DefaultAzureCredential` (managed identity on the VM)
- `BlobServiceClient` from `azure-storage-blob`
- Backup Vault REST API (`Microsoft.DataProtection`) for restore orchestration

It is idempotent for container creation: if the container already exists, it logs that and continues.

## Prerequisites

1. Python 3.9+
2. VM managed identity has data-plane permission on the target storage account:
	- `Storage Blob Data Contributor` (or higher)
3. VM managed identity has permission to read/trigger restore in Backup Vault:
	- Backup vault operations for recovery points and restore (for example Backup Contributor on vault scope, plus required vault restore permissions)
4. Backup instance is a PostgreSQL backup instance.
5. Restore target is in the same subscription as the backup vault and backup instance.

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
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_BACKUP_VAULT_RESOURCE_GROUP`
- `AZURE_BACKUP_VAULT_NAME`
- `AZURE_BACKUP_INSTANCE_NAME`
- `AZURE_BACKUP_RESTORE_LOCATION`

Optional variables:

- `AZURE_STORAGE_ACCOUNT_URL` (defaults to `https://<account>.blob.core.windows.net`)
- `AZURE_MANAGED_IDENTITY_CLIENT_ID` (for user-assigned identity)
- `AZURE_BLOB_PUBLIC_ACCESS` (`none`, `blob`, or `container`)
- `AZURE_BACKUP_API_VERSION` (default `2025-09-01`)
- `AZURE_BACKUP_SOURCE_DATA_STORE_TYPE` (default `VaultStore`)
- `AZURE_BACKUP_EXPECTED_DATASOURCE_TYPE_PREFIX` (default `Microsoft.DBforPostgreSQL/`)
- `AZURE_BACKUP_RESTORE_FILE_PREFIX` (default `restored`)
- `AZURE_BACKUP_RESTORE_POLL_SECONDS` (default `15`)
- `AZURE_BACKUP_RESTORE_TIMEOUT_SECONDS` (default `1800`)

Example:

```bash
export AZURE_STORAGE_ACCOUNT_NAME=mystorageacct
export AZURE_BLOB_CONTAINER_NAME=backups
export AZURE_BLOB_PUBLIC_ACCESS=none
export AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000
export AZURE_BACKUP_VAULT_RESOURCE_GROUP=rg-backup
export AZURE_BACKUP_VAULT_NAME=myBackupVault
export AZURE_BACKUP_INSTANCE_NAME=myBlobBackupInstance
export AZURE_BACKUP_RESTORE_LOCATION=eastus
```

## Run

```bash
python create_blob_container.py
```
