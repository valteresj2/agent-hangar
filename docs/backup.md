# Backup, restore and upgrade

What to protect:

| | Where | Without it |
|---|---|---|
| **Database** | Postgres: agents, versions, catalog, users, keys, usage, audit | everything is lost |
| **`HANGAR_SECRET_KEY`** | `.env` (Docker) or the `<release>-secrets` Secret (Kubernetes) | LLM keys stored in the database cannot be decrypted |
| Agent memory | Neo4j or FalkorDB volume | agents forget what they learned (the rest works) |

Keep the secret key **in a vault, apart from the backups**: a backup file alone does not expose LLM keys.

## Docker

```bash
hangar backup                              # pg_dump to .hangar/backups/hangar-<date>-manual.dump
hangar backup --out /mnt/nas/hangar        # somewhere else
hangar restore .hangar/backups/hangar-20261001-030000-manual.dump
hangar upgrade --version 0.12.0            # backup, new images, start, hangar doctor
```

- **`restore`** first saves the current state (`…-antes-de-restaurar.dump`). Then it stops the central, restores in a
  single transaction and starts the central again. The migrations bring an older backup up to date on start.
- **`upgrade`** takes a backup, sets `HANGAR_VERSION` in `.env` (the previous file is kept as `.env.bak-*`), pulls
  and starts the new images, waits for the central and runs `hangar doctor`. If something fails, it prints how to go
  back. With images built from the checkout (`HANGAR_REGISTRY=agent-hangar`), run `git pull` first; `upgrade` then
  rebuilds.

Schedule `hangar backup` with cron or Task Scheduler, and copy `.hangar/backups/` off the machine.

## Kubernetes

Turn on the chart's backup:

```yaml
backup:
  enabled: true
  schedule: "0 3 * * *"   # daily pg_dump to a volume
  keep: 14
  beforeUpgrade: true     # pg_dump before every helm upgrade; if it fails, the upgrade does not happen
  storage: 20Gi
  image: postgres:16      # same major version as the server, or newer
```

- The volume (`<release>-backup`) survives `helm uninstall`.
- For an extra backup on demand:
  `kubectl -n agent-hangar create job backup-now --from=cronjob/agent-hangar-backup`.
- With the chart's Postgres, `hangar backup --namespace agent-hangar` and `hangar restore … --namespace agent-hangar`
  also work from your machine.
- **Managed database** (Cloud SQL, Azure Database, RDS/Aurora): use the provider's automatic backups and
  point-in-time recovery. The Terraform in [`deploy/terraform`](../deploy/terraform/README.md) turns them on with 14 days.
  The chart job also works against them as an extra logical copy.
- **Volumes:** for the graph database and the backup volume, use VolumeSnapshots or Velero.

Upgrading: `git pull` (or the new chart version), then `hangar setup --target kubernetes` or
`helm upgrade --reuse-values`. With `beforeUpgrade`, the dump runs first; migrations run when the new central
starts, and with 2+ replicas the update is rolling.

## Agent memory

The Community editions of Neo4j and FalkorDB have no online backup:
- **Neo4j:** stop `neo4j` and run `neo4j-admin database dump`, or snapshot the volume.
- **FalkorDB (Redis):** copy the `dump.rdb` file.

Memory can also be rebuilt: new conversations feed it again.
