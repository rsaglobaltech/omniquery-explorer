from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.domain.entities.database_schema import EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.db.base_sql_adapter import BaseSQLAdapter


class PostgreSQLAdapter(BaseSQLAdapter):
    """
    Driven adapter for PostgreSQL using asyncpg driver.
    Connection URL format: postgresql+asyncpg://user:password@host:port/dbname
    """

    @property
    def engine_type(self) -> EngineType:
        return EngineType.POSTGRESQL

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        async with engine.connect() as conn:
            # Fetch current database name
            db_name_row = await conn.execute(text("SELECT current_database()"))
            db_name: str = db_name_row.scalar()

            # Fetch all user tables (exclude system schemas)
            tables_result = await conn.execute(
                text(
                    """
                    SELECT table_name, obj_description(
                        (quote_ident(table_schema)||'.'||quote_ident(table_name))::regclass, 'pg_class'
                    ) AS table_comment
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                )
            )
            table_rows = tables_result.fetchall()

            # Fetch PK columns
            pk_result = await conn.execute(
                text(
                    """
                    SELECT kcu.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema    = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
                    """
                )
            )
            pk_set: set[tuple[str, str]] = {
                (r.table_name, r.column_name) for r in pk_result
            }

            # Fetch FK columns
            fk_result = await conn.execute(
                text(
                    """
                    SELECT kcu.table_name, kcu.column_name,
                           ccu.table_name  AS ref_table,
                           ccu.column_name AS ref_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema    = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
                    """
                )
            )
            fk_map: dict[tuple[str, str], tuple[str, str]] = {
                (r.table_name, r.column_name): (r.ref_table, r.ref_column)
                for r in fk_result
            }

            tables: list[Table] = []
            for trow in table_rows:
                tname: str = trow.table_name

                cols_result = await conn.execute(
                    text(
                        """
                        SELECT column_name, udt_name, is_nullable,
                               col_description(
                                   (quote_ident(table_schema)||'.'||quote_ident(table_name))::regclass,
                                   ordinal_position
                               ) AS col_comment
                        FROM information_schema.columns
                        WHERE table_name = :tname
                          AND table_schema NOT IN ('pg_catalog', 'information_schema')
                        ORDER BY ordinal_position
                        """
                    ),
                    {"tname": tname},
                )

                columns = [
                    self._build_column(
                        name=c.column_name,
                        sql_type=c.udt_name.upper(),
                        nullable=c.is_nullable == "YES",
                        is_pk=(tname, c.column_name) in pk_set,
                        fk_table=fk_map.get((tname, c.column_name), (None, None))[0],
                        fk_col=fk_map.get((tname, c.column_name), (None, None))[1],
                        comment=c.col_comment,
                    )
                    for c in cols_result
                ]

                tables.append(Table(name=tname, columns=columns, comment=trow.table_comment))

        return tables, db_name
