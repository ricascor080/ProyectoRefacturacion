# generate_csv.py
import csv
import random

N = 3500
filename = "conceptos.csv"

with open(filename, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["clave", "descripcion", "unidad", "cantidad", "valor_unitario", "importe", "status"])

    for i in range(1, N + 1):
        clave = "01010101"  # clave genérica SAT válida
        descripcion = f"Concepto #{i}"
        unidad = "H87"  # ClaveUnidad estándar (pieza)
        cantidad = random.randint(1, 10)
        valor_unitario = round(random.uniform(50, 500), 2)
        importe = round(cantidad * valor_unitario, 2)
        status = "Libre"
        writer.writerow([clave, descripcion, unidad, cantidad, valor_unitario, importe, status])

print(f"✅ Archivo {filename} generado con {N} conceptos (incluye importe).")
