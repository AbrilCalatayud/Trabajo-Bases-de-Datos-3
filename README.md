# 🧩 BD3 – Consistencia Causal con Garantías de Sesión (Sistema Distribuido de Empleados)

Este proyecto simula un **sistema distribuido** con **tres nodos Flask** que garantizan  
**consistencia causal desde la perspectiva del cliente**, utilizando **garantías de sesión**  
(*read-your-writes, monotonic reads, monotonic writes, writes-follow-reads*).  

Cada nodo mantiene un almacenamiento local de **empleados**, replica su información a los otros  
nodos mediante peticiones HTTP y conserva un historial de operaciones (lecturas/escrituras).

---

## ⚙️ Características principales

- Tres nodos Flask independientes (`Sucursal_5000`, `Sucursal_5001`, `Sucursal_5002`).
- Replicación automática **peer-to-peer** vía `/obtener_todo`.
- Persistencia local en archivos JSON dentro de `data_<puerto>/`.
- Interfaz web con formularios para:
  - Agregar empleados  
  - Editar empleados  
  - Consultar empleados  
  - Visualizar historial y estado de sincronización
- Sincronización automática entre nodos.
- Implementación simple y portable (sin bases de datos externas).

---

## 🗂️ Estructura del proyecto

```
bd3-session-consistency-empleados/
│
├── app/
│   ├── app.py                 # Lógica principal del sistema distribuido
│   ├── templates/
│   │   └── index.html         # Interfaz web del sistema
│   └── static/
│       └── style.css          # Estilos CSS
│
├── data_5000/                 # Datos locales del nodo 5000
├── data_5001/                 # Datos locales del nodo 5001
├── data_5002/                 # Datos locales del nodo 5002
│
├── .env.example               # Variables de entorno de ejemplo
├── requirements.txt           # Dependencias del proyecto
├── run.py                     # Punto de entrada
└── README.md
```

---

## 🚀 Instalación y ejecución

### 1️⃣ Clonar el repositorio
```bash
git clone https://github.com/agustingimenez/bd3-session-consistency-empleados.git
cd bd3-session-consistency-empleados
```

### 2️⃣ Crear entorno virtual e instalar dependencias
```bash
python -m venv .venv
# Activar entorno
# Windows PowerShell:
.venv\Scripts\activate
# Linux / Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

---

### 3️⃣ Ejecutar los tres nodos (cada uno en una terminal)

#### 🔹 Nodo 1
```bash
# PowerShell
$env:PORT="5000"; $env:NODE_NAME="Sucursal_5000"; $env:PEERS="5000,5001,5002"; python run.py
```

#### 🔹 Nodo 2
```bash
$env:PORT="5001"; $env:NODE_NAME="Sucursal_5001"; $env:PEERS="5000,5001,5002"; python run.py
```

#### 🔹 Nodo 3
```bash
$env:PORT="5002"; $env:NODE_NAME="Sucursal_5002"; $env:PEERS="5000,5001,5002"; python run.py
```

(En Linux/Mac podés hacerlo así:)
```bash
PORT=5000 NODE_NAME=Sucursal_5000 PEERS=5000,5001,5002 python run.py
PORT=5001 NODE_NAME=Sucursal_5001 PEERS=5000,5001,5002 python run.py
PORT=5002 NODE_NAME=Sucursal_5002 PEERS=5000,5001,5002 python run.py
```

---

### 4️⃣ Acceder desde el navegador

- [http://localhost:5000](http://localhost:5000)
- [http://localhost:5001](http://localhost:5001)
- [http://localhost:5002](http://localhost:5002)

Cada puerto representa una **sucursal/nodo** independiente que replica los datos  
automáticamente entre sí.

---

## 📦 Variables de entorno

El archivo `.env.example` contiene un modelo básico:

```env
PORT=5000
NODE_NAME=Sucursal_5000
PEERS=5000,5001,5002
```

Copialo y renombralo a `.env` si querés correr un solo nodo.

---

## 📊 Ejemplo de operación

1. Agregás un empleado en `http://localhost:5000`
2. Automáticamente se replica en `http://localhost:5001` y `http://localhost:5002`
3. Al consultar el mismo DNI en otro nodo, los datos estarán sincronizados
4. En “Ver historial” podés observar la secuencia de operaciones replicadas

---

## 🧠 Conceptos teóricos involucrados

- **Consistencia causal:** garantiza que si una operación A causa una operación B,  
  entonces todos los nodos observarán A antes que B.
- **Garantías de sesión:**  
  - *Read-your-writes*: un cliente siempre ve sus propias escrituras.  
  - *Monotonic reads*: las lecturas son cada vez más actualizadas.  
  - *Monotonic writes*: las escrituras de un cliente mantienen su orden.  
  - *Writes-follow-reads*: si leíste un dato antes de escribir, la escritura será coherente.

---

## 🧰 Tecnologías utilizadas

- [Python 3.12+](https://www.python.org/)
- [Flask](https://flask.palletsprojects.com/)
- [Requests](https://docs.python-requests.org/)
- [Dotenv](https://pypi.org/project/python-dotenv/)

---

## 👨‍💻 Autores

- **Agustín Giménez** – UNDEF / FIE  
  Proyecto práctico de **Base de Datos 3**  
  *(Consistencia causal desde la perspectiva del cliente)*

---

## 🏁 Licencia

Este proyecto es de uso académico y libre bajo licencia MIT.
