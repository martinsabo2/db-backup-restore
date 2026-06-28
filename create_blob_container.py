import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
import requests


@dataclass(frozen=True)
class AppConfig:
    storage_account_name: str
    container_name: str
    account_url: str
    managed_identity_client_id: Optional[str]
    public_access: Optional[str]
    subscription_id: str
    backup_vault_resource_group: str
    backup_vault_name: str
    backup_instance_name: str
    restore_location: str
    source_data_store_type: str
    restore_file_prefix: str
    restore_poll_seconds: int
    restore_poll_timeout_seconds: int
    data_protection_api_version: str
    expected_datasource_type_prefix: str


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
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    backup_vault_resource_group = os.getenv("AZURE_BACKUP_VAULT_RESOURCE_GROUP", "").strip()
    backup_vault_name = os.getenv("AZURE_BACKUP_VAULT_NAME", "").strip()
    backup_instance_name = os.getenv("AZURE_BACKUP_INSTANCE_NAME", "").strip()
    restore_location = os.getenv("AZURE_BACKUP_RESTORE_LOCATION", "").strip()
    source_data_store_type = os.getenv("AZURE_BACKUP_SOURCE_DATA_STORE_TYPE", "VaultStore").strip() or "VaultStore"
    restore_file_prefix = os.getenv("AZURE_BACKUP_RESTORE_FILE_PREFIX", "restored").strip() or "restored"
    restore_poll_seconds_raw = os.getenv("AZURE_BACKUP_RESTORE_POLL_SECONDS", "15").strip()
    restore_poll_timeout_seconds_raw = os.getenv("AZURE_BACKUP_RESTORE_TIMEOUT_SECONDS", "1800").strip()
    data_protection_api_version = os.getenv("AZURE_BACKUP_API_VERSION", "2025-09-01").strip() or "2025-09-01"
    expected_datasource_type_prefix = (
        os.getenv("AZURE_BACKUP_EXPECTED_DATASOURCE_TYPE_PREFIX", "Microsoft.DBforPostgreSQL/").strip()
        or "Microsoft.DBforPostgreSQL/"
    )

    missing = []
    if not storage_account_name:
        missing.append("AZURE_STORAGE_ACCOUNT_NAME")
    if not container_name:
        missing.append("AZURE_BLOB_CONTAINER_NAME")
    if not subscription_id:
        missing.append("AZURE_SUBSCRIPTION_ID")
    if not backup_vault_resource_group:
        missing.append("AZURE_BACKUP_VAULT_RESOURCE_GROUP")
    if not backup_vault_name:
        missing.append("AZURE_BACKUP_VAULT_NAME")
    if not backup_instance_name:
        missing.append("AZURE_BACKUP_INSTANCE_NAME")
    if not restore_location:
        missing.append("AZURE_BACKUP_RESTORE_LOCATION")

    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

    if not account_url:
        account_url = f"https://{storage_account_name}.blob.core.windows.net"

    try:
        restore_poll_seconds = int(restore_poll_seconds_raw)
        restore_poll_timeout_seconds = int(restore_poll_timeout_seconds_raw)
    except ValueError as exc:
        raise ValueError("AZURE_BACKUP_RESTORE_POLL_SECONDS and AZURE_BACKUP_RESTORE_TIMEOUT_SECONDS must be integers") from exc

    return AppConfig(
        storage_account_name=storage_account_name,
        container_name=container_name,
        account_url=account_url,
        managed_identity_client_id=managed_identity_client_id,
        public_access=_normalize_public_access(public_access_raw),
        subscription_id=subscription_id,
        backup_vault_resource_group=backup_vault_resource_group,
        backup_vault_name=backup_vault_name,
        backup_instance_name=backup_instance_name,
        restore_location=restore_location,
        source_data_store_type=source_data_store_type,
        restore_file_prefix=restore_file_prefix,
        restore_poll_seconds=restore_poll_seconds,
        restore_poll_timeout_seconds=restore_poll_timeout_seconds,
        data_protection_api_version=data_protection_api_version,
        expected_datasource_type_prefix=expected_datasource_type_prefix,
    )


def _to_iso8601(value: str) -> datetime:
    sanitized = value.strip()
    if sanitized.endswith("Z"):
        sanitized = sanitized[:-1] + "+00:00"
    return datetime.fromisoformat(sanitized)


def _get_latest_recovery_point(recovery_points: list[dict[str, Any]]) -> dict[str, Any]:
    if not recovery_points:
        raise ValueError("No recovery points found for the backup instance.")

    def sort_key(item: dict[str, Any]) -> datetime:
        props = item.get("properties", {})
        candidate = (
            props.get("recoveryPointTime")
            or props.get("recoveryPointTimestamp")
            or props.get("pointInTime")
        )
        if isinstance(candidate, str) and candidate.strip():
            try:
                return _to_iso8601(candidate)
            except ValueError:
                pass
        # Fall back to minimum date when timestamp is missing/invalid.
        return datetime.min

    return sorted(recovery_points, key=sort_key, reverse=True)[0]


def _build_dataprotection_base_url(config: AppConfig) -> str:
    return (
        "https://management.azure.com"
        f"/subscriptions/{config.subscription_id}"
        f"/resourceGroups/{config.backup_vault_resource_group}"
        f"/providers/Microsoft.DataProtection/backupVaults/{config.backup_vault_name}"
        f"/backupInstances/{config.backup_instance_name}"
    )


def _arm_bearer_token(credential: DefaultAzureCredential) -> str:
    token = credential.get_token("https://management.azure.com/.default")
    return token.token


def _arm_get(url: str, token: str) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _arm_post(url: str, token: str, body: dict[str, Any]) -> requests.Response:
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    response.raise_for_status()
    return response


def _poll_async_operation(async_url: str, token: str, poll_seconds: int, timeout_seconds: int) -> str:
    elapsed = 0
    while elapsed <= timeout_seconds:
        operation_result = _arm_get(async_url, token)
        status = str(operation_result.get("status", "Unknown"))
        lowered = status.lower()
        if lowered in {"succeeded", "failed", "canceled", "cancelled"}:
            return status

        elapsed += poll_seconds
        # Use built-in clock sleep via requests' event loop is not available; fallback to simple wait.
        import time

        time.sleep(poll_seconds)

    return "Timeout"


def _find_latest_recovery_point(config: AppConfig, token: str, base_url: str) -> dict[str, Optional[str]]:
    recovery_points_url = f"{base_url}/recoveryPoints?api-version={config.data_protection_api_version}"
    recovery_points_payload = _arm_get(recovery_points_url, token)
    recovery_points = recovery_points_payload.get("value", [])
    latest_recovery_point = _get_latest_recovery_point(recovery_points)

    latest_recovery_point_props = latest_recovery_point.get("properties", {})
    recovery_point_id = latest_recovery_point.get("name")
    recovery_point_time = latest_recovery_point_props.get("recoveryPointTime")
    if not recovery_point_time:
        recovery_point_time = latest_recovery_point_props.get("recoveryPointTimestamp")
    policy_name = latest_recovery_point_props.get("policyName")

    if not recovery_point_id:
        raise ValueError("Latest recovery point response did not contain a recovery point ID.")

    return {
        "id": str(recovery_point_id),
        "recoveryPointTime": str(recovery_point_time) if recovery_point_time else None,
        "policyName": str(policy_name) if policy_name else None,
    }


def _build_restore_request_and_url(config: AppConfig, base_url: str, recovery_point_id: str) -> tuple[dict[str, Any], str]:
    target_container_url = f"{config.account_url.rstrip('/')}/{config.container_name}"
    restore_request: dict[str, Any] = {
        "objectType": "AzureBackupRecoveryPointBasedRestoreRequest",
        "recoveryPointId": recovery_point_id,
        "sourceDataStoreType": config.source_data_store_type,
        "restoreTargetInfo": {
            "objectType": "RestoreFilesTargetInfo",
            "recoveryOption": "FailIfExists",
            "restoreLocation": config.restore_location,
            "targetDetails": {
                "restoreTargetLocationType": "AzureBlobs",
                "url": target_container_url,
                "filePrefix": config.restore_file_prefix,
            },
        },
    }
    restore_url = f"{base_url}/restore?api-version={config.data_protection_api_version}"
    return restore_request, restore_url


def restore_from_last_recovery_point(config: AppConfig) -> None:
    credential = DefaultAzureCredential(
        managed_identity_client_id=config.managed_identity_client_id,
        exclude_interactive_browser_credential=True,
    )
    token = _arm_bearer_token(credential)

    base_url = _build_dataprotection_base_url(config)

    backup_instance_url = f"{base_url}?api-version={config.data_protection_api_version}"
    backup_instance_payload = _arm_get(backup_instance_url, token)
    datasource_type = (
        backup_instance_payload.get("properties", {})
        .get("dataSourceInfo", {})
        .get("resourceType", "")
    )
    if not datasource_type.lower().startswith(config.expected_datasource_type_prefix.lower()):
        raise ValueError(
            "Backup instance datasource is not PostgreSQL as expected. "
            f"Found resourceType='{datasource_type}'."
        )

    recovery_point = _find_latest_recovery_point(config, token, base_url)
    recovery_point_id = recovery_point["id"]
    recovery_point_time = recovery_point.get("recoveryPointTime") or "unknown"
    policy_name = recovery_point.get("policyName") or "unknown"

    logging.info(
        "Using recovery point metadata: recoveryPointTime='%s', policyName='%s'.",
        recovery_point_time,
        policy_name,
    )

    restore_request, restore_url = _build_restore_request_and_url(config, base_url, recovery_point_id)
    restore_response = _arm_post(restore_url, token, restore_request)

    async_operation_url = restore_response.headers.get("Azure-AsyncOperation")
    location = restore_response.headers.get("Location")
    body = restore_response.json() if restore_response.content else {}
    job_id = body.get("jobId")

    logging.info(
        "Triggered PostgreSQL restore from recovery point '%s' into container '%s'.",
        recovery_point_id,
        config.container_name,
    )
    if job_id:
        logging.info("Restore job ID: %s", job_id)
    if location:
        logging.info("Restore operation location: %s", location)

    if async_operation_url:
        logging.info("Restore operation is asynchronous. Polling for completion...")
        final_status = _poll_async_operation(
            async_url=async_operation_url,
            token=token,
            poll_seconds=config.restore_poll_seconds,
            timeout_seconds=config.restore_poll_timeout_seconds,
        )
        if final_status.lower() != "succeeded":
            raise RuntimeError(f"Restore operation did not succeed. Final status: {final_status}")
        logging.info("Restore operation finished with status: %s", final_status)
    else:
        logging.info("Restore API completed without async polling endpoint.")


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
        restore_from_last_recovery_point(config)
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
    except requests.HTTPError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        logging.error("Backup Vault API request failed: %s", detail)
        return 5
    except Exception as exc:  # pragma: no cover
        logging.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
