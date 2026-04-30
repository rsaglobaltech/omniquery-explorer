from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.domain.entities.database_schema import EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.db.base_sql_adapter import BaseSQLAdapter


class OracleAdapter(BaseSQLAdapter):
    """
    Driven adapter for Oracle Database using python-oracledb (thin mode).
    Connection URL format: oracle+oracledb_async://user:password@host:port/?service_name=ORCLPDB1

    Note: Oracle's information_schema equivalent is ALL_*/USER_* dictionary views.
          We query ALL_TABLES, ALL_TAB_COLUMNS, ALL_CONSTRAINTS, ALL_CONS_COLUMNS.
    """

    @property
    def engine_type(self) -> EngineType:
        return EngineType.ORACLE

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        async with engine.connect() as conn:
            db_name_row = await conn.execute(
                text("SELECT SYS_CONTEXT('USERENV','DB_NAME') FROM DUAL")
            )
            db_name: str | None = db_name_row.scalar()

            schema_row = await conn.execute(
                text("SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM DUAL")
            )
            current_schema: str = schema_row.scalar()

            tables_result = await conn.execute(
                text(
                    """
                    SELECT t.TABLE_NAME,
                           c.COMMENTS AS table_comment
                    FROM ALL_TABLES t
                    LEFT JOIN ALL_TAB_COMMENTS c
                      ON c.OWNER = t.OWNER AND c.TABLE_NAME = t.TABLE_NAME
                    WHERE t.OWNER = :schema
                    ORDER BY t.TABLE_NAME
                    """
                ),
                {"schema": current_schema},
            )
            table_rows = tables_result.fetchall()

            # PK columns
            pk_result = await conn.execute(
                text(
                    """
                    SELECT acc.TABLE_NAME, acc.COLUMN_NAME
                    FROM ALL_CONSTRAINTS  ac
                    JOIN ALL_CONS_COLUMNS acc
                      ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                     AND ac.OWNER           = acc.OWNER
                    WHERE ac.CONSTRAINT_TYPE = 'P'
                      AND ac.OWNER = :schema
                    """
                ),
                {"schema": current_schema},
            )
            pk_set: set[tuple[str, str]] = {
                (r.TABLE_NAME, r.COLUMN_NAME) for r in pk_result
            }

            # FK columns
            fk_result = await conn.execute(
                text(
                    """
                    SELECT acc.TABLE_NAME,  acc.COLUMN_NAME,
                           rcc.TABLE_NAME  AS ref_table,
                           rcc.COLUMN_NAME AS ref_column
                    FROM ALL_CONSTRAINTS  ac
                    JOIN ALL_CONS_COLUMNS acc
                      ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                     AND ac.OWNER           = acc.OWNER
                    JOIN ALL_CONS_COLUMNS rcc
                      ON ac.R_CONSTRAINT_NAME = rcc.CONSTRAINT_NAME
                     AND ac.R_OWNER           = rcc.OWNER
                    WHERE ac.CONSTRAINT_TYPE = 'R'
                      AND ac.OWNER = :schema
                    """
                ),
                {"schema": current_schema},
            )
            fk_map: dict[tuple[str, str], tuple[str, str]] = {
                (r.TABLE_NAME, r.COLUMN_NAME): (r.ref_table, r.ref_column)
                for r in fk_result
            }

            tables: list[Table] = []
            for trow in table_rows:
                tname: str = trow.TABLE_NAME

                cols_result = await conn.execute(
                    text(
                        """
                        SELECT c.COLUMN_NAME,
                               c.DATA_TYPE ||
                                 CASE
                                   WHEN c.DATA_TYPE IN ('VARCHAR2','NVARCHAR2','CHAR')
                                     THEN '(' || c.CHAR_LENGTH || ')'
                                   WHEN c.DATA_TYPE = 'NUMBER' AND c.DATA_PRECISION IS NOT NULL
                                     THEN '(' || c.DATA_PRECISION || ',' || c.DATA_SCALE || ')'
                                   ELSE ''
                                 END AS column_type,
                               c.NULLABLE,
                               cc.COMMENTS AS col_comment
                        FROM ALL_TAB_COLUMNS c
                        LEFT JOIN ALL_COL_COMMENTS cc
                          ON cc.OWNER = c.OWNER
                         AND cc.TABLE_NAME  = c.TABLE_NAME
                         AND cc.COLUMN_NAME = c.COLUMN_NAME
                        WHERE c.OWNER      = :schema
                          AND c.TABLE_NAME = :tname
                        ORDER BY c.COLUMN_ID
                        """
                    ),
                    {"schema": current_schema, "tname": tname},
                )

                columns = [
                    self._build_column(
                        name=c.COLUMN_NAME,
                        sql_type=c.column_type,
                        nullable=c.NULLABLE == "Y",
                        is_pk=(tname, c.COLUMN_NAME) in pk_set,
                        fk_table=fk_map.get((tname, c.COLUMN_NAME), (None, None))[0],
                        fk_col=fk_map.get((tname, c.COLUMN_NAME), (None, None))[1],
                        comment=c.col_comment,
                    )
                    for c in cols_result
                ]

                tables.append(
                    Table(name=tname, columns=columns, comment=trow.table_comment)
                )

        return tables, db_name
