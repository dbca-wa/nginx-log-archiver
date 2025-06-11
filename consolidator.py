import argparse
import os
import re
from tempfile import TemporaryDirectory

import orjson as json
import requests
import unicodecsv as csv
from dotenv import load_dotenv

from utils import configure_logging, download_logs, upload_log

# Load environment variables.
load_dotenv()
# Assumes a Azure storage connection string is defined as an environment variable.
CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
# Optionally use the Sentry cron monitor, if that environment variable is defined.
SENTRY_CRON_URL = os.getenv("SENTRY_CRON_URL")

# Configure logging.
LOGGER = configure_logging()


def consolidate_json_access_requests(timestamp, source_dir, destination_dir):
    """Given the passed-in timestamp, source_dir and destination_dir, consolidate all access requests
    in JSON logs in the source into a single CSV file in destination."""
    loglist = []
    source_json_files = os.listdir(source_dir)
    source_json_files = [f for f in source_json_files if f.startswith(timestamp)]

    for f in source_json_files:
        source = os.path.join(source_dir, f)
        LOGGER.info(f"Processing {source} access requests")
        log = open(source, "r", errors="replace")
        for line in log.readlines():
            d = json.loads(line)
            if d["source"] == "stdout" and "log" not in d:  # Skips errors and non-Nginx logs.
                try:
                    loglist.append(
                        [
                            d["timestamp"],
                            d["remote_ip"],
                            d["host"],
                            d["uri"],
                            d["query"],
                            d["method"],
                            d["protocol"],
                            int(d["status"]),  # Transform str to int
                            int(float(d["request_time"]) * 1000 * 1000),  # Transform to microseconds
                            int(d["bytes_sent"]),  # Transform str to int
                            re.sub(r"\r|\n|\"|'", "", d["user_agent"]),  # Remove quotes and newlines in the User-Agent string
                            d["ssouser"],
                        ]
                    )
                except:  # Occasionally, parsing the log dict might throw an exception. Skip this logs.
                    pass

    out_log = os.path.join(destination_dir, f"{timestamp}.nginx.access.csv")
    LOGGER.info(f"Exporting to {out_log}")
    f = open(out_log, "wb")
    writer = csv.writer(f,escapechar="\\")
    for row in sorted(loglist):
        writer.writerow(row)

    return out_log


def consolidate_json_errors(timestamp, source_dir, destination_dir):
    """Given the passed-in timestamp, source_dir and destination_dir, consolidate all errors
    in JSON logs in `source_dir` into a single CSV file in `destination_dir`"""
    loglist = []
    source_json_files = os.listdir(source_dir)
    source_json_files = [f for f in source_json_files if f.startswith(timestamp) and f.endswith(".json")]
    pattern = re.compile(r"^(?P<timestamp>[\d\/]+\s[\d:]+)\s\[(?P<level>[a-z]+)\]\s(?P<message>.+$)")

    for f in source_json_files:
        source = os.path.join(source_dir, f)
        LOGGER.info(f"Processing {source} errors")
        log = open(source, "r", errors="replace")
        for line in log.readlines():
            d = json.loads(line)
            if d["source"] == "stderr":  # Only process error logs.
                log_line = d["log"]
                try:
                    data = pattern.match(log_line).groupdict()
                    loglist.append([data["timestamp"], data["level"], data["message"]])
                except:
                    pass

    out_log = os.path.join(destination_dir, f"{timestamp}.nginx.errors.csv")
    LOGGER.info(f"Exporting to {out_log}")
    f = open(out_log, "wb")
    writer = csv.writer(f,escapechar="\\")
    for row in sorted(loglist):
        writer.writerow(row)

    return out_log


def consolidate_logs(
    timestamp,
    hosts,
    container_src="access-logs-json",
    container_dest="access-logs",
    container_dest_errors="error-logs",
):
    """Download logs for the specified timestamp and services, consolidate and upload the source logs."""
    if SENTRY_CRON_URL:
        LOGGER.info("Signalling Sentry monitor (in progress)")
        requests.get(f"{SENTRY_CRON_URL}?status=in_progress")

    # Use a temporary directory to download JSON logs.
    temp_dir = TemporaryDirectory()
    # Download Nginx JSON logs.
    downloads = download_logs(timestamp, hosts, temp_dir.name, container_src, CONN_STR, True, slow_connection=True)

    if downloads:
        # Consolidate access request logs into one CSV file.
        out_log = consolidate_json_access_requests(timestamp, temp_dir.name, temp_dir.name)
        # Upload consolidated CSV log to blob storage.
        upload_log(out_log, container_dest, CONN_STR)
        # Consolidate error logs into one CSV file.
        out_log_errors = consolidate_json_errors(timestamp, temp_dir.name, temp_dir.name)
        # Upload consolidated CSV errors to blob storage.
        upload_log(out_log_errors, container_dest_errors, CONN_STR, slow_connection=True)

    if SENTRY_CRON_URL:
        LOGGER.info("Signalling Sentry monitor (completed)")
        requests.get(f"{SENTRY_CRON_URL}?status=ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A script to consolidate multiple JSON-formatted Nginx log files from different hosts into a single CSV file."
    )
    parser.add_argument(
        "-t",
        "--timestamp",
        help="A timestamp value to the nearest hour in the format YYYYmmddHH",
        action="store",
        required=True,
    )
    parser.add_argument(
        "-s",
        "--hosts",
        help="A comma-seperated list of hostnames to process JSON-formatted logs",
        action="store",
        required=True,
    )
    parser.add_argument(
        "-c",
        "--container",
        help="The source logs container name (optional, default 'access-logs-json')",
        default="access-logs-json",
        action="store",
        required=False,
    )
    parser.add_argument(
        "-d",
        "--destination-container",
        help="The destination container name (optional, default 'access-logs')",
        default="access-logs",
        action="store",
        required=False,
    )
    parser.add_argument(
        "-e",
        "--destination-container-errors",
        help="The destination container name for error logs (optional, default 'error-logs')",
        default="error-logs",
        action="store",
        required=False,
    )
    args = parser.parse_args()
    consolidate_logs(
        timestamp=args.timestamp,
        hosts=args.hosts,
        container_src=args.container,
        container_dest=args.destination_container,
        container_dest_errors=args.destination_container_errors,
    )
