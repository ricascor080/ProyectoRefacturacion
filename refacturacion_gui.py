#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
import sqlite3, os, datetime, base64, io, zipfile, json, re
from tkinter import messagebox
from pathlib import Path
from lxml import etree as ET
from suds.client import Client

# ================= CONFIG =================
DB_PATH = "conceptos.db"
REF_DIR = Path("refacturacion"); REF_DIR.mkdir(exist_ok=True)

WSDL_ASYNC = "https://demo-facturacion.finkok.com/servicios/soap/async.wsdl"
WSDL_CANCEL = "https://demo-facturacion.finkok.com/servicios/soap/cancel.wsdl"

FINKOK_USER = os.getenv("FINKOK_USER", "ricascor080@gmail.com")
FINKOK_PASS = os.getenv("FINKOK_PASS", "Ricas002385.")
TAXPAYER_ID = "EKU9003173C9"
CER_PATH = "cer.pem"
KEY_PATH = "key.pem"

# Datos del receptor nominativo
NOMINATIVO_RFC = "CTE950627K46"
NOMINATIVO_NOMBRE = "COMERCIALIZADORA TEODORIKAS"
NOMINATIVO_CP = "57740"
NOMINATIVO_REGIMEN = "601"
NOMINATIVO_USO = "G03"

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
    for c in ("file","zip","application_zipped","application_zip","data"):
        if hasattr(result_obj, c):
            val = getattr(result_obj, c)
            if val: return val
    return None

# ================= DB =================
def listar_facturas(status=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if status:
        cur.execute("SELECT id, uuid, fecha, total, status, tipo FROM facturas WHERE status=?", (status,))
    else:
        cur.execute("SELECT id, uuid, fecha, total, status, tipo FROM facturas")
    rows = cur.fetchall()
    conn.close()
    return rows

def conceptos_por_factura(id_factura):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id_concepto FROM factura_conceptos WHERE id_factura=?", (id_factura,))
    ids = [row[0] for row in cur.fetchall()]
    conn.close()
    return ids

def obtener_conceptos_cancelados():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, clave, descripcion, unidad, cantidad, valor_unitario, importe FROM conceptos WHERE status='Cancelado'")
    rows = cur.fetchall()
    conn.close()
    return rows

def marcar_conceptos(ids, status):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("UPDATE conceptos SET status=? WHERE id=?", [(status,cid) for cid in ids])
    conn.commit(); conn.close()

def guardar_factura(uuid, total, conceptos_ids, tipo="Global", status="Timbrada"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""INSERT INTO facturas (uuid, rfc_emisor, fecha, total, status, tipo)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (uuid, TAXPAYER_ID, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), total, status, tipo))
    id_factura = cur.lastrowid
    cur.executemany("INSERT INTO factura_conceptos (id_factura, id_concepto) VALUES (?, ?)",
                    [(id_factura, cid) for cid in conceptos_ids])
    conn.commit(); conn.close()
    return uuid

# ================= PAC =================
def enviar_cfdi(xml_path, tipo="Global"):
    zip_path = REF_DIR / f"{xml_path.stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(xml_path, arcname=os.path.basename(xml_path))

    b64_path = REF_DIR / f"{xml_path.stem}.b64"
    with open(zip_path,"rb") as f, open(b64_path,"w",encoding="utf-8") as fout:
        fout.write(base64.b64encode(f.read()).decode("utf-8"))

    client = Client(WSDL_ASYNC, cache=None)
    zip_b64 = b64_path.read_text().strip()
    res = client.service.sign_multistamp(file=zip_b64, username=FINKOK_USER, password=FINKOK_PASS)
    res_dict = suds_to_builtin(res)

    rid = res_dict.get("id")
    if rid:
        (REF_DIR / f"rid_{tipo.lower()}.txt").write_text(rid,encoding="utf-8")
        return rid, "CFDI enviado correctamente"
    return None, f"Error PAC: {json.dumps(res_dict, indent=2, ensure_ascii=False)}"

def consultar_cfdi(rid, tipo="Global"):
    client = Client(WSDL_ASYNC, cache=None)
    res = client.service.get_result_multistamp(id=rid, username=FINKOK_USER, password=FINKOK_PASS)
    b64_zip = pick_base64_field(res)
    if not b64_zip: return None, "Aún no está timbrado"

    zip_bytes = base64.b64decode(b64_zip.encode("ascii"))
    zip_path = REF_DIR / f"resultado_{tipo.lower()}_{rid}.zip"
    zip_path.write_bytes(zip_bytes)

    extract_dir = REF_DIR / f"extract_{tipo.lower()}_{rid}"
    with zipfile.ZipFile(io.BytesIO(zip_bytes),"r") as zf:
        zf.extractall(extract_dir)

    for f in extract_dir.glob("*.xml"):
        tree = ET.parse(f); root = tree.getroot()
        tfd = root.find(".//{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital")
        if tfd is not None:
            return (tfd.attrib.get("UUID"), float(root.attrib.get("Total"))), "CFDI timbrado con éxito"
    return None, "No se encontró UUID en XML"

def cancelar_factura_pac(uuid):
    cer_file = encode_file_to_base64(CER_PATH)
    key_file = encode_file_to_base64(KEY_PATH)
    client = Client(WSDL_CANCEL, cache=None)
    invoices_obj = client.factory.create("ns0:UUID"); invoices_obj._UUID = uuid; invoices_obj._Motivo = "02"
    UUIDS_list = client.factory.create("ns0:UUIDArray"); UUIDS_list.UUID.append(invoices_obj)
    return str(client.service.cancel(UUIDS_list, FINKOK_USER, FINKOK_PASS, TAXPAYER_ID, cer_file, key_file))


# ================= Cancelar Factura =================
def cancelar_factura_gui():
    sel = listbox_facturas.curselection()
    if not sel:
        return messagebox.showwarning("Atención", "Selecciona una factura a cancelar")

    factura_txt = listbox_facturas.get(sel[0])
    fid = int(factura_txt.split("|")[0].strip())
    uuid = factura_txt.split("|")[1].strip()

    # Cancelar con PAC
    respuesta = cancelar_factura_pac(uuid)
    if "Folios" in respuesta or "UUID" in respuesta:
        # Cambiar estatus de conceptos a Cancelado
        ids = conceptos_por_factura(fid)
        marcar_conceptos(ids, "Cancelado")

        # Cambiar estatus de la factura
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE facturas SET status='Cancelada' WHERE id=?", (fid,))
        conn.commit(); conn.close()

        refrescar_facturas()
        refrescar_conceptos_cancelados()
        messagebox.showinfo("Cancelada", f"Factura {uuid} cancelada correctamente.\nConceptos liberados.")
    else:
        messagebox.showerror("Error PAC", f"No se pudo cancelar.\nRespuesta: {respuesta}")


# ================= CFDI Builder =================
def generar_cfdi(conceptos_sel, tipo="Global"):
    fecha_sat = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    nsmap = {'cfdi':'http://www.sat.gob.mx/cfd/4','xsi':'http://www.w3.org/2001/XMLSchema-instance'}
    schemaLocation = 'http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd'

    root = ET.Element('{http://www.sat.gob.mx/cfd/4}Comprobante', nsmap=nsmap, attrib={
        '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation': schemaLocation,
        'Version':'4.0','Serie':'FG' if tipo=="Global" else 'FI','Folio':'10001','Fecha':fecha_sat,
        'Sello':'','NoCertificado':'','Certificado':'',
        'Moneda':'MXN','TipoDeComprobante':'I','Exportacion':'01',
        'LugarExpedicion':'64000','FormaPago':'01','MetodoPago':'PUE'
    })

    if tipo == "Global":
        ET.SubElement(root,'{http://www.sat.gob.mx/cfd/4}InformacionGlobal',
            attrib={'Periodicidad':'04','Meses':'08','Año':'2025'})

    ET.SubElement(root,'{http://www.sat.gob.mx/cfd/4}Emisor',
        attrib={'Rfc':TAXPAYER_ID,'Nombre':'ESCUELA KEMPER URGATE','RegimenFiscal':'601'})

    if tipo == "Ingreso":
        ET.SubElement(root,'{http://www.sat.gob.mx/cfd/4}Receptor',
            attrib={'Rfc':NOMINATIVO_RFC,'Nombre':NOMINATIVO_NOMBRE,
                    'DomicilioFiscalReceptor':NOMINATIVO_CP,
                    'RegimenFiscalReceptor':NOMINATIVO_REGIMEN,
                    'UsoCFDI':NOMINATIVO_USO})
    else:
        ET.SubElement(root,'{http://www.sat.gob.mx/cfd/4}Receptor',
            attrib={'Rfc':'XAXX010101000','Nombre':'PUBLICO EN GENERAL',
                    'UsoCFDI':'S01','RegimenFiscalReceptor':'616','DomicilioFiscalReceptor':'64000'})

    conceptos_tag = ET.SubElement(root,'{http://www.sat.gob.mx/cfd/4}Conceptos')
    subtotal = 0.0
    for c in conceptos_sel:
        idc, clave, desc, unidad, cantidad, valor_unitario, importe = c
        subtotal += importe
        ET.SubElement(conceptos_tag,'{http://www.sat.gob.mx/cfd/4}Concepto', attrib={
            'ClaveProdServ':clave,'Descripcion':desc,'Cantidad':str(cantidad),
            'ClaveUnidad':unidad,'ValorUnitario':str(valor_unitario),
            'Importe':str(importe),'ObjetoImp':'01'
        })

    root.set('SubTotal',f'{subtotal:.2f}')
    root.set('Total',f'{subtotal:.2f}')

    xml_path = REF_DIR / f"cfdi_{tipo.lower()}_{datetime.datetime.now().strftime('%H%M%S')}.xml"
    ET.ElementTree(root).write(xml_path, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    return xml_path, subtotal, [c[0] for c in conceptos_sel]

# ================= GUI =================
root = tk.Tk()
root.title("Gestión de Refacturación CFDI")

# Facturas
tk.Label(root,text="📑 Facturas Timbradas",font=("Arial",12,"bold")).pack()
listbox_facturas = tk.Listbox(root,width=120,height=10)
listbox_facturas.pack(padx=10,pady=5)

def refrescar_facturas():
    listbox_facturas.delete(0,tk.END)
    for f in listar_facturas("Timbrada"):
        fid, uuid, fecha, total, status, tipo = f
        listbox_facturas.insert(tk.END,f"{fid} | {uuid} | {fecha} | ${total} | {status} | {tipo}")
# ================= BOTÓN DE CANCELACIÓN =================
btn_cancelar = tk.Button(root, text="❌ Cancelar Factura Seleccionada", command=cancelar_factura_gui, bg="red", fg="white")
btn_cancelar.pack(pady=5)
# Conceptos Cancelados
tk.Label(root,text="Conceptos Cancelados (para Nominativa):",font=("Arial",12,"bold")).pack()
listbox_cancelados = tk.Listbox(root,width=100,height=10,selectmode=tk.MULTIPLE)
listbox_cancelados.pack(padx=10,pady=5)

def refrescar_conceptos_cancelados():
    listbox_cancelados.delete(0,tk.END)
    for c in obtener_conceptos_cancelados():
        listbox_cancelados.insert(tk.END,f"{c[0]} - {c[2]} (${c[6]})")

# Botones para Nominativa
def generar_ingreso():
    sel = listbox_cancelados.curselection()
    if not sel: return messagebox.showwarning("Atención","Selecciona conceptos")
    conceptos_sel, ids = [], []
    for idx in sel:
        item = listbox_cancelados.get(idx)
        cid = int(item.split(" - ")[0])
        for c in obtener_conceptos_cancelados():
            if c[0]==cid: conceptos_sel.append(c)
        ids.append(cid)

    xml_path,total,ids = generar_cfdi(conceptos_sel,"Ingreso")
    global ingreso_data
    ingreso_data = {"ids":ids,"xml":xml_path,"total":total}
    messagebox.showinfo("Generado",f"CFDI Ingreso generado:\n{xml_path}")

def enviar_ingreso():
    global ingreso_data
    if not ingreso_data: return messagebox.showerror("Error","Primero genera CFDI")
    rid,msg = enviar_cfdi(ingreso_data["xml"],"Ingreso")
    if rid: messagebox.showinfo("Timbrado",f"Enviado a timbrar.\nRID: {rid}")
    else: messagebox.showerror("Error",msg)

def estatus_ingreso():
    try: rid = Path("refacturacion/rid_ingreso.txt").read_text().strip()
    except: return messagebox.showerror("Error","No hay RID Ingreso")
    res,msg = consultar_cfdi(rid,"Ingreso")
    if res:
        uuid,total = res
        guardar_factura(uuid,total,ingreso_data["ids"],"Ingreso","Timbrada")
        marcar_conceptos(ingreso_data["ids"],"Ocupado")
        refrescar_facturas(); refrescar_conceptos_cancelados()
        messagebox.showinfo("Ingreso",f"Nominativa timbrada UUID {uuid}")
    else: messagebox.showwarning("Estatus",msg)

tk.Label(root,text="⚡ Nominativa (Ingreso)").pack()
tk.Button(root,text="1. Generar Ingreso",command=generar_ingreso).pack(pady=2)
tk.Button(root,text="2. Enviar Ingreso",command=enviar_ingreso).pack(pady=2)
tk.Button(root,text="3. Estatus Ingreso",command=estatus_ingreso).pack(pady=2)

# Botones para Global
def generar_global():
    cancelados = obtener_conceptos_cancelados()
    if not cancelados: return messagebox.showwarning("Atención","No hay conceptos cancelados")
    xml_path,total,ids = generar_cfdi(cancelados,"Global")
    global global_data
    global_data = {"ids":ids,"xml":xml_path,"total":total}
    messagebox.showinfo("Generado",f"CFDI Global generado:\n{xml_path}")

def enviar_global():
    global global_data
    if not global_data: return messagebox.showerror("Error","Primero genera CFDI Global")
    rid,msg = enviar_cfdi(global_data["xml"],"Global")
    if rid: messagebox.showinfo("Timbrado",f"Global enviado a timbrar.\nRID: {rid}")
    else: messagebox.showerror("Error",msg)

def estatus_global():
    try: rid = Path("refacturacion/rid_global.txt").read_text().strip()
    except: return messagebox.showerror("Error","No hay RID Global")
    res,msg = consultar_cfdi(rid,"Global")
    if res:
        uuid,total = res
        guardar_factura(uuid,total,global_data["ids"],"Global","Timbrada")
        marcar_conceptos(global_data["ids"],"Ocupado")
        refrescar_facturas(); refrescar_conceptos_cancelados()
        messagebox.showinfo("Global",f"Factura Global timbrada UUID {uuid}")
    else: messagebox.showwarning("Estatus",msg)

tk.Label(root,text="🌍 Global Nueva").pack()
tk.Button(root,text="1. Generar Global",command=generar_global).pack(pady=2)
tk.Button(root,text="2. Enviar Global",command=enviar_global).pack(pady=2)
tk.Button(root,text="3. Estatus Global",command=estatus_global).pack(pady=2)

# Inicializar
refrescar_facturas()
refrescar_conceptos_cancelados()
root.mainloop()
