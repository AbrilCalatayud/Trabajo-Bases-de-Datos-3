# app.py
import os, sqlite3, threading, time, json, logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from threading import Lock
from flask import Flask, render_template, request, jsonify, make_response, Response, send_file
import requests
from dotenv import load_dotenv

# === Paths fijos ===
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

    # === Peers hardcodeados (9 instancias, orden estable) ===
    PEERS = [
        "26.60.177.15:5000", "26.60.177.15:5001", "26.60.177.15:5002",
        "26.39.171.184:5000", "26.39.171.184:5001", "26.39.171.184:5002",
        "26.32.162.255:5000", "26.32.162.255:5001", "26.32.162.255:5002",
    ]
    PEERS = sorted(set(PEERS))
    if len(PEERS) != 9:
        print(f"[WARN] Se esperaban 9 peers, hay {len(PEERS)}: {PEERS}")

    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()
    MY_ADDR = f"{PUBLIC_HOST}:{PORT}" if PUBLIC_HOST else None

    AUTO_SYNC = int(os.getenv("AUTO_SYNC", "0"))            # 0 = manual, 1 = auto tras write
    SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "600"))  # segundos
    SYNC_SCOPE = os.getenv("SYNC_SCOPE", "all").lower()     # "all" | "cohort"

    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), f"data_{PORT}")
    DB_PATH = os.path.join(DATA_DIR, "db.sqlite3")
    os.makedirs(DATA_DIR, exist_ok=True)

    # === Logging JSON con rotación ===
    LOG_DIR = os.path.join(os.path.dirname(BASE_DIR), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_PATH = os.path.join(LOG_DIR, f"sync_{PORT}.log")

    logger = logging.getLogger(f"sync-{PORT}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)

    def log_event(level: str, event: str, **kv):
        payload = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "node": NODE_NAME,
            "port": PORT,
            "event": event,
            **kv
        }
        line = json.dumps(payload, ensure_ascii=False)
        getattr(logger, "error" if level == "error" else "warning" if level == "warning" else "info")(line)

    _db_lock = Lock()
    _sync_lock = Lock()
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
        try:
            cur.execute("ALTER TABLE empleados ADD COLUMN updated_at TEXT")
        except Exception:
            pass
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

    def _last_ts_map_local():
        cur = _db().cursor()
        cur.execute("""
            SELECT dni, MAX(fecha) AS last_ts
            FROM historial
            GROUP BY dni
        """)
        return {r["dni"]: r["last_ts"] for r in cur.fetchall()}

    # === Merge remoto → local (LWW) ===
    def _merge_from_snapshot(emp_rem, hist_rem, last_ts_rem):
        merged_emp_inserts = merged_emp_updates = merged_ops = 0
        local_last = _last_ts_map_local()

        def _is_remote_newer(rem_ts, loc_ts):
            if rem_ts and not loc_ts: return True
            if rem_ts and loc_ts: return rem_ts > loc_ts
            return False

        with _db_lock:
            conn = _db(); cur = conn.cursor()

            for dni, e in emp_rem.items():
                cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
                exists = cur.fetchone() is not None
                rem_ts = last_ts_rem.get(dni)
                loc_ts = local_last.get(dni)

                if not exists:
                    cur.execute(
                        "INSERT INTO empleados(dni,nombre,apellido,puesto,sucursal,updated_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                        (e["dni"], e["nombre"], e["apellido"], e["puesto"], e["sucursal"])
                    )
                    merged_emp_inserts += 1
                else:
                    if _is_remote_newer(rem_ts, loc_ts):
                        cur.execute(
                            "UPDATE empleados SET nombre=?, apellido=?, puesto=?, sucursal=?, updated_at=datetime('now','localtime') WHERE dni=?",
                            (e["nombre"], e["apellido"], e["puesto"], e["sucursal"], e["dni"])
                        )
                        merged_emp_updates += 1

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

        log_event("info", "merge_applied",
                  merged_empleados_inserts=merged_emp_inserts,
                  merged_empleados_updates=merged_emp_updates,
                  merged_historial=merged_ops)
        return merged_emp_inserts + merged_emp_updates, merged_ops

    # === Sync principal ===
    def sincronizar_con_sucursales(peers_list=None):
        peers = peers_list if peers_list is not None else PEERS
        peers_ok = total_emp = total_ops = 0
        for peer in peers:
            started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_event("info", "peer_request_start", peer=peer, endpoint="/obtener_todo", started_at=started_at)
            try:
                r = requests.get(f"http://{peer}/obtener_todo", timeout=4)
                if r.status_code != 200:
                    log_event("warning", "peer_request_non200", peer=peer, status=r.status_code)
                    continue
                data = r.json()
                emp_rem = data.get("empleados", {})
                hist_rem = data.get("historial", [])
                last_ts_rem = data.get("last_ts", {})
                merged_emp, merged_ops = _merge_from_snapshot(emp_rem, hist_rem, last_ts_rem)
                peers_ok += 1
                total_emp += merged_emp
                total_ops += merged_ops
                log_event("info", "peer_request_ok", peer=peer,
                          merged_empleados=merged_emp, merged_historial=merged_ops)
            except Exception as e:
                log_event("error", "peer_request_error", peer=peer, error=str(e))
        summary = {"peers_ok": peers_ok, "merged_empleados": total_emp, "merged_historial": total_ops}
        log_event("info", "sync_summary", **summary)
        return summary

    def _sync_now_blocking():
        with _sync_lock:
            if app._syncing:
                log_event("warning", "sync_already_running")
                return {"already_running": True}
            app._syncing = True
        try:
            log_event("info", "sync_start", auto=False)
            stats = sincronizar_con_sucursales()
            app._last_sync_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_event("info", "sync_end", last_sync=app._last_sync_iso, **stats)
            return {"ok": True, "stats": stats, "last_sync": app._last_sync_iso}
        finally:
            app._syncing = False

    def _sync_now_async():
        log_event("info", "sync_async_triggered")
        threading.Thread(target=_sync_now_blocking, daemon=True).start()

    # Helpers cohortes (mismo puerto)
    def _peers_with_port(port_int: int):
        want = str(port_int)
        return [p for p in PEERS if p.split(":")[1] == want]

    def _background_scheduler():
        if SYNC_INTERVAL <= 0:
            log_event("info", "scheduler_disabled")
            return
        while True:
            time.sleep(SYNC_INTERVAL)
            log_event("info", "scheduler_tick", interval=SYNC_INTERVAL, scope=SYNC_SCOPE)
            if SYNC_SCOPE == "cohort":
                cohort = _peers_with_port(PORT)
                threading.Thread(target=lambda: sincronizar_con_sucursales(cohort), daemon=True).start()
            else:
                _sync_now_async()

    # === CRUD ===
    def op_agregar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if cur.fetchone():
                log_event("warning", "agregar_exists", dni=dni)
                return False, "El empleado ya existe"
            cur.execute(
                "INSERT INTO empleados(dni,nombre,apellido,puesto,sucursal,updated_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                (dni, nombre, apellido, puesto, NODE_NAME)
            )
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("write", dni, NODE_NAME)
            )
            conn.commit()
        log_event("info", "agregar_ok", dni=dni, nombre=nombre, apellido=apellido, puesto=puesto)
        if AUTO_SYNC: _sync_now_async()
        return True, "Empleado agregado correctamente"

    def op_editar(dni, nombre, apellido, puesto):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT 1 FROM empleados WHERE dni=?", (dni,))
            if not cur.fetchone():
                log_event("warning", "editar_not_found", dni=dni)
                return False, "El empleado no existe"
            cur.execute("UPDATE empleados SET nombre=?,apellido=?,puesto=?,updated_at=datetime('now','localtime') WHERE dni=?",
                        (nombre, apellido, puesto, dni))
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("update", dni, NODE_NAME)
            )
            conn.commit()
        log_event("info", "editar_ok", dni=dni)
        if AUTO_SYNC: _sync_now_async()
        return True, "Empleado editado correctamente"

    def op_consultar(dni):
        with _db_lock:
            conn = _db(); cur = conn.cursor()
            cur.execute("SELECT * FROM empleados WHERE dni=?", (dni,))
            row = cur.fetchone()
            if not row:
                log_event("warning", "consultar_not_found", dni=dni)
                return None, "El empleado no existe"
            cur.execute(
                "INSERT INTO historial(tipo,dni,fecha,sucursal) VALUES(?,?,datetime('now','localtime'),?)",
                ("read", dni, NODE_NAME)
            )
            conn.commit()
        log_event("info", "consultar_ok", dni=dni)
        if AUTO_SYNC: _sync_now_async()
        return _row_to_dict(row), "Consulta exitosa"

    # === Contexto templates ===
    @app.context_processor
    def inject_globals():
        return {
            "sucursal": NODE_NAME,
            "puerto": PORT,
            "sync_interval": SYNC_INTERVAL,
            "last_sync": app._last_sync_iso,
            "is_syncing": app._syncing,
        }

    # === Rutas UI ===
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

    # === APIs de datos/sync ===
    @app.get("/obtener_historial")
    def obtener_historial_endpoint():
        return jsonify(get_historial_list())

    @app.get("/obtener_empleados")
    def obtener_empleados_endpoint():
        return jsonify(get_empleados_dict())

    @app.get("/obtener_todo")
    def obtener_todo_endpoint():
        return jsonify({
            "empleados": get_empleados_dict(),
            "historial": get_historial_list(),
            "last_ts": _last_ts_map_local(),
        })

    @app.post("/sync/now")
    def sync_now_endpoint():
        log_event("info", "sync_now_endpoint_called")
        _sync_now_async()
        return jsonify({"started": True})

    @app.get("/sync/status")
    def sync_status_endpoint():
        return jsonify({
            "syncing": app._syncing,
            "last_sync": app._last_sync_iso,
            "interval": SYNC_INTERVAL
        })

    @app.post("/sync/port/<int:port>")
    def sync_from_port(port):
        peers = _peers_with_port(port)
        log_event("info", "sync_from_port_called", port=port, peers=peers)
        threading.Thread(target=lambda: sincronizar_con_sucursales(peers), daemon=True).start()
        return jsonify({"started": True, "port": port, "targets": peers})

    @app.post("/sync/from")
    def sync_from_peer():
        peer = request.args.get("peer")
        if not peer:
            return jsonify({"error": "Falta parámetro ?peer=HOST:PORT"}), 400
        log_event("info", "sync_from_peer_called", peer=peer)
        threading.Thread(target=lambda: sincronizar_con_sucursales([peer]), daemon=True).start()
        return jsonify({"started": True, "peer": peer})

    # === NUEVO: Sugerencias y fetch por DNI ===
    @app.get("/empleados/suggest")
    def empleados_suggest():
        q = (request.args.get("q") or "").strip()
        limit = int(request.args.get("limit", "12"))
        cur = _db().cursor()
        if not q:
            cur.execute("SELECT dni, nombre, apellido FROM empleados ORDER BY dni LIMIT ?", (limit,))
        else:
            like = f"{q}%"
            like_any = f"%{q}%"
            cur.execute("""
                SELECT dni, nombre, apellido
                FROM empleados
                WHERE dni LIKE ? OR nombre LIKE ? OR apellido LIKE ?
                ORDER BY (dni LIKE ?) DESC, dni
                LIMIT ?
            """, (like, like_any, like_any, like, limit))
        rows = [{"dni": r["dni"], "nombre": r["nombre"], "apellido": r["apellido"]} for r in cur.fetchall()]
        return jsonify(rows)

    @app.get("/empleado/<dni>")
    def empleado_by_dni(dni):
        cur = _db().cursor()
        cur.execute("SELECT * FROM empleados WHERE dni=?", (dni,))
        r = cur.fetchone()
        if not r:
            return jsonify({"ok": False, "msg": "No existe"}), 404
        return jsonify({"ok": True, "empleado": _row_to_dict(r)})

    # === Health ===
    @app.get("/health")
    def health():
        resp = make_response(jsonify({
            "ok": True, "port": PORT, "node": NODE_NAME, "timestamp": time.time(),
        }), 200)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # === DB Browser simple ===
    @app.get("/admin/db")
    def admin_db():
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT * FROM empleados ORDER BY dni")
        empleados = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM historial ORDER BY fecha DESC, id DESC")
        historial = [dict(r) for r in cur.fetchall()]
        return render_template("db.html", empleados=empleados, historial=historial)

    # === Estado de peers (si ya lo usás en otra plantilla, ok) ===
    @app.get("/status")
    def status_page():
        return render_template("status.html")

    @app.get("/status/peers")
    def peers_status_json():
        grid = [
            "26.60.177.15:5000", "26.60.177.15:5001", "26.60.177.15:5002",
            "26.39.171.184:5000", "26.39.171.184:5001", "26.39.171.184:5002",
            "26.32.162.255:5000", "26.32.162.255:5001", "26.32.162.255:5002",
        ]
        out = []
        for peer in grid:
            try:
                start = datetime.now()
                r = requests.get(f"http://{peer}/sync/status", timeout=2)
                latency = int((datetime.now() - start).total_seconds() * 1000)
                if r.status_code == 200:
                    data = r.json()
                    out.append({"peer": peer, "up": True, "latency_ms": latency, "remote_last_sync": data.get("last_sync")})
                else:
                    out.append({"peer": peer, "up": False, "latency_ms": None})
            except Exception:
                out.append({"peer": peer, "up": False, "latency_ms": None})
        return jsonify(out)

    # === Logs ===
    def _tail_file(path: str, max_lines: int = 200):
        if not os.path.exists(path): return []
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = -1
            data = []
            while len(data) <= max_lines and abs(block * 1024) < size:
                f.seek(block * 1024, os.SEEK_END)
                data.extend(f.readlines()); block -= 1
            return [l.decode("utf-8", errors="replace").rstrip("\n") for l in data[-max_lines:]]

    @app.get("/admin/logs")
    def admin_logs():
        try:
            lines = int(request.args.get("lines", "200"))
        except Exception:
            lines = 200
        tail = _tail_file(LOG_PATH, max_lines=lines)
        return Response("\n".join(tail), mimetype="text/plain; charset=utf-8")

    @app.get("/admin/logs/download")
    def admin_logs_download():
        if not os.path.exists(LOG_PATH):
            return Response("No hay logs todavía.", mimetype="text/plain"), 404
        return send_file(LOG_PATH, as_attachment=True, download_name=os.path.basename(LOG_PATH))

    # Init
    _ensure_db()
    threading.Thread(target=_background_scheduler, daemon=True).start()
    log_event("info", "app_started", peers=PEERS, log_path=LOG_PATH, sync_scope=SYNC_SCOPE, my_addr=MY_ADDR)
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "5000")),
            debug=False, use_reloader=False)
