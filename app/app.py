import os, json, sqlite3, threading
from datetime import datetime
from threading import Lock
from flask import Flask, render_template, request, jsonify
import requests
from dotenv import load_dotenv

# === Paths fijos para que siempre encuentre templates/static ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

    # === Config ===
    PORT = int(os.getenv("PORT", "5000"))
    NODE_NAME = os.getenv("NODE_NAME", f"Sucursal_{PORT}")
    peers_env = os.getenv("PEERS", "5000,5001,5002")
    SUCURSALES = [int(p.strip()) for p in peers_env.split(",") if p.strip().isdigit()]
    SUCURSALES = [p for p in SUCURSALES if p != PORT]

    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), f"data_{PORT}")
    DB_PATH = os.path.join(DATA_DIR, "db.sqlite3")
    os.makedirs(DATA_DIR, exist_ok=True)

    _db_lock = Lock()  # serialize writes from threads

    # === DB helpers (SQLite) ===
    def _db():
        conn = getattr(app, "_db_conn", None)
        if conn is None:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            app._db_conn = conn
        return conn

    def _ensure_db():
        conn = _db()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS empleados(
            dni TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            puesto TEXT NOT NULL,
            sucursal TEXT NOT NULL
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS historial(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,        -- read | write | update
            dni TEXT NOT NULL,
            fecha TEXT NOT NULL,       -- 'YYYY-MM-DD HH:MM:SS'
            sucursal TEXT NOT NULL
        )""")
        conn.commit()

    def _row_to_dict(row): return {k: row[k] for k in row.keys()}

    # snapshots para API/sync
    def get_empleados_dict():
        cur = _db().cursor()
        cur.execute("SELECT * FROM empleados")
        return {r["dni"]: _row_to_dict(r) for r in cur.fetchall()}

    def get_historial_list():
        cur = _db().cursor()
        cur.execute("SELECT tipo, dni, fecha, sucursal FROM historial ORDER BY fecha DESC, id DESC")
        return [dict(r) for r in cur.fetchall()]

    # === Sync entre nodos (merge idempotente) ===
    def sincronizar_con_sucursales():
        for puerto in SUCURSALES:
            try:
                r = requests.get(f"http://127.0.0.1:{puerto}/obtener_todo", timeout=2)
                if r.status_code != 200:
                    continue
                datos = r.json()
                emp_rem = datos.get("empleados", {})
                hist_rem = datos.get("historial", [])

                with _db_lock:
                    conn = _db(); cur = conn.cursor()

                    # merge empleados: insertar si no existe
                    for dni, e in emp_rem.items():
                        cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
                        if not cur.fetchone():
                            cur.execute(
                                "INSERT INTO empleados(dni, nombre, apellido, puesto, sucursal) VALUES(?,?,?,?,?)",
                                (e["dni"], e["nombre"], e["apellido"], e["puesto"], e["sucursal"])
                            )

                    # merge historial (idempotente por 4 campos)
                    for op in hist_rem:
                        cur.execute("""SELECT 1 FROM historial
                                       WHERE tipo=? AND dni=? AND fecha=? AND sucursal=?""",
                                    (op["tipo"], op["dni"], op["fecha"], op["sucursal"]))
                        if not cur.fetchone():
                            cur.execute("""INSERT INTO historial(tipo, dni, fecha, sucursal)
                                           VALUES(?,?,?,?)""",
                                        (op["tipo"], op["dni"], op["fecha"], op["sucursal"]))
                    conn.commit()
            except Exception as e:
                print(f"[WARN] Peer {puerto} no disponible: {e}")

    # === Operaciones ===
    def op_agregar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if cur.fetchone():
                return False, "El empleado ya existe"

            cur.execute(
                "INSERT INTO empleados(dni, nombre, apellido, puesto, sucursal) VALUES(?,?,?,?,?)",
                (dni, nombre, apellido, puesto, NODE_NAME)
            )
            cur.execute(
                "INSERT INTO historial(tipo, dni, fecha, sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("write", dni, NODE_NAME)
            )
            conn.commit()
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return True, "Empleado agregado correctamente"

    def op_editar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if not cur.fetchone():
                return False, "El empleado no existe"

            cur.execute("UPDATE empleados SET nombre=?, apellido=?, puesto=? WHERE dni=?",
                        (nombre, apellido, puesto, dni))
            cur.execute(
                "INSERT INTO historial(tipo, dni, fecha, sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("update", dni, NODE_NAME)
            )
            conn.commit()
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return True, "Empleado editado correctamente"

    def op_consultar(dni):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT * FROM empleados WHERE dni=?", (dni,))
            row = cur.fetchone()
            if not row:
                return None, "El empleado no existe"
            cur.execute(
                "INSERT INTO historial(tipo, dni, fecha, sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("read", dni, NODE_NAME)
            )
            conn.commit()
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return _row_to_dict(row), "Consulta exitosa"

    # === Rutas UI/API ===
    @app.get("/")
    def index():
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return render_template("index.html", sucursal=NODE_NAME, puerto=PORT)

    @app.post("/agregar_empleado")
    def agregar_empleado_endpoint():
        ok, msg = op_agregar(request.form["dni"], request.form["nombre"],
                             request.form["apellido"], request.form["puesto"])
        return jsonify({"exito": ok, "mensaje": msg})

    @app.post("/editar_empleado")
    def editar_empleado_endpoint():
        ok, msg = op_editar(request.form["dni"], request.form["nombre"],
                            request.form["apellido"], request.form["puesto"])
        return jsonify({"exito": ok, "mensaje": msg})

    @app.post("/consultar_empleado")
    def consultar_empleado_endpoint():
        emp, msg = op_consultar(request.form["dni"])
        if emp:
            return jsonify({"exito": True, "mensaje": msg, "empleado": emp})
        return jsonify({"exito": False, "mensaje": msg})

    # APIs para sync/visualización
    @app.get("/obtener_historial")
    def obtener_historial_endpoint():
        return jsonify(get_historial_list())

    @app.get("/obtener_empleados")
    def obtener_empleados_endpoint():
        return jsonify(get_empleados_dict())

    @app.get("/obtener_todo")
    def obtener_todo_endpoint():
        return jsonify({"empleados": get_empleados_dict(), "historial": get_historial_list()})

    @app.get("/ver_historial")
    def ver_historial_endpoint():
        sincronizar_con_sucursales()
        return jsonify({"empleados": get_empleados_dict(), "historial": get_historial_list()})

    # === Página para ver la BD (tablas) ===
    @app.get("/admin/db")
    def admin_db():
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT * FROM empleados ORDER BY dni")
        empleados = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM historial ORDER BY fecha DESC, id DESC")
        historial = [dict(r) for r in cur.fetchall()]
        return render_template("db.html",
                               sucursal=NODE_NAME, puerto=PORT,
                               empleados=empleados, historial=historial)

    _ensure_db()
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(port=int(os.getenv("PORT", "5000")), debug=True)
