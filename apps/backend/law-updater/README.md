# law-updater

Minimal runtime packaging for `apps/backend/legal-pipeline/scripts/run_incremental_law_update.py`.

- Runtime code is copied into this directory so `legal-pipeline` stays untouched.
- Embeddings are external-API only. Local sentence-transformer execution is intentionally removed.
- Base install is intended for `--skip-embed` or API-backed embeddings.
- Docker build context should be `apps/backend/law-updater/`.
- The image does not define a default command. Pass the full job command from Coolify.

Examples:

```bash
docker build -f apps/backend/law-updater/Dockerfile apps/backend/law-updater
```

Coolify scheduled job command example:

```bash
python scripts/run_incremental_law_update.py --reg-dt 20260330
```

If you want the date to be added automatically, use:

```bash
python scripts/run_incremental_law_update_auto_date.py
```

Options:

```bash
python scripts/run_incremental_law_update_auto_date.py --days-offset -1
python scripts/run_incremental_law_update_auto_date.py --timezone Asia/Seoul --skip-embed
```

The wrapper uses `Asia/Seoul` by default and formats `--reg-dt` as `YYYYMMDD`.
