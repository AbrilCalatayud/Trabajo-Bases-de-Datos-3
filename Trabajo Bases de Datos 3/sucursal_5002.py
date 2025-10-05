import json
import os
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
import threading

app = Flask(__name__)

# Configuración de la sucursal
PUERTO = 5002
SUCURSAL = f"Sucursal_{PUERTO}"
ARCHIVO_EMPLEADOS = f"empleados_{PUERTO}.json"
ARCHIVO_HISTORIAL = f"historial_{PUERTO}.json"

# Lista de sucursales (puertos)
SUCURSALES = [5000, 5001, 5002]

# Inicializar archivos si no existen
def inicializar_archivos():
    if not os.path.exists(ARCHIVO_EMPLEADOS):
        with open(ARCHIVO_EMPLEADOS, 'w') as f:
            json.dump({}, f)
    
    if not os.path.exists(ARCHIVO_HISTORIAL):
        with open(ARCHIVO_HISTORIAL, 'w') as f:
            json.dump([], f)

# Cargar datos
def cargar_empleados():
    with open(ARCHIVO_EMPLEADOS, 'r') as f:
        return json.load(f)

def cargar_historial():
    with open(ARCHIVO_HISTORIAL, 'r') as f:
        return json.load(f)

# Guardar datos
def guardar_empleados(empleados):
    with open(ARCHIVO_EMPLEADOS, 'w') as f:
        json.dump(empleados, f, indent=4)

def guardar_historial(historial):
    with open(ARCHIVO_HISTORIAL, 'w') as f:
        json.dump(historial, f, indent=4)

# Sincronización entre sucursales
def sincronizar_con_sucursales():
    """Sincroniza automáticamente con todas las sucursales"""
    for puerto in SUCURSALES:
        if puerto != PUERTO:
            try:
                # Obtener datos de la sucursal remota
                response = requests.get(f"http://localhost:{puerto}/obtener_todo", timeout=2)
                if response.status_code == 200:
                    datos_remotos = response.json()
                    
                    # Procesar empleados remotos
                    empleados_locales = cargar_empleados()
                    for dni, empleado_remoto in datos_remotos["empleados"].items():
                        if dni not in empleados_locales:
                            empleados_locales[dni] = empleado_remoto
                    guardar_empleados(empleados_locales)
                    
                    # Procesar historial remoto
                    historial_local = cargar_historial()
                    for operacion in datos_remotos["historial"]:
                        if operacion not in historial_local:
                            historial_local.append(operacion)
                    
                    # Ordenar historial por fecha (más reciente primero)
                    historial_local.sort(key=lambda x: x["fecha"], reverse=True)
                    guardar_historial(historial_local)
                    
            except Exception as e:
                print(f"Error sincronizando con sucursal {puerto}: {e}")

# Funciones para operaciones con sincronización automática
def agregar_empleado(dni, nombre, apellido, puesto):
    empleados = cargar_empleados()
    historial = cargar_historial()
    
    if dni in empleados:
        return False, "El empleado ya existe"
    
    empleados[dni] = {
        "dni": dni,
        "nombre": nombre,
        "apellido": apellido,
        "puesto": puesto,
        "sucursal": SUCURSAL
    }
    
    # Registrar en historial
    operacion = {
        "tipo": "write",
        "dni": dni,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sucursal": SUCURSAL
    }
    historial.append(operacion)
    
    guardar_empleados(empleados)
    guardar_historial(historial)
    
    # Sincronizar automáticamente con otras sucursales
    threading.Thread(target=sincronizar_con_sucursales).start()
    
    return True, "Empleado agregado correctamente"

def editar_empleado(dni, nombre, apellido, puesto):
    empleados = cargar_empleados()
    historial = cargar_historial()
    
    if dni not in empleados:
        return False, "El empleado no existe"
    
    empleados[dni]["nombre"] = nombre
    empleados[dni]["apellido"] = apellido
    empleados[dni]["puesto"] = puesto
    
    # Registrar en historial
    operacion = {
        "tipo": "update",
        "dni": dni,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sucursal": SUCURSAL
    }
    historial.append(operacion)
    
    guardar_empleados(empleados)
    guardar_historial(historial)
    
    # Sincronizar automáticamente con otras sucursales
    threading.Thread(target=sincronizar_con_sucursales).start()
    
    return True, "Empleado editado correctamente"

def consultar_empleado(dni):
    empleados = cargar_empleados()
    historial = cargar_historial()
    
    if dni not in empleados:
        return None, "El empleado no existe"
    
    # Registrar en historial
    operacion = {
        "tipo": "read",
        "dni": dni,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sucursal": SUCURSAL
    }
    historial.append(operacion)
    
    guardar_historial(historial)
    
    # Sincronizar automáticamente con otras sucursales
    threading.Thread(target=sincronizar_con_sucursales).start()
    
    return empleados[dni], "Consulta exitosa"

# Rutas de la aplicación
@app.route('/')
def index():
    # Sincronizar automáticamente al cargar la página
    threading.Thread(target=sincronizar_con_sucursales).start()
    return render_template('index.html', sucursal=SUCURSAL, puerto=PUERTO)

@app.route('/agregar_empleado', methods=['POST'])
def agregar_empleado_endpoint():
    dni = request.form['dni']
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    puesto = request.form['puesto']
    
    exito, mensaje = agregar_empleado(dni, nombre, apellido, puesto)
    return jsonify({"exito": exito, "mensaje": mensaje})

@app.route('/editar_empleado', methods=['POST'])
def editar_empleado_endpoint():
    dni = request.form['dni']
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    puesto = request.form['puesto']
    
    exito, mensaje = editar_empleado(dni, nombre, apellido, puesto)
    return jsonify({"exito": exito, "mensaje": mensaje})

@app.route('/consultar_empleado', methods=['POST'])
def consultar_empleado_endpoint():
    dni = request.form['dni']
    empleado, mensaje = consultar_empleado(dni)
    
    if empleado:
        return jsonify({"exito": True, "mensaje": mensaje, "empleado": empleado})
    else:
        return jsonify({"exito": False, "mensaje": mensaje})

@app.route('/obtener_historial')
def obtener_historial_endpoint():
    historial = cargar_historial()
    return jsonify(historial)

@app.route('/obtener_empleados')
def obtener_empleados_endpoint():
    empleados = cargar_empleados()
    return jsonify(empleados)

@app.route('/obtener_todo')
def obtener_todo_endpoint():
    empleados = cargar_empleados()
    historial = cargar_historial()
    return jsonify({
        "empleados": empleados,
        "historial": historial
    })

@app.route('/ver_historial')
def ver_historial_endpoint():
    # Sincronizar antes de mostrar el historial
    sincronizar_con_sucursales()
    empleados = cargar_empleados()
    historial = cargar_historial()
    return jsonify({
        "empleados": empleados,
        "historial": historial
    })

if __name__ == '__main__':
    inicializar_archivos()
    app.run(port=PUERTO, debug=True)