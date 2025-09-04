# 🧾 CFDI Refacturación GUI

Este proyecto es una **interfaz gráfica en Python (Tkinter)** para gestionar **CFDI Globales y Nominativos** (facturas de ingreso) utilizando el **PAC Finkok**.  
Permite generar XML, enviarlos a timbrar, consultar su estatus y cancelar facturas desde una sola aplicación.

---

## ⚙️ Requisitos

1. **Python 3.10+** (recomendado).
2. Crear un entorno virtual:

   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux / Mac
   venv\Scripts\activate      # Windows

    Instalar dependencias:

pip install -r requirements.txt

Si aún no tienes requirements.txt, lo puedes generar con:

    pip freeze > requirements.txt

📂 Estructura del proyecto

├── cfdi_gui.py              # GUI principal para CFDI

├── refacturacion/           # Carpeta donde se guardan XML, ZIP y resultados timbrados

├── conceptos.db             # Base de datos SQLite con conceptos y facturas

├── cer.pem                  # Certificado del emisor

├── key.pem                  # Llave privada del emisor

├── requirements.txt         # Dependencias del entorno virtual

└── README.md                # Este archivo

▶️ Ejecución

Para iniciar la aplicación:

python cfdi_gui.py

📋 Funcionalidades principales

    📑 Listar Facturas Timbradas (Globales y Nominativas).

    ❌ Cancelar Facturas: Envía la solicitud al PAC y libera los conceptos asociados.

    📝 Generar Factura Nominativa: Selecciona conceptos cancelados y crea un CFDI de Ingreso.

    🌍 Generar Factura Global Nueva: Con los conceptos restantes cancelados.

    📤 Timbrar CFDI: Envía el XML en Base64 al PAC para obtener un UUID válido.

    🔎 Consultar Estatus: Recupera el XML timbrado y lo guarda en refacturacion/.

🛠️ Preparar la base de datos

La aplicación utiliza SQLite (conceptos.db) para gestionar conceptos y facturas.
1. Crear la base de datos

Ejecuta en Python:

import sqlite3

conn = sqlite3.connect("conceptos.db")
cur = conn.cursor()

# Tabla de conceptos
cur.execute("""
CREATE TABLE IF NOT EXISTS conceptos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT,
    descripcion TEXT,
    unidad TEXT,
    cantidad REAL,
    valor_unitario REAL,
    importe REAL,
    status TEXT
)
""")

# Tabla de facturas
cur.execute("""
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT,
    rfc_emisor TEXT,
    fecha TEXT,
    total REAL,
    status TEXT,
    tipo TEXT
)
""")

# Relación facturas - conceptos
cur.execute("""
CREATE TABLE IF NOT EXISTS factura_conceptos (
    id_factura INTEGER,
    id_concepto INTEGER
)
""")

conn.commit()
conn.close()



📂 Carpeta refacturacion/

Aquí se guardan automáticamente:

    Archivos XML generados.

    Archivos .zip enviados al PAC.

    Archivos .b64 con el contenido Base64.

    Resultados timbrados recuperados del PAC.

👨‍💻 Autor

Desarrollado para pruebas y prácticas de refacturación CFDI con Python + Finkok.

