# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Migrate to Unity Catalog secrets
# MAGIC
# MAGIC Reads `mapping.yml`, copies each secret into Unity Catalog, verifies it, and
# MAGIC optionally deletes the emptied scopes.
# MAGIC
# MAGIC There is no `CREATE SECRET` SQL statement — Unity Catalog secrets are created
# MAGIC through the REST API. That is also why this runs on any UC-enabled compute:
# MAGIC `dbutils.secrets.get(catalog=..., schema=..., key=...)` needs DBR 17.3 LTS+ or
# MAGIC serverless environment version 4+, but the API needs neither.

# COMMAND ----------

dbutils.widgets.dropdown("dry_run", "true", ["true", "false"])
dbutils.widgets.dropdown("delete_scopes", "false", ["true", "false"])

DRY_RUN = dbutils.widgets.get("dry_run") == "true"
DELETE_SCOPES = dbutils.widgets.get("delete_scopes") == "true"

# COMMAND ----------

import hashlib

import requests
import yaml
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
API = f"{w.config.host.rstrip('/')}/api/2.1/unity-catalog/secrets"

# mapping.yml sits next to this notebook, which is the working directory.
PLAN = yaml.safe_load(open("mapping.yml"))
CATALOG = PLAN["target_catalog"]


def uc_create(schema, name, value, comment):
    r = requests.post(API, headers=w.config.authenticate(),
                      json={"catalog_name": CATALOG, "schema_name": schema,
                            "name": name, "value": value, "comment": comment})
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")


def uc_digest(full_name):
    """SHA-256 of the stored value, so the value itself never reaches a cell."""
    r = requests.get(f"{API}/{full_name}", headers=w.config.authenticate(),
                     params={"include_value": "true"})
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return hashlib.sha256(r.json()["effective_value"].encode()).hexdigest()


def uc_exists(full_name):
    return requests.get(f"{API}/{full_name}",
                        headers=w.config.authenticate()).status_code != 404


# COMMAND ----------

# MAGIC %md
# MAGIC Two legacy keys can collapse onto the same Unity Catalog name (`api-key` and
# MAGIC `api.key` both become `api_key`), which would silently overwrite one with the
# MAGIC other. Catch it before writing anything.

# COMMAND ----------

targets = [
    f"{CATALOG}.{spec['schema']}.{name}"
    for spec in PLAN["scopes"].values()
    for name in spec["keys"].values()
]
if dupes := {t for t in targets if targets.count(t) > 1}:
    raise ValueError(f"Two secrets map to the same name: {sorted(dupes)}")

print(f"{len(targets)} secrets to migrate" + ("  (DRY RUN)" if DRY_RUN else ""))

# COMMAND ----------

migrated = set()

for scope, spec in PLAN["scopes"].items():
    for source_key, uc_key in spec["keys"].items():
        full_name = f"{CATALOG}.{spec['schema']}.{uc_key}"
        try:
            value = dbutils.secrets.get(scope=scope, key=source_key)

            if uc_exists(full_name):
                status = "exists"
            elif DRY_RUN:
                status = "would create"
            else:
                uc_create(spec["schema"], uc_key, value,
                          f"Migrated from secret scope '{scope}'")
                digest = hashlib.sha256(value.encode()).hexdigest()
                status = "migrated" if uc_digest(full_name) == digest else "VERIFY FAILED"

            if status != "VERIFY FAILED":
                migrated.add((scope, source_key))
        except Exception as e:
            status = f"FAILED: {type(e).__name__}: {e}"[:200]

        print(f"  {status:<14} {scope}/{source_key}  ->  {full_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Delete the source scopes
# MAGIC
# MAGIC Only scopes marked `delete_scope: true` whose **every** key is now in Unity
# MAGIC Catalog. The live key list is re-read from the API, so a key you left out of
# MAGIC `mapping.yml` — or one added since — blocks the delete. This is irreversible.

# COMMAND ----------

for scope, spec in PLAN["scopes"].items():
    if not spec.get("delete_scope"):
        continue

    live = {m.key for m in w.secrets.list_secrets(scope=scope)}
    missing = live - {k for s, k in migrated if s == scope}

    if missing:
        print(f"  kept      {scope}  ({len(missing)} key(s) not migrated: {sorted(missing)})")
    elif DRY_RUN or not DELETE_SCOPES:
        print(f"  deletable {scope}  ({len(live)} secrets, all migrated)")
    else:
        w.secrets.delete_scope(scope=scope)
        print(f"  DELETED   {scope}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## After migrating
# MAGIC
# MAGIC ```sql
# MAGIC GRANT READ SECRET ON SECRET workspace.prod_credentials.password TO `data-engineers`;
# MAGIC ```
# MAGIC
# MAGIC ```python
# MAGIC # before
# MAGIC dbutils.secrets.get(scope="prod-jdbc", key="password")
# MAGIC # after
# MAGIC dbutils.secrets.get(catalog="workspace", schema="prod_credentials", key="password")
# MAGIC ```
