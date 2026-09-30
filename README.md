# Migrating secret scopes to Unity Catalog secrets

Unity Catalog secrets replace workspace-level secret scopes with a proper
three-level securable: `catalog.schema.secret`. This is a minimal working
migration — inventory, a plan in YAML, then copy and verify.

Runs on Databricks Free Edition.

| | Secret scopes | Unity Catalog secrets |
|---|---|---|
| Namespace | `scope/key`, workspace-local | `catalog.schema.secret`, metastore-wide |
| Access control | Scope ACLs (`READ`/`WRITE`/`MANAGE`) | `READ SECRET`, `WRITE SECRET`, `CREATE SECRET`, `REFERENCE SECRET` — inherited |
| Create | `POST /api/2.0/secrets/put` | `POST /api/2.1/unity-catalog/secrets` |
| Read | `dbutils.secrets.get(scope=, key=)` | `dbutils.secrets.get(catalog=, schema=, key=)` |

## The plan is a YAML file

`src/mapping.yml` is the whole migration. Left of the colon is the legacy key,
right is the Unity Catalog name:

```yaml
target_catalog: workspace

scopes:
  prod-jdbc:
    schema: prod_credentials
    keys:
      username: username
      password: password
      jdbc.url: jdbc_url          # dots are illegal in UC names

  legacy_etl:
    schema: etl_credentials
    delete_scope: true            # delete once every key above is verified
    keys:
      sftp_user: sftp_user
      SFTP_Password: sftp_password
```

Drop a key to skip it, drop a scope block to skip the scope. It lives in git, so
the migration gets reviewed in a pull request like any other change.

## You need a workspace

Sign up at the [Free Edition signup page](https://login.databricks.com/?intent=CE_SIGN_UP)
and Databricks provisions one for you.

Free Edition is serverless-only and capped at 5 concurrent job tasks, which is
plenty here. Its default catalog is `workspace`, which is what `mapping.yml`
already targets — change it if you are running this anywhere else.

## Run it

A browser and nothing else — no CLI, no local checkout, nothing to install.

**1. Get the code in.** In the sidebar: **Workspace → Create → Git folder**, paste
this repo's URL. Everything lands in one place, `mapping.yml` included, and the
workspace file editor can edit it.

**2. Run the setup.** Open `src/01_setup`, attach serverless, **Run all**. It
creates the demo scopes and the UC schemas, and the last cell prints a starting
`mapping.yml`. Migrating real scopes instead? Set the `seed_demo` widget to
`false` and only the inventory runs.

**3. Edit the plan.** Open `src/mapping.yml` in the workspace editor, paste in
what the last cell printed, and edit: drop a key to skip it, drop a scope block
to skip the scope, add `delete_scope: true` where you want cleanup.

**4. Migrate.** Open `src/02_migrate` and **Run all**. It starts with `dry_run`
set to `true`, so the first pass only prints what it would do. Flip the widget to
`false` and run again. Once the secrets are verified, set `delete_scopes` to
`true` to remove the scopes you marked.

**5. Check the result.** **Catalog → workspace → prod_credentials → Secrets**
lists what landed. Unity Catalog secrets don't show up in global search, so
browse to the schema rather than searching for them.

To put it on a schedule, open `02_migrate` and use **Schedule → Add schedule**,
which wraps the notebook in a job.

## Four things that bite

**There is no `CREATE SECRET` SQL.** Secrets are created through Catalog Explorer
or `POST /api/2.1/unity-catalog/secrets`. SQL only does grants.

**Legacy key names aren't valid UC names.** Dots are illegal, so `jdbc.url` has to
become `jdbc_url`. Hyphens are legal but force backticks in every `GRANT`. Worth
normalizing — but then two keys can collapse onto one name (`api-key` and
`api.key` both become `api_key`), silently overwriting one. `02_migrate` refuses
to run if that happens.

**`dbutils` needs a recent runtime; the API doesn't.**
`dbutils.secrets.get(catalog=, schema=, key=)` requires DBR 17.3 LTS+ or
serverless environment version 4+. The REST API has no such floor, which is why
the migration writes through REST and runs anywhere. UC secrets don't work on SQL
warehouses or in init scripts at all — if a scope feeds an init script, it can't
move.

**Scope ACLs don't map to UC privileges.** The two models are different, and
auto-translating silently over-grants, so this migration doesn't try. Read the
old ACLs off the Secrets API (`GET /api/2.0/secrets/acls/list`) and write the
`GRANT`s yourself.

## Files

```
src/01_setup.py     legacy scopes + UC schemas, then prints a starting mapping.yml
src/mapping.yml     the plan
src/02_migrate.py   copy, verify, optionally delete scopes
databricks.yml      \ bundle definition, if you would rather deploy the two
resources/          / notebooks as jobs with the Databricks CLI
```

Quotas: 100 secrets per schema, 1,000 per metastore, 61,440 characters per value.

Verification compares SHA-256 digests rather than values, so nothing sensitive
lands in cell output. A scope is deleted only when every key currently in it is
confirmed present in Unity Catalog.

Docs: [Secrets in Unity Catalog](https://docs.databricks.com/aws/en/security/secrets/unity-catalog-secrets)
