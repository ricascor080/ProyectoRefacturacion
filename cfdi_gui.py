#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
import refacturacion
from tkinter import messagebox
import sqlite3, os, base64, zipfile, io, json, time, re, datetime
from pathlib import Path
from lxml import etree as ET
from suds.client import Client
import subprocess
import sys

# ================= CONFIG =================
DB_PATH = "conceptos.db"
OUT_DIR = Path("out"); OUT_DIR.mkdir(exist_ok=True)

WSDL_ASYNC = "https://demo-facturacion.finkok.com/servicios/soap/async.wsdl"
WSDL_CANCEL = "https://demo-facturacion.finkok.com/servicios/soap/cancel.wsdl"

FINKOK_USER = os.getenv("FINKOK_USER", "ricascor080@gmail.com")
FINKOK_PASS = os.getenv("FINKOK_PASS", "Ricas002385.")
TAXPAYER_ID = "EKU9003173C9"   # RFC emisor

CER_PATH = "cer.pem"
KEY_PATH = "key.pem"

# ================= HELPERS =================
def encode_file_to_base64(filepath):
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def suds_to_builtin(obj):
    try:
        from suds.sudsobject import asdict
    except Exception:
        return obj
    if hasattr(obj, "__keylist__"):
        from suds.sudsobject import asdict
        return {k: suds_to_builtin(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [suds_to_builtin(x) for x in obj]
    return obj

def pick_base64_field(result_obj):
    for c in ("file", "zip", "application_zipped", "application_zip", "data"):
        if hasattr(result_obj, c):
            val = getattr(result_obj, c)
            if val:
                return val
    d = suds_to_builtin(result_obj)
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, str) and len(v) > 100:
                return v
            if isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, str) and len(vv) > 100:
                        return vv
    return None

def read_id_from_txt(path: Path) -> str:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"(multistamp_[0-9a-fA-F\-]+)", txt)
    if m:
        return m.group(1)
    for token in re.split(r"\s+", txt):
        tok = token.strip().strip("'").strip('"')
        if tok:
            return tok
    raise ValueError(f"No se encontró un id válido en {path}")

# ================= DB =================
def migrate_facturas():
    """Asegura que la tabla facturas tenga columna rfc_emisor"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(facturas)")
    cols = [row[1] for row in cur.fetchall()]
    if "rfc_emisor" not in cols:
        cur.execute("ALTER TABLE facturas ADD COLUMN rfc_emisor TEXT")
        conn.commit()
        print("Columna rfc_emisor agregada a facturas")
    conn.close()

def obtener_conceptos_libres():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, clave, descripcion, unidad, cantidad, valor_unitario, importe FROM conceptos WHERE status='Libre'")
    rows = cur.fetchall()
    conn.close()
    return rows

def ocupar_conceptos(ids):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("UPDATE conceptos SET status='Ocupado' WHERE id=?", [(cid,) for cid in ids])
    conn.commit()
    conn.close()

def liberar_conceptos(ids):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("UPDATE conceptos SET status='Libre' WHERE id=?", [(cid,) for cid in ids])
    conn.commit()
    conn.close()

def guardar_factura(uuid, total, conceptos_ids):
    migrate_facturas()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO facturas (uuid, rfc_emisor, fecha, total, status)
        VALUES (?, ?, ?, ?, 'Timbrada')
    """, (uuid, TAXPAYER_ID, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), total))
    id_factura = cur.lastrowid
    cur.executemany("INSERT INTO factura_conceptos (id_factura, id_concepto) VALUES (?, ?)",
                    [(id_factura, cid) for cid in conceptos_ids])
    conn.commit()
    conn.close()

def listar_facturas():
    migrate_facturas()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT uuid, fecha, total, status FROM facturas")
    rows = cur.fetchall()
    conn.close()
    return rows

def conceptos_por_factura(uuid):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM facturas WHERE uuid=?", (uuid,))
    row = cur.fetchone()
    if not row:
        return []
    id_factura = row[0]
    cur.execute("SELECT id_concepto FROM factura_conceptos WHERE id_factura=?", (id_factura,))
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids

# ================= CFDI =================
def generar_cfdi(conceptos_sel):
    fecha_sat = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    nsmap = {'cfdi': 'http://www.sat.gob.mx/cfd/4','xsi': 'http://www.w3.org/2001/XMLSchema-instance'}
    schemaLocation = 'http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd'

    root = ET.Element('{http://www.sat.gob.mx/cfd/4}Comprobante', nsmap=nsmap, attrib={
        '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation': schemaLocation,
        'Version': '4.0','Serie': 'FG','Folio': '10001','Fecha': fecha_sat,
        'Sello': '','NoCertificado': '','Certificado': '',
        'Moneda': 'MXN','TipoDeComprobante': 'I','Exportacion': '01',
        'LugarExpedicion': '64000','FormaPago': '01','MetodoPago': 'PUE'
    })

    ET.SubElement(root, '{http://www.sat.gob.mx/cfd/4}InformacionGlobal',
                  attrib={'Periodicidad':'04','Meses':'08','Año':'2025'})
    ET.SubElement(root, '{http://www.sat.gob.mx/cfd/4}Emisor',
                  attrib={'Rfc':TAXPAYER_ID,'Nombre':'ESCUELA KEMPER URGATE','RegimenFiscal':'601'})
    ET.SubElement(root, '{http://www.sat.gob.mx/cfd/4}Receptor',
                  attrib={'Rfc':'XAXX010101000','Nombre':'PUBLICO EN GENERAL',
                          'UsoCFDI':'S01','RegimenFiscalReceptor':'616','DomicilioFiscalReceptor':'64000'})

    conceptos_tag = ET.SubElement(root, '{http://www.sat.gob.mx/cfd/4}Conceptos')
    subtotal = 0.0
    for c in conceptos_sel:
        idc, clave, desc, unidad, cantidad, valor_unitario, importe = c
        subtotal += importe
        ET.SubElement(conceptos_tag, '{http://www.sat.gob.mx/cfd/4}Concepto', attrib={
            'ClaveProdServ': clave,'Descripcion': desc,'Cantidad': str(cantidad),
            'ClaveUnidad': unidad,'ValorUnitario': str(valor_unitario),
            'Importe': str(importe),'ObjetoImp': '01'
        })

    root.set('SubTotal', f'{subtotal:.2f}')
    root.set('Total', f'{subtotal:.2f}')

    xml_path = OUT_DIR / "cfdi_global40.xml"
    ET.ElementTree(root).write(xml_path, pretty_print=True, xml_declaration=True, encoding='UTF-8')

    # ZIP
    zip_filename = OUT_DIR / "cfdi_global40.zip"
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(xml_path, arcname=os.path.basename(xml_path))

    # B64
    b64_filename = OUT_DIR / "cfdi_global40.b64"
    with open(zip_filename, "rb") as f, open(b64_filename, "w", encoding="utf-8") as fout:
        fout.write(base64.b64encode(f.read()).decode('utf-8'))

    return xml_path, b64_filename, subtotal, [c[0] for c in conceptos_sel]

# ================= PAC actions =================
def enviar_cfdi():
    b64_file = OUT_DIR / "cfdi_global40.b64"
    if not b64_file.exists():
        return None, "Primero genera el CFDI."

    zip_b64 = b64_file.read_text().strip()
    client = Client(WSDL_ASYNC, cache=None)
    res = client.service.sign_multistamp(file=zip_b64, username=FINKOK_USER, password=FINKOK_PASS)
    res_dict = suds_to_builtin(res)

    rid = res_dict.get("id")
    if not rid:
        return None, f"Error en timbrado: {json.dumps(res_dict, indent=2, ensure_ascii=False)}"

    (OUT_DIR / "workprocessid.txt").write_text(rid, encoding="utf-8")
    return rid, "CFDI enviado con éxito."

def consultar_estatus():
    try:
        rid = read_id_from_txt(OUT_DIR / "workprocessid.txt")
    except:
        return None, "No existe workprocessid.txt"

    client = Client(WSDL_ASYNC, cache=None)
    res = client.service.get_result_multistamp(id=rid, username=FINKOK_USER, password=FINKOK_PASS)
    res_dict = suds_to_builtin(res)

    b64_zip = pick_base64_field(res)
    if not b64_zip:
        return None, "Aún no está timbrado"

    zip_bytes = base64.b64decode(b64_zip.encode("ascii"))
    zip_path  = OUT_DIR / f"resultado_{rid}.zip"
    zip_path.write_bytes(zip_bytes)

    extract_dir = OUT_DIR / f"extract_{rid}"
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        zf.extractall(extract_dir)

    # Leer XML timbrado para extraer UUID
    for f in extract_dir.glob("*.xml"):
        tree = ET.parse(f)
        root = tree.getroot()
        tfd = root.find(".//{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital")
        if tfd is not None:
            uuid = tfd.attrib.get("UUID")
            total = root.attrib.get("Total")
            return (uuid, float(total)), "CFDI timbrado con éxito."

    return None, "No se encontró UUID en el XML."

def cancelar_factura(uuid):
    try:
        cer_file = encode_file_to_base64(CER_PATH)
        key_file = encode_file_to_base64(KEY_PATH)

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT rfc_emisor FROM facturas WHERE uuid=?", (uuid,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return False, "Factura no encontrada en la BD"
        rfc_emisor = row[0]

        client = Client(WSDL_CANCEL, cache=None)
        invoices_obj = client.factory.create("ns0:UUID")
        invoices_obj._UUID = uuid
        invoices_obj._Motivo = "02"

        UUIDS_list = client.factory.create("ns0:UUIDArray")
        UUIDS_list.UUID.append(invoices_obj)

        result = client.service.cancel(UUIDS_list, FINKOK_USER, FINKOK_PASS, rfc_emisor, cer_file, key_file)
        if "Folios" in str(result):
            ids = conceptos_por_factura(uuid)
            liberar_conceptos(ids)
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE facturas SET status='Cancelada' WHERE uuid=?", (uuid,))
            conn.commit(); conn.close()
            return True, "Factura cancelada con éxito"
        else:
            return False, f"Error PAC: {result}"
    except Exception as e:
        return False, str(e)

# ================= GUI actions =================
def generar_cfdi_gui():
    global conceptos_ids
    seleccionados = [conceptos[i] for i in listbox_conceptos.curselection()]
    if not seleccionados:
        messagebox.showwarning("Atención", "Selecciona al menos un concepto.")
        return
    try:
        xml_path, b64_file, total, conceptos_ids = generar_cfdi(seleccionados)
        messagebox.showinfo("Generado", f"Archivos creados:\n{xml_path}\n{b64_file}")
    except Exception as e:
        messagebox.showerror("Error", str(e))

def enviar_cfdi_gui():
    global conceptos_ids
    rid, msg = enviar_cfdi()
    if not rid:
        messagebox.showerror("Error", msg)
        return
    ocupar_conceptos(conceptos_ids)
    refrescar_conceptos()
    messagebox.showinfo("Timbrado", msg)

def consultar_estatus_gui():
    res, msg = consultar_estatus()
    if not res:
        messagebox.showwarning("Estatus", msg)
        return
    (uuid, total) = res
    guardar_factura(uuid, total, conceptos_ids)
    refrescar_facturas()
    messagebox.showinfo("Estatus", f"CFDI timbrado.\nUUID: {uuid}")

def cancelar_factura_gui():
    sel = listbox_facturas.curselection()
    if not sel:
        messagebox.showwarning("Atención", "Selecciona una factura.")
        return
    idx = sel[0]
    factura_txt = listbox_facturas.get(idx)
    uuid = factura_txt.split("|")[0].strip()
    ok, msg = cancelar_factura(uuid)
    if ok:
        refrescar_facturas()
        refrescar_conceptos()
        messagebox.showinfo("Cancelada", msg)
    else:
        messagebox.showerror("Error", msg)

def refrescar_conceptos():
    listbox_conceptos.delete(0, tk.END)
    libres = obtener_conceptos_libres()  # ← debe traer registros con status='Libre'
    lbl_count.config(text=f"Conceptos libres: {len(libres)}")  # ← contador actualizado
    for c in libres:
        listbox_conceptos.insert(tk.END, f"{c[0]} - {c[2]} (${c[6]})")
        
def seleccionar_todos_conceptos():
    listbox_conceptos.select_set(0, tk.END)  # selecciona todo en la lista

def refrescar_facturas():
    listbox_facturas.delete(0, tk.END)
    for f in listar_facturas():
        uuid, fecha, total, status = f
        listbox_facturas.insert(tk.END, f"{uuid} | {fecha} | ${total} | {status}")

def abrir_refacturacion_gui():
    try:
        ruta = os.path.join(os.path.dirname(__file__), "refacturacion_gui.py")
        subprocess.Popen([sys.executable, ruta])
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo abrir la GUI de Refacturación: {e}")
# ================= Mostrar solo facturas globales canceladas =================
def ver_canceladas_globales():
    win = tk.Toplevel(root)
    win.title("Facturas Globales Canceladas")

    tk.Label(win, text="🌍 Facturas Globales Canceladas", font=("Arial", 12, "bold")).pack(pady=5)
    listbox_canceladas = tk.Listbox(win, width=120, height=15)
    listbox_canceladas.pack(padx=10, pady=10)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, uuid, fecha, total, status, tipo 
        FROM facturas 
        WHERE status='Cancelada' AND tipo='Global'
    """)
    rows = cur.fetchall()
    conn.close()

    for f in rows:
        fid, uuid, fecha, total, status, tipo = f
        listbox_canceladas.insert(tk.END, f"{fid} | {uuid} | {fecha} | ${total} | {status} | {tipo}")

    if not rows:
        listbox_canceladas.insert(tk.END, "⚠️ No hay facturas Globales canceladas")

# ================= GUI =================
root = tk.Tk()
root.title("CFDI Global GUI v5")

# Contador
lbl_count = tk.Label(root, text="Conceptos libres: 0", font=("Arial", 10, "bold"))
lbl_count.pack()



tk.Label(root, text="Conceptos disponibles (Libres):").pack()
conceptos = obtener_conceptos_libres()
listbox_conceptos = tk.Listbox(root, selectmode=tk.MULTIPLE, width=100)
for c in conceptos:
    listbox_conceptos.insert(tk.END, f"{c[0]} - {c[2]} (${c[6]})")
listbox_conceptos.pack()

# Botón seleccionar todos
btn_select_all = tk.Button(root, text="Seleccionar Todos", command=seleccionar_todos_conceptos)
btn_select_all.pack(pady=5)


btn1 = tk.Button(root, text="1. Generar CFDI", command=generar_cfdi_gui)
btn1.pack(pady=5)

btn2 = tk.Button(root, text="2. Enviar a Timbrar", command=enviar_cfdi_gui)
btn2.pack(pady=5)

btn3 = tk.Button(root, text="3. Consultar Estatus", command=consultar_estatus_gui)
btn3.pack(pady=5)

tk.Label(root, text="Facturas:").pack()
listbox_facturas = tk.Listbox(root, width=100)
listbox_facturas.pack()

btn4 = tk.Button(root, text="Cancelar Factura", command=cancelar_factura_gui)
btn4.pack(pady=10)

btn6 = tk.Button(root, text="Abrir Refacturación GUI", command=abrir_refacturacion_gui)
btn6.pack(pady=5)

btn_ver_canceladas = tk.Button(root, text="📂 Ver Globales Canceladas", command=ver_canceladas_globales)
btn_ver_canceladas.pack(pady=5)

refrescar_facturas()
refrescar_conceptos()
root.mainloop()
