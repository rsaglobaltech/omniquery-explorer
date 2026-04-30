from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.domain.entities.database_schema import EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.db.base_sql_adapter import BaseSQLAdapter


class MySQLAdapter(BaseSQLAdapter):
    """
    Driven adapter for MySQL / MariaDB using aiomysql driver.
    Connection URL format: mysql+aiomysql://user:password@host:port/dbname
    """

    @property
    def engine_type(self) -> EngineType:
        return EngineType.MYSQL

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        async with engine.connect() as conn:
            db_name_row = await conn.execute(text("SELECT DATABASE()"))
            db_name: str = db_name_row.scalar()

            tables_result = await conn.execute(
                text(
                    """
                    SELECT TABLE_NAME   AS table_name,
                           TABLE_COMMENT AS table_comment
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_TYPE   = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                    """
                )
            )
            table_rows = tables_result.fetchall()

            pk_result = await conn.execute(
                text(
                    """
                    SELECT TABLE_NAME, COLUMN_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA    = DATABASE()
                      AND CONSTRAINT_NAME = 'PRIMARY'
                    """
                )
            )
            pk_set: set[tuple[str, str]] = {
                (r.TABLE_NAME, r.COLUMN_NAME) for r in pk_result
            }

            fk_result = await conn.execute(
                text(
                    """
                    SELECT kcu.TABLE_NAME, kcu.COLUMN_NAME,
                           kcu.REFERENCED_TABLE_NAME  AS ref_table,
                           kcu.REFERENCED_COLUMN_NAME AS ref_column
                    FROM information_schema.KEY_COLUMN_USAGE kcu
                    JOIN information_schema.TABLE_CONSTRAINTS tc
                      ON tc.CONSTRAINT_NAME  = kcu.CONSTRAINT_NAME
                     AND tc.TABLE_SCHEMA     = kcu.TABLE_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                      AND kcu.TABLE_SCHEMA   = DATABASE()
                    """
                )
            )
            fk_map: dict[tuple[str, str], tuple[str, str]] = {
                (r.TABLE_NAME, r.COLUMN_NAME): (r.ref_table, r.ref_column)
                for r in fk_result
            }

            tables: list[Table] = []
            for trow in table_rows:
                tname: str = trow.table_name

                cols_result = await conn.execute(
                    text(
                        """
                        SELECT COLUMN_NAME    AS column_name,
                               COLUMN_TYPE    AS column_type,
                               IS_NULLABLE    AS is_nullable,
                               COLUMN_COMMENT AS col_comment
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME   = :tname
                        ORDER BY ORDINAL_POSITION
                        """
                    ),
                    {"tname": tname},
                )

                columns = [
                    self._build_column(
                        name=c.column_name,
                        sql_type=c.column_type.upper(),
                        nullable=c.is_nullable == "YES",
                        is_pk=(tname, c.column_name) in pk_set,
                        fk_table=fk_map.get((tname, c.column_name), (None, None))[0],
                        fk_col=fk_map.get((tname, c.column_name), (None, None))[1],
                        comment=c.col_comment or None,
                    )
                    for c in cols_result
                ]

                tables.append(
                    Table(name=tname, columns=columns, comment=trow.table_comment or None)
                )

        return tables, db_name
