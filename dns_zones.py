import argparse
import csv
import json
import os
from tempfile import NamedTemporaryFile, TemporaryDirectory, TemporaryFile

import crossplane
import requests
from azure.cli.core import get_default_cli
from dotenv import load_dotenv

from utils import clone_repo, configure_logging, upload_log

# Load environment variables.
load_dotenv()
# Cloudflare API token
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
# Assumes a GitHub access token secret is present as an environment variable.
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
# Assumes an Azure storage connection string is defined as an environment variable.
CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

# Configure logging.
LOGGER = configure_logging()


def verify_cf_api_token(api_token: str):
    """Cloudflare API endpoint to verify a valid token."""
    url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
    headers = {"Authorization": f"Bearer {api_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def cf_list_zones(api_token: str):
    """Cloudflare API endpoint to list all DNS zones (assumes <50 in total)."""
    url = "https://api.cloudflare.com/client/v4/zones"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {
        "per_page": 50,
    }
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def cf_list_dns_records(api_token: str, zone_id: str):
    """Cloudflare API endpoint to list all DNS records for a given zone (assumes <1000 total)."""
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {
        "per_page": 1000,
    }
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def az_login(az_cli):
    """Invoke as follows:

    from azure.cli.core import get_default_cli
    az = get_default_cli()
    az_login(az)
    """
    azure_tenant_id = os.getenv("AZURE_TENANT_ID")
    azure_client_id = os.getenv("AZURE_CLIENT_ID")
    azure_client_secret = os.getenv("AZURE_CLIENT_SECRET")
    outfile = TemporaryFile("r+")
    az_cli.invoke(
        [
            "login",
            "--service-principal",
            "--tenant",
            azure_tenant_id,
            "--username",
            azure_client_id,
            "--password",
            azure_client_secret,
        ],
        out_file=outfile,
    )
    outfile.flush()
    outfile.seek(0)
    data = json.load(outfile)
    outfile.close()
    return data


def az_dns_zone_list(az_cli):
    outfile = TemporaryFile("r+")
    az_cli.invoke(["network", "dns", "zone", "list"], out_file=outfile)
    outfile.flush()
    outfile.seek(0)
    data = json.load(outfile)
    outfile.close()
    return data


def az_dns_recordset_list(az_cli, zone_name: str, resource_group: str = "oim-appservices"):
    outfile = TemporaryFile("r+")
    az_cli.invoke(["network", "dns", "record-set", "list", "--resource-group", resource_group, "--zone-name", zone_name], out_file=outfile)
    outfile.flush()
    outfile.seek(0)
    data = json.load(outfile)
    outfile.close()
    return data


def get_all_zone_records():
    # CLOUDFLARE
    cf_api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    cf_zones = cf_list_zones(cf_api_token)["result"]
    cf_zone_ids = []
    for zone in cf_zones:
        cf_zone_ids.append((zone["name"], zone["id"]))

    zone_records = []
    for zone in cf_zone_ids:
        LOGGER.info(f"Checking {zone[0]} (Cloudflare)")
        records = cf_list_dns_records(cf_api_token, zone[1])["result"]
        for record in records:
            zone_records.append((record["name"], record["content"], record["type"], "Cloudflare"))

    # AZURE DNS
    az = get_default_cli()
    az_login(az)
    zones = az_dns_zone_list(az)
    zone_names = [zone["name"] for zone in zones]
    recordsets = []

    for zone_name in zone_names:
        LOGGER.info(f"Checking {zone_name} (Azure)")
        zone_recordsets = az_dns_recordset_list(az, zone_name)
        recordsets += zone_recordsets

    # Extract A and CNAME records.
    for record in recordsets:
        if record["type"] == "Microsoft.Network/dnszones/A":
            if "ARecords" in record and record["ARecords"]:
                for obj in record["ARecords"]:
                    zone_records.append((record["fqdn"], obj["ipv4Address"], record["type"], "Azure"))
        elif record["type"] == "Microsoft.Network/dnszones/CNAME":
            zone_records.append((record["fqdn"], record["CNAMERecord"]["cname"], record["type"], "Azure"))

    # NGINX
    repo_dest = TemporaryDirectory()
    cloned_repo = clone_repo(repo_dest.name, GITHUB_ACCESS_TOKEN, GITHUB_REPO)
    if cloned_repo:
        # Parse the Nginx conf to a temporary file.
        dest_path = os.path.join(repo_dest.name, "nginx", "nginx.conf")
        nginx_conf = crossplane.parse(dest_path)
        config_list = nginx_conf["config"]
        sites_enabled_configs = [c for c in config_list if "nginx/sites-enabled" in c["file"]]
        parsed = []
        for config in sites_enabled_configs:
            parsed += config["parsed"]

        server_names = []

        for p in parsed:
            server_name = None
            targets = set()
            for part in p["block"]:
                if part["directive"] == "server_name":
                    server_name = part["args"][0]
                elif part["directive"] == "location":
                    for subpart in part["block"]:
                        if subpart["directive"] == "proxy_pass":
                            targets.add((subpart["args"][0], "proxy_pass"))
                        elif subpart["directive"] == "return" and len(subpart["args"]) > 1:
                            targets.add((subpart["args"][1], "redirect"))
            server_names.append((server_name, targets))

        for name in server_names:
            if not name[0]:
                continue
            targets = name[1]
            if targets:
                for target in targets:
                    zone_records.append((name[0], target[0], target[1], "Nginx"))
            else:
                zone_records.append((name[0], "", "redirect", "Nginx"))

    return zone_records


def parse_dns_zones(container_dest: str, blob_name: str):
    LOGGER.info("Querying DNS records")
    zone_records = get_all_zone_records()
    zone_records = sorted(zone_records)

    # Write the parsed DNS records to a temporary file.
    out_csv = NamedTemporaryFile(mode="w", suffix=".csv")
    writer = csv.writer(out_csv)
    writer.writerow(["SUBDOMAIN", "TARGET", "TYPE", "SOURCE"])

    for record in zone_records:
        # Skip TXT records.
        if record[2] == "TXT":
            continue

        writer.writerow([record[0], record[1], record[2], record[3]])

    # Upload the temp file to blob storage.
    upload_log(out_csv.name, container_dest, CONN_STR, blob_name=blob_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query DNS zone records, parse Nginx rules, summarise as CSV and upload to a container.")
    parser.add_argument(
        "-c",
        "--container",
        help="The destination container name (optional, default 'analytics')",
        default="analytics",
        action="store",
        required=False,
    )
    parser.add_argument(
        "-b",
        "--blob-name",
        help="The destination blob name (optional, default 'dbca_subdomain_target_records.csv')",
        default="dbca_subdomain_target_records.csv",
        action="store",
        required=False,
    )
    args = parser.parse_args()
    parse_dns_zones(
        container_dest=args.container,
        blob_name=args.blob_name,
    )
