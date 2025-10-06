#!/bin/bash
# ========================================
# TP2 - Arranque de 3 nodos en WSL usando Windows Terminal
# Abre 3 tabs en wt.exe, cada tab ejecuta wsl.exe -> bash -lc "..."
# ========================================

set -e

PROJECT_DIR="$(pwd)"                 # ruta en WSL, tipo /mnt/c/Users/.../repo
PEERS="5000,5001,5002"

# Rutas de venv (elige la que te aplique)
VENV_ACTIVATE_WSL="$PROJECT_DIR/.venv/bin/activate"            # venv creado dentro de WSL
VENV_ACTIVATE_WIN="$PROJECT_DIR/.venv/Scripts/activate"        # venv creado con Python de Windows

make_cmd() {
  local PORT="$1"
  local NAME="$2"

  # arma el comando que se ejecuta dentro de bash -lc en WSL
  cat <<EOF
cd "$PROJECT_DIR";
if [ -f "$VENV_ACTIVATE_WSL" ]; then
  source "$VENV_ACTIVATE_WSL";
elif [ -f "$VENV_ACTIVATE_WIN" ]; then
  source "$VENV_ACTIVATE_WIN";
fi
export PORT=$PORT NODE_NAME="$NAME" PEERS="$PEERS";
python run.py
EOF
}

# 1) Si hay Windows Terminal, usamos 3 pestañas con wsl.exe dentro
if command -v wt.exe >/dev/null 2>&1; then
  echo "▶ Abriendo 3 pestañas en Windows Terminal con WSL…"

  wt.exe new-tab --title "Nodo 5000" wsl.exe -e bash -lc "$(make_cmd 5000 Sucursal_5000)" &
  sleep 0.5
  wt.exe new-tab --title "Nodo 5001" wsl.exe -e bash -lc "$(make_cmd 5001 Sucursal_5001)" &
  sleep 0.5
  wt.exe new-tab --title "Nodo 5002" wsl.exe -e bash -lc "$(make_cmd 5002 Sucursal_5002)" &
  exit 0
fi

# 2) Fallback: usar tmux dentro de WSL
echo "ℹ️  wt.exe no encontrado. Probando con tmux…"
if ! command -v tmux >/dev/null 2>&1; then
  echo "❌ tmux no está instalado. Instalalo con: sudo apt update && sudo apt install -y tmux"
  exit 1
fi

SESSION="bd3-nodes"
tmux new-session -d -s "$SESSION" "bash -lc '$(make_cmd 5000 Sucursal_5000)'" \; \
  split-window -h   "bash -lc '$(make_cmd 5001 Sucursal_5001)'" \; \
  split-window -v   "bash -lc '$(make_cmd 5002 Sucursal_5002)'" \; \
  select-layout even-horizontal \; attach -t "$SESSION"
