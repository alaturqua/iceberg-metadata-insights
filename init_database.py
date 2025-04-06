import trino
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_connection() -> trino.dbapi.Connection:
    """Initializes a connection to Trino.
    Returns:
        trino.dbapi.Connection: A connection object to interact with Trino.
    """
    try:
        conn = trino.dbapi.connect(
            host="localhost",
            port=8088,
            user="trino",
            catalog="iceberg",
            schema="default",
            http_scheme="http",
        )
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to Trino: {e}")
        return None


def init_database() -> trino.dbapi.Connection:
    """Initializes the database connection and returns the connection object."""
    conn = init_connection()
    cursor = conn.cursor()

    # Drop and create schema
    queries = [
        "DROP SCHEMA IF EXISTS iceberg.gold CASCADE",
        "CREATE SCHEMA IF NOT EXISTS iceberg.gold",
    ]

    # Create tables and perform operations
    queries.extend(
        [
            # Create lineitem table
            """
        CREATE or REPLACE TABLE iceberg.gold.lineitem
        WITH (
            partitioning = ARRAY['year(receiptdate)']
        )
        AS 
        SELECT * FROM tpch.tiny.lineitem
        """,
            # Create orders table
            """
        CREATE or REPLACE TABLE iceberg.gold.orders 
        WITH (
            partitioning = ARRAY['year(orderdate)']
        )
        AS 
        SELECT * FROM tpch.tiny.orders
        """,
            # Insert new records - lineitem
            """
        INSERT INTO iceberg.gold.lineitem 
        SELECT * FROM tpch.tiny.lineitem LIMIT 5
        """,
            # Insert new records - orders
            """
        INSERT INTO iceberg.gold.orders 
        SELECT * FROM tpch.tiny.orders LIMIT 5
        """,
            # Delete records - lineitem
            """
        DELETE FROM iceberg.gold.lineitem 
        WHERE quantity > 45
        """,
            # Delete records - orders
            """
        DELETE FROM iceberg.gold.orders 
        WHERE orderstatus = 'F'
        """,
            # Update records - lineitem
            """
        UPDATE iceberg.gold.lineitem 
        SET discount = discount * 1.1 
        WHERE shipdate > DATE '1995-01-01'
        """,
            # Update records - orders
            """
        UPDATE iceberg.gold.orders 
        SET totalprice = totalprice * 1.1 
        WHERE orderdate > DATE '1995-01-01'
        """,
            # Merge records - lineitem
            """
        MERGE INTO iceberg.gold.lineitem target
        USING (
            SELECT DISTINCT orderkey, partkey, suppkey, linenumber, quantity, extendedprice, 
                   discount, tax, returnflag, linestatus, shipdate, commitdate, receiptdate, 
                   shipinstruct, shipmode, comment 
            FROM tpch.tiny.lineitem 
            WHERE orderkey = 1
        ) source
        ON target.orderkey = source.orderkey 
           AND target.partkey = source.partkey 
           AND target.suppkey = source.suppkey
           AND target.linenumber = source.linenumber
        WHEN MATCHED THEN
            UPDATE SET extendedprice = source.extendedprice * 1.1
        WHEN NOT MATCHED THEN
            INSERT (orderkey, partkey, suppkey, linenumber, quantity, extendedprice, discount, tax, returnflag, linestatus, shipdate, commitdate, receiptdate, shipinstruct, shipmode, comment)
            VALUES (source.orderkey, source.partkey, source.suppkey, source.linenumber, source.quantity, source.extendedprice * 1.1, source.discount, source.tax, source.returnflag, source.linestatus, source.shipdate, source.commitdate, source.receiptdate, source.shipinstruct, source.shipmode, source.comment)
        """,
            # Merge records - orders
            """
        MERGE INTO iceberg.gold.orders target
        USING (
            SELECT DISTINCT orderkey, custkey, orderstatus, totalprice, orderdate, 
                   orderpriority, clerk, shippriority, comment
            FROM tpch.tiny.orders 
            WHERE orderkey = 1
        ) source
        ON target.orderkey = source.orderkey
        WHEN MATCHED THEN
            UPDATE SET totalprice = source.totalprice * 1.1
        WHEN NOT MATCHED THEN
            INSERT (orderkey, custkey, orderstatus, totalprice, orderdate, orderpriority, 
                   clerk, shippriority, comment)
            VALUES (source.orderkey, source.custkey, source.orderstatus, source.totalprice * 1.1, 
                   source.orderdate, source.orderpriority, source.clerk, source.shippriority, 
                   source.comment)
        """,
        ]
    )

    # Execute all queries
    for query in queries:
        try:
            cursor.execute(query)
            logger.info(f"Successfully executed: {query}")
        except Exception as e:
            logger.error(f"Failed to execute {query}: {e}")


if __name__ == "__main__":
    logger.info("Connection to Trino established successfully.")
    init_database()
    logger.info("Database initialized successfully.")
