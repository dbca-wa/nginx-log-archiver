# Nginx access log archiver

This project contains a utility for archiving the department's preserved Nginx access logs in the
[Parquet](https://parquet.apache.org/) column-oriented data file format for efficient storage.

A number of OSS libraries exist for interacting with Parquet storage; this project makes use of PyArrow:

- <https://arrow.apache.org/docs/python/index.html>

## Installation

Dependencies for this project are managed using [uv](https://docs.astral.sh/uv/).
With uv installed, change into the project directory and run:

    uv sync

Activate the virtualenv like so:

    source .venv/bin/activate

To run Python commands in the activated virtualenv, thereafter run them like so:

    python manage.py

Manage new or updated project dependencies with uv also, like so:

    uv add newpackage==1.0

## Usage

Activate the virtualenv like so:

    source .venv/bin/activate

To run Python commands in the activated virtualenv, thereafter run them as normal:

    python archiver.py --help

To archive all files for a given date and then delete the originals, run the following command:

    python archiver.py -d <YYYYmmdd> --delete-source

## Environment variables

This project uses **python-dotenv** to set environment variables (in a `.env` file).
The following variables are required for the project to run:

    AZURE_STORAGE_CONNECTION_STRING=MySecretAzureStorageAccountConnectionString

## Querying / filtering Parquet files

Example using PyArrow:

```python
import pyarrow.parquet as pq
import pyarrow.compute as pc

table = pq.read_table("nginx_access_logs.parquet")  # Filename of the Parquet file.
expr = pc.field("host") == "www.dbca.wa.gov.au"
len(table.filter(expr))
```

Reference: <https://arrow.apache.org/docs/python/index.html>
