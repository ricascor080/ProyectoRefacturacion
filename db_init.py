# db_init.py
import sqlite3

DB_PATH = "conceptos.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Tabla de conceptos
c.execute("""
CREATE TABLE IF NOT EXISTS conceptos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    unidad TEXT NOT NULL,
    cantidad REAL NOT NULL,
    valor_unitario REAL NOT NULL,
    importe REAL NOT NULL,
    status TEXT DEFAULT 'Libre'
)
""")

# Tabla de facturas
c.execute("""
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    status TEXT DEFAULT 'Timbrada'
)
""")

# Tabla intermedia (factura → conceptos)
c.execute("""
CREATE TABLE IF NOT EXISTS factura_conceptos (
    id_factura INTEGER,
    id_concepto INTEGER,
    FOREIGN KEY(id_factura) REFERENCES facturas(id),
    FOREIGN KEY(id_concepto) REFERENCES conceptos(id)
)
""")

conn.commit()
conn.close()

print("✅ Base de datos inicializada en conceptos.db (sin conceptos demo).")
