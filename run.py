# run.py
import os
from app.app import create_app

if __name__ == "__main__":
    app = create_app()
    host = os.getenv("HOST", "0.0.0.0")      # <-- escucha en todas las interfaces
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("DEBUG", "0") == "1"

    # IMPORTANTE: sin reloader para que no vuelva a 127.0.0.1
    app.run(host=host, port=port, debug=debug, use_reloader=False)
