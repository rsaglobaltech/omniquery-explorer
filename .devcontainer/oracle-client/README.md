# Oracle Instant Client (opcional)

Por licencia de Oracle, no se incluyen binarios en este repo.

Para habilitar scripts Oracle dentro del Dev Container:

1. Descarga desde Oracle Instant Client para Linux x86-64:
   - `instantclient-basiclite-*.zip` (o `instantclient-basic-*.zip`)
   - `instantclient-sqlplus-*.zip`
   - `instantclient-tools-*.zip` (incluye `sqlldr`)
2. Guarda los 3 ZIP en esta carpeta (`.devcontainer/oracle-client/`).
3. Ya dentro del Dev Container, ejecuta:

```bash
setup-oracle-client \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-basiclite-*.zip \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-sqlplus-*.zip \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-tools-*.zip
```

Luego podras ejecutar scripts Oracle de `scripts/aws_import/`.
