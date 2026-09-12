import psycopg2
from psycopg2.extras import DictCursor
import pymysql
from pymysql.cursors import DictCursor as MyDictCursor
from pymysql.constants import CLIENT


class DBManager:
    def __init__(self, config):
        self.config = config['db']

    def get_connection(self):
        return psycopg2.connect(
            host=self.config['host'],
            port=self.config['port'],
            user=self.config['user'],
            password=self.config['password'],
            dbname=self.config['database']
        )

    def test_connection(self):
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            return True, None
        except Exception as e:
            return False, str(e)

    def execute_query(self, query_template, nps_list):
        if not nps_list:
            return []
            
        try:
            # Format NPs for SQL IN clause ('NP1', 'NP2')
            nps_formatted = ",".join([f"'{str(np).strip()}'" for np in nps_list])
            final_query = query_template.replace("{NPs}", nps_formatted).replace("{NP}", nps_formatted)
            
            conn = self.get_connection()
            cur = conn.cursor(cursor_factory=DictCursor)
            cur.execute(final_query)
            results = cur.fetchall()
            cur.close()
            conn.close()
            
            return [dict(r) for r in results]
        except Exception as e:
            raise Exception(f"Database query error: {str(e)}")

    def execute_raw(self, query):
        """Ejecuta el query tal cual está escrito (sin placeholders) y devuelve
        la lista de filas como dicts. Útil para queries independientes como el Query EPTS."""
        conn = self.get_connection()
        try:
            cur = conn.cursor(cursor_factory=DictCursor)
            cur.execute(query)
            results = cur.fetchall()
            cur.close()
            return [dict(r) for r in results]
        finally:
            conn.close()


class DBManagerMySQL:
    """Gestor de conexiones MySQL/MariaDB para los orígenes WMS de Producto Terminado.
    Recibe un dict con host, port, user, password, database."""

    def __init__(self, conn_config):
        self.conn_config = conn_config

    def get_connection(self):
        return pymysql.connect(
            host=self.conn_config['host'],
            port=int(self.conn_config.get('port', 3306)),
            user=self.conn_config['user'],
            password=self.conn_config['password'],
            database=self.conn_config['database'],
            charset='utf8mb4',
            cursorclass=MyDictCursor,
            connect_timeout=10,
            read_timeout=60,
            client_flag=CLIENT.FOUND_ROWS,
        )

    def test_connection(self):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True, None
        except Exception as e:
            return False, str(e)

    def execute_raw(self, query):
        """Ejecuta el query tal cual (sin placeholders) y devuelve filas como dicts."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                results = cur.fetchall()
        return [dict(r) for r in results]

    def execute_write(self, query, get_last_id=False):
        """Ejecuta un UPDATE/INSERT/DELETE contra MySQL, hace commit y devuelve
        (rowcount, lastrowid). lastrowid solo se pide si get_last_id es True."""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rowcount = cur.rowcount
                lastid = cur.lastrowid if get_last_id else None
                conn.commit()
        return rowcount, lastid

    def execute_many_write(self, queries):
        """Ejecuta varias sentencias de escritura en UNA sola transacción:
        todas se confirman juntas o, si alguna falla, se hace rollback de todas.
        Devuelve la lista de filas afectadas."""
        with self.get_connection() as conn:
            try:
                rowcounts = []
                with conn.cursor() as cur:
                    for query in queries:
                        cur.execute(query)
                        rowcounts.append(cur.rowcount)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return rowcounts
