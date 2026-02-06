import logging
import os
import subprocess
import sys
from typing import List, Literal, Optional

from azure.storage.blob import BlobClient, ContainerClient


def configure_logging(log_level: Optional[int] = None, azure_log_level: Optional[int] = None) -> logging.Logger:
    """Configure logging for the default logger and for the `azure` logger."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("{asctime} | {levelname} | {message}", style="{")
    handler = logging.StreamHandler(sys.stdout)
    if log_level:
        handler.setLevel(log_level)
    else:
        handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Set the logging level for all azure-* libraries (the azure-storage-blob library uses this one).
    # Reference: https://learn.microsoft.com/en-us/azure/developer/python/sdk/azure-sdk-logging
    azure_logger = logging.getLogger("azure")
    if azure_log_level:
        azure_logger.setLevel(azure_log_level)
    else:
        azure_logger.setLevel(logging.WARNING)

    return logger


def get_blob_client(
    conn_str: str, container_name: str, blob_name: str, max_put: int = 16 * 1024 * 1024, conn_timeout: int = 60
) -> BlobClient:
    """
    Return a BlobClient class having defaults to account for a slower internet connection.
    The parent class defaults are 64MB and 20s.
    https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.blobclient?view=azure-python#azure-storage-blob-blobclient-from-connection-string
    """
    return BlobClient.from_connection_string(
        conn_str,
        container_name,
        blob_name,
        max_single_put_size=max_put,
        connection_timeout=conn_timeout,
    )


def download_logs(
    timestamp: str,
    hosts: str,
    destination_dir: str,
    container_name: str,
    conn_str: str,
    nginx_host_log: bool = False,
    enable_logging: bool = True,
) -> Literal[True] | None:
    """Given the passed in timestamp, hosts list and destination directory, download logs from blob storage."""
    if enable_logging:
        logger = logging.getLogger()

    container_client = ContainerClient.from_connection_string(conn_str, container_name)
    hosts_list = hosts.split(",")
    log_list = []
    for host in hosts_list:
        # list_blobs returns a list of BlobProperties objects.
        if nginx_host_log:
            blob_list = container_client.list_blobs(name_starts_with=f"{host}/nginx_access.{timestamp}")
        else:
            blob_list = container_client.list_blobs(name_starts_with=f"{host}/{timestamp}")
        log_list += [b for b in blob_list]

    if not log_list:  # Nil source data, abort.
        if enable_logging:
            logger.info(f"No source data for timestamp {timestamp}, hosts {hosts}")
        return

    for blob in log_list:
        host, name = blob.name.split("/")
        if nginx_host_log:
            name = f"{timestamp}.{host}.access.json"
            dest_path = os.path.join(destination_dir, name)
        else:
            dest_path = os.path.join(destination_dir, name)

        blob_client = get_blob_client(conn_str, container_name, blob.name)

        if enable_logging:
            logger.info(f"Downloading blob {blob.name} ({container_name} container) to {dest_path}")

        try:
            with open(dest_path, "wb") as downloaded_blob:
                download_stream = blob_client.download_blob()
                downloaded_blob.write(download_stream.readall())
        except Exception as e:
            if enable_logging:
                logger.error(f"Exception during download of {blob.name}, aborting")
                logger.exception(e)
            return

    return True


def upload_log(
    source_path: str,
    container_name: str,
    conn_str: str,
    overwrite: bool = True,
    enable_logging: bool = True,
    blob_name: str = "",
):
    """Upload a single log at `source_path` to Azure blob storage (`blob_name` destination name is optional)."""
    if not blob_name:
        blob_name = os.path.basename(source_path)

    blob_client = get_blob_client(conn_str, container_name, blob_name)

    if enable_logging:
        logger = logging.getLogger()
        logger.info(f"Uploading {source_path} to container {container_name}/{blob_name}")

    with open(file=source_path, mode="rb") as data:
        blob_client.upload_blob(data, overwrite=overwrite, validate_content=True)


def clone_repo(dest_path: str, github_access_token: str, github_repo: str, enable_logging: bool = True) -> List | Literal[False]:
    """Clone the GitHub repository to `dest_path`."""
    cmd = f"git clone --quiet --depth=1 https://{github_access_token}@{github_repo} {dest_path}"
    if enable_logging:
        logger = logging.getLogger()
        logger.info(f"Cloning https://{github_repo} to {dest_path}")

    try:
        subprocess.check_call(cmd, shell=True)
        return os.listdir(dest_path)
    except subprocess.CalledProcessError as e:
        if enable_logging:
            logger.warning("Error cloning the repository")
            logger.exception(e)
        return False
