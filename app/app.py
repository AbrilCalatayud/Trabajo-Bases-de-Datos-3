import os, json, threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)

    # === Config ===
    PORT = int(os.getenv("PORT", "5000"))
    NODE_NAME = os.getenv("NODE_NAME", f"Sucursal_{PORT}")
    peers_env = os.getenv("PEERS", "5000,5001,5002")
    SUCURSALES = [int(p.strip()) for p in peers_env.split(",") if p.strip().isdigit()]
    SUCURSALES = [p for p in SUCURSALES if p != PORT]

    DATA_DIR = f"data_{PORT}"
    EMP_FILE = os.path.join(DATA_DIR, f"empleados_{PORT}.json")
    LOG_FILE = os.path.join(DATA_DIR, f"historial_{PORT}.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    # === Storage helpers ===
    def _ensure():
        if not os.path.exists(EMP_FILE):
            with open(EMP_FILE, "w", encoding="utf-8") as f: json.dump({}, f)
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", encoding="utf-8") as f: json.dump([], f)

    def cargar_empleados():
        with open(EMP_FILE, "r", encoding="utf-8") as f: return json.load(f)

    def cargar_historial():
        with open(LOG_FILE, "r", encoding="utf-8") as f: return json.load(f)

    def guardar_empleados(data):
        with open(EMP_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

    def guardar_historial(data):
        with open(LOG_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

    # === Sync ===
    def sincronizar_con_sucursales():
        for puerto in SUCURSALES:
            try:
                r = requests.get(f"http://localhost:{puerto}/obtener_todo", timeout=2)
                if r.status_code != 200: 
                    continue
                datos_remotos = r.json()

                empleados_locales = cargar_empleados()
                for dni, emp_r in datos_remotos.get("empleados", {}).items():
                    if dni not in empleados_locales:
                        empleados_locales[dni] = emp_r
                guardar_empleados(empleados_locales)

                historial_local = cargar_historial()
                for op in datos_remotos.get("historial", []):
                    if op not in historial_local:
                        historial_local.append(op)
                historial_local.sort(key=lambda x: x["fecha"], reverse=True)
                guardar_historial(historial_local)
            except Exception as e:
                print(f"[WARN] Peer {puerto} no disponible: {e}")

    # === Operaciones ===
    def agregar_empleado(dni, nombre, apellido, puesto):
        empleados = cargar_empleados()
        if dni in empleados:
            return False, "El empleado ya existe"
        empleados[dni] = {
            "dni": dni, "nombre": nombre, "apellido": apellido,
            "puesto": puesto, "sucursal": NODE_NAME
        }
        historial = cargar_historial()
        historial.append({
            "tipo": "write", "dni": dni,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sucursal": NODE_NAME
        })
        guardar_empleados(empleados)
        guardar_historial(historial)
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return True, "Empleado agregado correctamente"

    def editar_empleado(dni, nombre, apellido, puesto):
        empleados = cargar_empleados()
        if dni not in empleados:
            return False, "El empleado no existe"
        empleados[dni].update({"nombre": nombre, "apellido": apellido, "puesto": puesto})
        historial = cargar_historial()
        historial.append({
            "tipo": "update", "dni": dni,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sucursal": NODE_NAME
        })
        guardar_empleados(empleados)
        guardar_historial(historial)
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return True, "Empleado editado correctamente"

    def consultar_empleado(dni):
        empleados = cargar_empleados()
        if dni not in empleados:
            return None, "El empleado no existe"
        historial = cargar_historial()
        historial.append({
            "tipo": "read", "dni": dni,
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sucursal": NODE_NAME
        })
        guardar_historial(historial)
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return empleados[dni], "Consulta exitosa"

    # === Rutas ===
    @app.route("/")
    def index():
        threading.Thread(target=sincronizar_con_sucursales, daemon=True).start()
        return render_template("index.html", sucursal=NODE_NAME, puerto=PORT)

    @app.post("/agregar_empleado")
    def agregar_empleado_endpoint():
        exito, mensaje = agregar_empleado(
            request.form["dni"], request.form["nombre"], request.form["apellido"], request.form["puesto"]
        )
        return jsonify({"exito": exito, "mensaje": mensaje})

    @app.post("/editar_empleado")
    def editar_empleado_endpoint():
        exito, mensaje = editar_empleado(
            request.form["dni"], request.form["nombre"], request.form["apellido"], request.form["puesto"]
        )
        return jsonify({"exito": exito, "mensaje": mensaje})

    @app.post("/consultar_empleado")
    def consultar_empleado_endpoint():
        empleado, mensaje = consultar_empleado(request.form["dni"])
        if empleado:
            return jsonify({"exito": True, "mensaje": mensaje, "empleado": empleado})
        return jsonify({"exito": False, "mensaje": mensaje})

    @app.get("/obtener_historial")
    def obtener_historial_endpoint():
        return jsonify(cargar_historial())

    @app.get("/obtener_empleados")
    def obtener_empleados_endpoint():
        return jsonify(cargar_empleados())

    @app.get("/obtener_todo")
    def obtener_todo_endpoint():
        return jsonify({"empleados": cargar_empleados(),"historial": cargar_historial()})

    @app.get("/ver_historial")
    def ver_historial_endpoint():
        sincronizar_con_sucursales()
        return jsonify({"empleados": cargar_empleados(),"historial": cargar_historial()})

    _ensure()
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(port=int(os.getenv("PORT", "5000")), debug=True)
