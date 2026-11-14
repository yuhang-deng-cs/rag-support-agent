## What & why

## Checklist
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `pytest` passes (and against PostgreSQL if you touched data access — see CONTRIBUTING.md)
- [ ] New tenant-owned tables are added to `TENANT_OWNED_TABLES` and covered by an RLS test
