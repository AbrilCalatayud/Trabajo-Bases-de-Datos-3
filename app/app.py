import os, sqlite3, threading, time
from datetime import datetime
from threading import Lock
from flask import Flask, render_template, request, jsonify, make_response
import requests
from dotenv import load_dotenv

# === Paths fijos para que siempre encuentre templates/static ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

    # === Configuración ===
    PORT = int(os.getenv("PORT", "5000"))
    HOST = os.getenv("HOST", "0.0.0.0")
    NODE_NAME = f"Sucursal_{PORT}"

    # Peers "host:puerto,host:puerto,host:puerto"
    peers_env = os.getenv("PEERS", "127.0.0.1:5000,127.0.0.1:5001,127.0.0.1:5002")
    PEERS = [p.strip() for p in peers_env.split(",") if ":" in p]

    # Para evitar auto-llamarse si definís tu IP pública (Radmin/WiFi)
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", None)
    MY_ADDR = f"{PUBLIC_HOST}:{PORT}" if PUBLIC_HOST else None

    # Control de sincronización
    AUTO_SYNC = int(os.getenv("AUTO_SYNC", "0"))            # 0 = manual, 1 = al modificar
    SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "600"))  # 10 minutos por defecto

    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), f"data_{PORT}")
    DB_PATH = os.path.join(DATA_DIR, "db.sqlite3")
    os.makedirs(DATA_DIR, exist_ok=True)

    _db_lock = Lock()    # serializa writes
    _sync_lock = Lock()  # evita sync concurrentes
    app._syncing = False
    app._last_sync_iso = None

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
            tipo TEXT NOT NULL,
            dni TEXT NOT NULL,
            fecha TEXT NOT NULL,
            sucursal TEXT NOT NULL
        )""")
        conn.commit()

    def _row_to_dict(row): return {k: row[k] for k in row.keys()}

    def get_empleados_dict():
        cur = _db().cursor()
        cur.execute("SELECT * FROM empleados")
        return {r["dni"]: _row_to_dict(r) for r in cur.fetchall()}

    def get_historial_list():
        cur = _db().cursor()
        cur.execute("SELECT id, tipo, dni, fecha, sucursal FROM historial ORDER BY fecha DESC, id DESC")
        return [dict(r) for r in cur.fetchall()]

    # === SYNC ===
    def _merge_from_snapshot(emp_rem, hist_rem):
        """Inserta solo los registros faltantes."""
        merged_emp, merged_ops = 0, 0
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            for dni, e in emp_rem.items():
                cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO empleados(dni,nombre,apellido,puesto,sucursal) VALUES(?,?,?,?,?)",
                        (e["dni"], e["nombre"], e["apellido"], e["puesto"], e["sucursal"])
                    )
                    merged_emp += 1

            for op in hist_rem:
                cur.execute("""SELECT 1 FROM historial
                               WHERE tipo=? AND dni=? AND fecha=? AND sucursal=?""",
                            (op["tipo"], op["dni"], op["fecha"], op["sucursal"]))
                if not cur.fetchone():
                    cur.execute("""INSERT INTO historial(tipo,dni,fecha,sucursal)
                                   VALUES(?,?,?,?)""",
                                (op["tipo"], op["dni"], op["fecha"], op["sucursal"]))
                    merged_ops += 1
            conn.commit()
        return merged_emp, merged_ops

    def sincronizar_con_sucursales():
        peers_ok = total_emp = total_ops = 0
        for peer in PEERS:
            if MY_ADDR and peer == MY_ADDR:
                continue
            try:
                r = requests.get(f"http://{peer}/obtener_todo", timeout=4)
                if r.status_code != 200:
                    continue
                data = r.json()
                emp_rem = data.get("empleados", {})
                hist_rem = data.get("historial", [])
                merged_emp, merged_ops = _merge_from_snapshot(emp_rem, hist_rem)
                peers_ok += 1
                total_emp += merged_emp
                total_ops += merged_ops
            except Exception as e:
                print(f"[WARN] Peer {peer} no disponible: {e}")
        return {"peers_ok": peers_ok, "merged_empleados": total_emp, "merged_historial": total_ops}

    def _sync_now_blocking():
        with _sync_lock:
            if app._syncing:
                return {"already_running": True}
            app._syncing = True
        try:
            stats = sincronizar_con_sucursales()
            app._last_sync_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {"ok": True, "stats": stats, "last_sync": app._last_sync_iso}
        finally:
            app._syncing = False

    def _sync_now_async():
        threading.Thread(target=_sync_now_blocking, daemon=True).start()

    def _background_scheduler():
        """Hilo que corre cada SYNC_INTERVAL segundos."""
        if SYNC_INTERVAL <= 0:
            return
        while True:
            time.sleep(SYNC_INTERVAL)
            _sync_now_async()

    # === Operaciones CRUD ===
    def op_agregar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if cur.fetchone():
                return False, "El empleado ya existe"

            cur.execute(
                "INSERT INTO empleados(dni,nombre,apellido,puesto,sucursal) VALUES(?,?,?,?,?)",
                (dni, nombre, apellido, puesto, NODE_NAME)
            )
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("write", dni, NODE_NAME)
            )
            conn.commit()
        if AUTO_SYNC:
            _sync_now_async()
        return True, "Empleado agregado correctamente"

    def op_editar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if not cur.fetchone():
                return False, "El empleado no existe"

            cur.execute("UPDATE empleados SET nombre=?,apellido=?,puesto=? WHERE dni=?",
                        (nombre, apellido, puesto, dni))
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("update", dni, NODE_NAME)
            )
            conn.commit()
        if AUTO_SYNC:
            _sync_now_async()
        return True, "Empleado editado correctamente"

    def op_consultar(dni):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT * FROM empleados WHERE dni=?", (dni,))
            row = cur.fetchone()
            if not row:
                return None, "El empleado no existe"
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("read", dni, NODE_NAME)
            )
            conn.commit()
        if AUTO_SYNC:
            _sync_now_async()
        return _row_to_dict(row), "Consulta exitosa"

    # === Contexto global para templates ===
    @app.context_processor
    def inject_globals():
        return {
            "sucursal": NODE_NAME,
            "puerto": PORT,
            "sync_interval": SYNC_INTERVAL,
            "last_sync": app._last_sync_iso,
            "is_syncing": app._syncing,
        }

    # === Rutas principales ===
    @app.get("/")
    def index():
        return render_template("index.html")

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

    # === APIs de datos y sync ===
    @app.get("/obtener_historial")
    def obtener_historial_endpoint():
        return jsonify(get_historial_list())

    @app.get("/obtener_empleados")
    def obtener_empleados_endpoint():
        return jsonify(get_empleados_dict())

    @app.get("/obtener_todo")
    def obtener_todo_endpoint():
        return jsonify({"empleados": get_empleados_dict(), "historial": get_historial_list()})

    @app.post("/sync/now")
    def sync_now_endpoint():
        _sync_now_async()
        return jsonify({"started": True})

    @app.get("/sync/status")
    def sync_status_endpoint():
        return jsonify({
            "syncing": app._syncing,
            "last_sync": app._last_sync_iso,
            "interval": SYNC_INTERVAL
        })

    # === Healthcheck con CORS ===
    @app.get("/health")
    def health():
        resp = make_response(jsonify({
            "ok": True,
            "port": PORT,
            "node": NODE_NAME,
            "timestamp": time.time(),
        }), 200)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # === Página DB Browser ===
    @app.get("/admin/db")
    def admin_db():
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT * FROM empleados ORDER BY dni")
        empleados = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM historial ORDER BY fecha DESC, id DESC")
        historial = [dict(r) for r in cur.fetchall()]
        return render_template("db.html", empleados=empleados, historial=historial)

    # === Página y API de estado ===
    @app.get("/status")
    def status_page():
        return render_template("status.html")

    @app.get("/status/peers")
    def peers_status_json():
        out = []
        for peer in PEERS:
            if MY_ADDR and peer == MY_ADDR:
                continue
            label = f"Sucursal_{peer.split(':')[1]}" if ':' in peer else peer
            started = datetime.now()
            try:
                r = requests.get(f"http://{peer}/sync/status", timeout=2)
                latency = int((datetime.now() - started).total_seconds() * 1000)
                if r.status_code == 200:
                    data = r.json()
                    out.append({
                        "peer": peer,
                        "label": label,
                        "up": True,
                        "latency_ms": latency,
                        "remote_last_sync": data.get("last_sync")
                    })
                else:
                    out.append({"peer": peer, "label": label, "up": False,
                                "latency_ms": None, "remote_last_sync": None})
            except Exception:
                out.append({"peer": peer, "label": label, "up": False,
                            "latency_ms": None, "remote_last_sync": None})
        return jsonify(out)

    # Inicializar DB y scheduler
    _ensure_db()
    threading.Thread(target=_background_scheduler, daemon=True).start()
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=False,
        use_reloader=False
    )
