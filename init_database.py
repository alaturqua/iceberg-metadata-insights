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
            port=8090,
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

    # Drop and create schemas
    queries = [
        "DROP SCHEMA IF EXISTS iceberg.gold CASCADE",
        "CREATE SCHEMA IF NOT EXISTS iceberg.gold",
        "DROP SCHEMA IF EXISTS iceberg.silver CASCADE",
        "CREATE SCHEMA IF NOT EXISTS iceberg.silver",
    ]

    # Create tables and perform operations for gold schema
    queries.extend(
        [
            # Create lineitem table in gold schema
            """
        CREATE or REPLACE TABLE iceberg.gold.lineitem
        WITH (
            partitioning = ARRAY['year(receiptdate)']
        )
        AS 
        SELECT * FROM tpch.tiny.lineitem
        """,
            # Create orders table in gold schema
            """
        CREATE or REPLACE TABLE iceberg.gold.orders 
        WITH (
            partitioning = ARRAY['year(orderdate)']
        )
        AS 
        SELECT * FROM tpch.tiny.orders
        """,
            # Insert new records - lineitem (gold)
            """
        INSERT INTO iceberg.gold.lineitem 
        SELECT * FROM tpch.tiny.lineitem LIMIT 5
        """,
            # Insert new records - orders (gold)
            """
        INSERT INTO iceberg.gold.orders 
        SELECT * FROM tpch.tiny.orders LIMIT 5
        """,
            # Delete records - lineitem (gold)
            """
        DELETE FROM iceberg.gold.lineitem 
        WHERE quantity > 45
        """,
            # Delete records - orders (gold)
            """
        DELETE FROM iceberg.gold.orders 
        WHERE orderstatus = 'F'
        """,
            # Update records - lineitem (gold)
            """
        UPDATE iceberg.gold.lineitem 
        SET discount = discount * 1.1 
        WHERE shipdate > DATE '1995-01-01'
        """,
            # Update records - orders (gold)
            """
        UPDATE iceberg.gold.orders 
        SET totalprice = totalprice * 1.1 
        WHERE orderdate > DATE '1995-01-01'
        """,
            # Merge records - lineitem (gold)
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
            # Merge records - orders (gold)
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

    # Create tables and perform operations for silver schema
    queries.extend(
        [
            # Create lineitem table in silver schema
            """
        CREATE or REPLACE TABLE iceberg.silver.lineitem
        WITH (
            partitioning = ARRAY['month(receiptdate)']
        )
        AS 
        SELECT * FROM iceberg.gold.lineitem
        """,
            # Create orders table in silver schema
            """
        CREATE or REPLACE TABLE iceberg.silver.orders 
        WITH (
            partitioning = ARRAY['month(orderdate)']
        )
        AS 
        SELECT * FROM iceberg.gold.orders
        """,
            # Insert new records - lineitem (silver)
            """
        INSERT INTO iceberg.silver.lineitem 
        SELECT * FROM iceberg.gold.lineitem LIMIT 10
        """,
            # Insert new records - orders (silver)
            """
        INSERT INTO iceberg.silver.orders 
        SELECT * FROM iceberg.gold.orders LIMIT 10
        """,
            # Delete records - lineitem (silver)
            """
        DELETE FROM iceberg.silver.lineitem 
        WHERE quantity < 5
        """,
            # Delete records - orders (silver)
            """
        DELETE FROM iceberg.silver.orders 
        WHERE orderstatus = 'O'
        """,
            # Update records - lineitem (silver)
            """
        UPDATE iceberg.silver.lineitem 
        SET discount = discount * 0.9 
        WHERE shipdate < DATE '1995-01-01'
        """,
            # Update records - orders (silver)
            """
        UPDATE iceberg.silver.orders 
        SET totalprice = totalprice * 0.9 
        WHERE orderdate < DATE '1995-01-01'
        """,
            # Merge records - lineitem (silver)
            """
        MERGE INTO iceberg.silver.lineitem target
        USING (
            SELECT DISTINCT orderkey, partkey, suppkey, linenumber, quantity, extendedprice, 
                   discount, tax, returnflag, linestatus, shipdate, commitdate, receiptdate, 
                   shipinstruct, shipmode, comment 
            FROM iceberg.gold.lineitem 
            WHERE orderkey = 2
        ) source
        ON target.orderkey = source.orderkey 
           AND target.partkey = source.partkey 
           AND target.suppkey = source.suppkey
           AND target.linenumber = source.linenumber
        WHEN MATCHED THEN
            UPDATE SET extendedprice = source.extendedprice * 0.9
        WHEN NOT MATCHED THEN
            INSERT (orderkey, partkey, suppkey, linenumber, quantity, extendedprice, discount, tax, returnflag, linestatus, shipdate, commitdate, receiptdate, shipinstruct, shipmode, comment)
            VALUES (source.orderkey, source.partkey, source.suppkey, source.linenumber, source.quantity, source.extendedprice * 0.9, source.discount, source.tax, source.returnflag, source.linestatus, source.shipdate, source.commitdate, source.receiptdate, source.shipinstruct, source.shipmode, source.comment)
        """,
            # Merge records - orders (silver)
            """
        MERGE INTO iceberg.silver.orders target
        USING (
            SELECT DISTINCT orderkey, custkey, orderstatus, totalprice, orderdate, 
                   orderpriority, clerk, shippriority, comment
            FROM iceberg.gold.orders 
            WHERE orderkey = 2
        ) source
        ON target.orderkey = source.orderkey
        WHEN MATCHED THEN
            UPDATE SET totalprice = source.totalprice * 0.9
        WHEN NOT MATCHED THEN
            INSERT (orderkey, custkey, orderstatus, totalprice, orderdate, orderpriority, 
                   clerk, shippriority, comment)
            VALUES (source.orderkey, source.custkey, source.orderstatus, source.totalprice * 0.9, 
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
