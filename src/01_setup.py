# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Setup and inventory
# MAGIC
# MAGIC Creates the demo "before" state — legacy secret scopes plus the Unity Catalog
# MAGIC schemas to move into — then lists every scope and prints a starting
# MAGIC `mapping.yml` to paste into `src/mapping.yml` and edit.
# MAGIC
# MAGIC Migrating real scopes? Set `seed_demo` to `false`; the inventory still runs.

# COMMAND ----------

dbutils.widgets.dropdown("seed_demo", "true", ["true", "false"])

CATALOG = "workspace"          # Free Edition's default catalog
SCHEMAS = ["prod_credentials", "etl_credentials"]
DEFAULT_SCHEMA = "etl_credentials"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Demo scopes
# MAGIC
# MAGIC Key names are deliberately messy, to exercise the rename step.

# COMMAND ----------

SCOPES = {
    "prod-jdbc": {
        "username": "svc_reporting",
        "password": "demo-password-01",
        "jdbc.url": "jdbc:postgresql://db.example.com:5432/reporting",  # dot: illegal in UC names
    },
    "analytics-api": {
        "api-key": "demo-ak-0000",      # hyphen: legal but needs backticks in GRANT
        "api_secret": "demo-as-1111",
    },
    "legacy_etl": {
        "sftp_user": "etl_transfer",
        "SFTP_Password": "demo-password-02",
    },
}

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

if dbutils.widgets.get("seed_demo") == "true":
    existing = {s.name for s in w.secrets.list_scopes()}
    for scope, secrets in SCOPES.items():
        if scope not in existing:
            w.secrets.create_scope(scope=scope)
        for key, value in secrets.items():
            w.secrets.put_secret(scope=scope, key=key, string_value=value)
        print(f"{scope}: {len(secrets)} secrets")

# Kept as plain SQL rather than DAB `schemas` resources: in development mode a
# bundle prefixes those (prod_credentials -> dev_<user>_prod_credentials), which
# would break the fully-qualified names in mapping.yml.
for schema in SCHEMAS:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
    print(f"{CATALOG}.{schema}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inventory
# MAGIC
# MAGIC Legacy keys allow characters Unity Catalog names don't. Dots are illegal;
# MAGIC hyphens are legal but force backtick-quoting in every `GRANT`. So `jdbc.url`
# MAGIC becomes `jdbc_url` and `api-key` becomes `api_key`.
# MAGIC
# MAGIC Paste the output below into `src/mapping.yml`, then edit: drop a key to skip
# MAGIC it, drop a scope block to skip the scope, add `delete_scope: true` to a scope
# MAGIC you want removed once its secrets are verified.

# COMMAND ----------

import re


def uc_name(key: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", key.lower()).strip("_")
    return f"s_{name}" if name[0].isdigit() else name


print(f"target_catalog: {CATALOG}\n\nscopes:")

for scope in w.secrets.list_scopes():
    print(f"  {scope.name}:")
    print(f"    schema: {DEFAULT_SCHEMA}")
    print("    keys:")
    for meta in w.secrets.list_secrets(scope=scope.name):
        renamed = "    # renamed" if uc_name(meta.key) != meta.key else ""
        print(f"      {meta.key}: {uc_name(meta.key)}{renamed}")