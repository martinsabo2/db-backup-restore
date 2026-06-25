import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


@dataclass(frozen=True)
class AppConfig:
    storage_account_name: str
    container_name: str
    account_url: str
    managed_identity_client_id: Optional[str]
    public_access: Optional[str]


def _normalize_public_access(value: str) -> Optional[str]:
    normalized = value.strip().lower()
    if normalized in ("", "none"):
        return None
    if normalized in ("blob", "container"):
        return normalized
    raise ValueError("AZURE_BLOB_PUBLIC_ACCESS must be one of: none, blob, container")


def load_config() -> AppConfig:
    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip()
    container_name = os.getenv("AZURE_BLOB_CONTAINER_NAME", "").strip()
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    managed_identity_client_id = os.getenv("AZURE_MANAGED_IDENTITY_CLIENT_ID", "").strip() or None
    public_access_raw = os.getenv("AZURE_BLOB_PUBLIC_ACCESS", "none")

    missing = []
    if not storage_account_name:
        missing.append("AZURE_STORAGE_ACCOUNT_NAME")
    if not container_name:
        missing.append("AZURE_BLOB_CONTAINER_NAME")

    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

    if not account_url:
        account_url = f"https://{storage_account_name}.blob.core.windows.net"

    return AppConfig(
        storage_account_name=storage_account_name,
        container_name=container_name,
        account_url=account_url,
        managed_identity_client_id=managed_identity_client_id,
        public_access=_normalize_public_access(public_access_raw),
    )


def create_container(config: AppConfig) -> bool:
    credential = DefaultAzureCredential(
        managed_identity_client_id=config.managed_identity_client_id,
        exclude_interactive_browser_credential=True,
    )

    blob_service_client = BlobServiceClient(
        account_url=config.account_url,
        credential=credential,
        retry_total=5,
        retry_backoff_factor=0.8,
        retry_backoff_max=30,
    )

    container_client = blob_service_client.get_container_client(config.container_name)

    try:
        container_client.create_container(public_access=config.public_access)
        logging.info("Created container '%s' in account '%s'.", config.container_name, config.storage_account_name)
        return True
    except ResourceExistsError:
        logging.info("Container '%s' already exists in account '%s'.", config.container_name, config.storage_account_name)
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = load_config()
        create_container(config)
        return 0
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2
    except ClientAuthenticationError as exc:
        logging.error("Authentication failed. Ensure the VM managed identity has blob data contributor access: %s", exc)
        return 3
    except HttpResponseError as exc:
        logging.error("Azure Storage request failed: %s", exc)
        return 4
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
