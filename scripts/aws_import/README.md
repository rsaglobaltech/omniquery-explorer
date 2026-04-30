# Scripts de importacion a AWS RDS (PostgreSQL, MySQL, Oracle)

Cada script importa **1 ZIP de `dbs/`** a un motor especifico, creando tablas automaticamente desde las cabeceras CSV.

## Reparto elegido

- PostgreSQL:
  - `import_airline_loyalty_program_postgres.sh`
  - `import_bank_customer_churn_postgres.sh`
  - `import_hospital_patient_records_postgres.sh`
  - `import_restaurant_orders_postgres.sh`
- MySQL:
  - `import_airline_passenger_satisfaction_mysql.sh`
  - `import_maven_fuzzy_factory_mysql.sh`
  - `import_streaming_video_subscriptions_mysql.sh`
  - `import_uk_train_rides_mysql.sh`
- Oracle:
  - `import_airlines_airports_flights_oracle.sh`
  - `import_nyc_taxi_trips_oracle.sh`
  - `import_sp500_stock_prices_oracle.sh`

## Variables por motor

### PostgreSQL

```bash
export AWS_PG_HOST=tu-endpoint-rds
export AWS_PG_PORT=5432
export AWS_PG_DB=tu_database
export AWS_PG_USER=tu_usuario
export AWS_PG_PASSWORD=tu_password
```

### MySQL

```bash
export AWS_MYSQL_HOST=tu-endpoint-rds
export AWS_MYSQL_PORT=3306
export AWS_MYSQL_DB=tu_database
export AWS_MYSQL_USER=tu_usuario
export AWS_MYSQL_PASSWORD=tu_password
```

### Oracle

```bash
export AWS_ORACLE_HOST=tu-endpoint-rds
export AWS_ORACLE_PORT=1521
export AWS_ORACLE_SERVICE=tu_service_name
export AWS_ORACLE_USER=tu_usuario
export AWS_ORACLE_PASSWORD=tu_password
```

## Dependencias locales

- Todos: `unzip`, `python3`
- PostgreSQL: `psql`
- MySQL: `mysql`
- Oracle: `sqlplus`, `sqlldr` (Oracle Instant Client)

## Uso con Dev Container (sin instalar clientes en tu host)

1. Abre el repo en VS Code.
2. Ejecuta `Dev Containers: Reopen in Container`.
3. Dentro del contenedor ya tendras:
   - `psql`
   - `mysql`
   - `python3`
   - `unzip`
   - `poetry`

Para Oracle (opcional), instala el cliente dentro del contenedor:

```bash
setup-oracle-client \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-basiclite-*.zip \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-sqlplus-*.zip \
  /workspaces/omniquery-explorer/.devcontainer/oracle-client/instantclient-tools-*.zip
```

Ver detalles en:
- `.devcontainer/oracle-client/README.md`

## Ejecucion

```bash
chmod +x scripts/aws_import/*.sh scripts/aws_import/lib/aws_import_common.sh
./scripts/aws_import/import_bank_customer_churn_postgres.sh
```

## Notas

- Los nombres de tabla se construyen como `prefix_nombre_csv`.
- Las columnas se crean como texto (`TEXT`, `LONGTEXT`, `VARCHAR2(4000)`) para simplificar cargas iniciales.
- En Oracle, las tablas se eliminan y recrean antes de cada carga.
