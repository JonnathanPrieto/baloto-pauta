#!/usr/bin/env python3
"""
Actualiza data.json del dashboard "Impacto de pauta Baloto" con datos de Zoho Analytics.

Corre todos los días desde GitHub Actions (.github/workflows/diario.yml).
Solo usa la librería estándar de Python.

Variables de entorno (se guardan como secretos del repositorio):
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN   -> Self Client de Zoho (scope ZohoAnalytics.data.read)
  ZOHO_ORG_ID        (opcional, por defecto 855872271)          -> organización crmbaloto
  ZOHO_WORKSPACE_ID  (opcional, por defecto 2917853000000155002) -> workspace "Zoho CRM Reports"
  ZOHO_ACCOUNTS_URL  (opcional, por defecto https://accounts.zoho.com)
  ZOHO_ANALYTICS_URL (opcional, por defecto https://analytics.zoho.com)

Si algo falla o los datos del último día no están completos, el script termina con error
y NO modifica data.json: la página sigue mostrando la última versión buena.
"""
import csv
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------- configuración
ORG_ID = os.environ.get("ZOHO_ORG_ID", "855872271")
WORKSPACE_ID = os.environ.get("ZOHO_WORKSPACE_ID", "2917853000000155002")
ACCOUNTS_URL = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/")
ANALYTICS_URL = os.environ.get("ZOHO_ANALYTICS_URL", "https://analytics.zoho.com").rstrip("/")

INICIO_MENSUAL = date(2026, 2, 1)   # primer mes del resumen mensual
INICIO_DIARIO = date(2026, 10, 1)   # desde aquí GA4 mide el registro con el evento nuevo
EVENTO_NUEVO_DESDE = date(2026, 10, 1)

T_GA = '"Registros_pauta_GA (Google Analytics 4 (GA4))"'
T_APUESTAS = '"Apuestas All"'
T_INV = '"[Baloto] Fuente de datos GA4"'

EV_NUEVO = "registro_exitoso_sin_contrasena"
EV_ANTERIOR = "Registro_Exitoso"

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
MES_CORTO = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

BOGOTA = timezone(timedelta(hours=-5))
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_JSON = os.path.join(RAIZ, "data.json")


def log(*a):
    print(datetime.now(BOGOTA).strftime("%H:%M:%S"), *a, flush=True)


def fallar(msg):
    print(f"::error::{msg}", flush=True)
    sys.exit(1)


# ---------------------------------------------------------------- API de Zoho
def http(url, method="GET", data=None, headers=None, intentos=4):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # noqa: BLE001
            if i == intentos - 1:
                raise
            log(f"  reintento {i + 1} tras error: {e}")
            time.sleep(10 * (i + 1))


def token():
    q = urllib.parse.urlencode({
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type": "refresh_token",
    })
    r = json.loads(http(f"{ACCOUNTS_URL}/oauth/v2/token?{q}", method="POST", data=b""))
    if "access_token" not in r:
        fallar(f"Zoho no entregó el token de acceso: {r}")
    return r["access_token"]


def consulta(tok, nombre, sql, espera_max=25 * 60):
    """Crea un trabajo de exportación con SQL, espera a que termine y devuelve las filas (lista de dicts)."""
    h = {"Authorization": f"Zoho-oauthtoken {tok}", "ZANALYTICS-ORGID": ORG_ID}
    config = urllib.parse.quote(json.dumps({"sqlQuery": sql, "responseFormat": "csv"}))
    base = f"{ANALYTICS_URL}/restapi/v2/bulk/workspaces/{WORKSPACE_ID}"
    r = json.loads(http(f"{base}/data?CONFIG={config}", headers=h))
    job = r.get("data", {}).get("jobId")
    if not job:
        fallar(f"[{nombre}] no se pudo crear la consulta: {r}")
    log(f"[{nombre}] consulta creada ({job})")
    t0 = time.time()
    while True:
        time.sleep(15)
        st = json.loads(http(f"{base}/exportjobs/{job}", headers=h)).get("data", {})
        code = str(st.get("jobCode"))
        if code == "1004":
            break
        if code in ("1003", "1005"):
            fallar(f"[{nombre}] la consulta falló en Zoho: {st}")
        if time.time() - t0 > espera_max:
            fallar(f"[{nombre}] la consulta tardó más de {espera_max // 60} minutos")
    filas = list(csv.DictReader(io.StringIO(http(f"{base}/exportjobs/{job}/data", headers=h))))
    log(f"[{nombre}] {len(filas)} filas")
    return filas


# ---------------------------------------------------------------- utilidades
def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except ValueError:
        return 0.0


def dias(desde, hasta):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def fin_de_mes(d):
    sig = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return sig - timedelta(days=1)


def mes_siguiente(y, m):
    return (y + (m == 12), m % 12 + 1)


# grupos de campaña (mismo orden que CAMP_DEF en index.html)
GRUPOS_GA = [
    "\"Session campaign\" like '%search_category%'",
    "\"Session campaign\" like '%influencers%'",
    "\"Session campaign\" like '%tiktok_acq_conversion-registros%'",
    "\"Session campaign\" like '%search_competencia%'",
    "\"Session campaign\" like '%pmax%'",
    "\"Session campaign\" like 'adcom_miloto%'",
    "\"Session campaign\" like '%ret_acumulado%' and \"Session campaign\" like 'adcom_baloto%'",
    "\"Session campaign\" like 'adcom_colorloto%'",
    "\"Session campaign\" like '%promocional-italia%'",
]
GRUPOS_INV = [g.replace('"Session campaign"', '"Campaign Name"') for g in GRUPOS_GA]
PAUTA_GA = ("(\"Session campaign\" like 'adcom_%' or \"Session source / medium\" like '%/ paid' "
            "or \"Session source / medium\" like '%/ cpc')")


def main():
    hoy = datetime.now(BOGOTA).date()
    ayer = hoy - timedelta(days=1)
    tok = token()

    # 1) ¿hasta qué día hay datos completos de GA4 y de inversión?
    r = consulta(tok, "corte GA4", f"select max(\"Date\") as ultimo from {T_GA} where \"Event name\"='{EV_NUEVO}'")
    ult_ga = datetime.strptime(r[0]["ultimo"][:10], "%Y-%m-%d").date()
    r = consulta(tok, "corte inversión", f"select max(\"Date\") as ultimo from {T_INV} where \"Fuente\"='Plataforma'")
    ult_inv = datetime.strptime(r[0]["ultimo"][:10], "%Y-%m-%d").date()
    corte = min(ayer, ult_ga, ult_inv)
    log(f"Corte: {corte} (GA4 hasta {ult_ga}, inversión hasta {ult_inv})")

    previo = {}
    if os.path.exists(DATA_JSON):
        previo = json.load(open(DATA_JSON, encoding="utf-8"))
        corte_prev = date.fromisoformat(previo.get("meta", {}).get("corte", "2000-01-01"))
        if corte < corte_prev:
            fallar(f"Los datos de Zoho llegan hasta {corte}, antes que la versión publicada ({corte_prev}). No se actualiza.")
    d1 = (corte + timedelta(days=1)).isoformat()
    ci, cf = INICIO_DIARIO.isoformat(), corte.isoformat()

    # 2) DIARIO: registros GA4 por día, plataforma y grupo de campaña
    grupos = ", ".join(f"sum(case when {g} then \"Event count\" else 0 end) as c{i}" for i, g in enumerate(GRUPOS_GA))
    ga_dia = consulta(tok, "GA4 diario", f"""
        select DATE_FORMAT("Date",'%Y-%m-%d') as dia, sum("Event count") as total,
          sum(case when "Session campaign" like 'adcom_%' and "Session source / medium" like 'google%' then "Event count" else 0 end) as google,
          sum(case when "Session campaign" like 'adcom_%' and "Session source / medium" like '%tiktok%' then "Event count" else 0 end) as tiktok,
          sum(case when ("Session campaign" like 'adcom_%' and ("Session source / medium" like '%facebook%' or "Session source / medium" like '%meta%')) or "Session source / medium" like '%/ paid' then "Event count" else 0 end) as meta,
          {grupos}
        from {T_GA} where "Event name"='{EV_NUEVO}' and "Date" between '{ci}' and '{cf}'
        group by DATE_FORMAT("Date",'%Y-%m-%d')""")
    ga_dia = {r["dia"]: r for r in ga_dia}

    # 3) DIARIO: compradores nuevos (primera apuesta) por día
    nue = consulta(tok, "compradores nuevos diario", f"""
        SELECT DATE_FORMAT(p.f1,'%Y-%m-%d') AS dia, COUNT(DISTINCT p.uid) AS nuevos
        FROM (SELECT "ID User" AS uid, MIN("Fecha y hora apuesta") AS f1 FROM {T_APUESTAS} GROUP BY "ID User"
              HAVING MIN("Fecha y hora apuesta") >= '{ci}' AND MIN("Fecha y hora apuesta") < '{d1}') p
        GROUP BY DATE_FORMAT(p.f1,'%Y-%m-%d')""")
    nue = {r["dia"]: int(num(r["nuevos"])) for r in nue}

    # 4) DIARIO: inversión por día, plataforma y grupo de campaña
    ginv = ", ".join(f"sum(case when {g} then \"Amount Spent\" else 0 end) as c{i}" for i, g in enumerate(GRUPOS_INV))
    inv_dia = consulta(tok, "inversión diaria", f"""
        select DATE_FORMAT("Date",'%Y-%m-%d') as dia, sum("Amount Spent") as inv_total,
          sum(case when "Medio"='Google' then "Amount Spent" else 0 end) as inv_google,
          sum(case when "Medio"='Facebook' then "Amount Spent" else 0 end) as inv_meta,
          sum(case when "Medio"='TikTok' then "Amount Spent" else 0 end) as inv_tiktok,
          sum(case when "Etapa" in ('ACQUISITION','AWARENESS') then "Amount Spent" else 0 end) as inv_adq,
          {ginv}
        from {T_INV} where "Fuente"='Plataforma' and "Date" >= '{ci}' and "Date" < '{d1}'
        group by DATE_FORMAT("Date",'%Y-%m-%d')""")
    inv_dia = {r["dia"]: r for r in inv_dia}

    # validación del último día: sin registros o sin compradores nuevos, algo no sincronizó
    k = corte.isoformat()
    if num(ga_dia.get(k, {}).get("total")) <= 0:
        fallar(f"GA4 no tiene registros para {k}; no se actualiza.")
    if nue.get(k, 0) <= 0:
        fallar(f"El CRM no tiene compradores nuevos para {k}; puede que las apuestas no hayan sincronizado. No se actualiza.")

    dias_out, camp_reg, camp_inv = [], [], []
    for d in dias(INICIO_DIARIO, corte):
        k = d.isoformat()
        g, v = ga_dia.get(k, {}), inv_dia.get(k, {})
        gg, tk, mt = int(num(g.get("google"))), int(num(g.get("tiktok"))), int(num(g.get("meta")))
        dias_out.append([k, int(num(g.get("total"))), gg, tk, mt, nue.get(k, 0),
                         round(num(v.get("inv_total"))), round(num(v.get("inv_google"))), round(num(v.get("inv_meta"))),
                         round(num(v.get("inv_tiktok"))), round(num(v.get("inv_adq")))])
        camp_reg.append([int(num(g.get(f"c{i}"))) for i in range(9)] + [gg + tk + mt])
        camp_inv.append([round(num(v.get(f"c{i}"))) for i in range(9)] + [round(num(v.get("inv_total")))])

    # 5) MENSUAL: cohortes de compradores nuevos
    mi = INICIO_MENSUAL.isoformat()
    coh = consulta(tok, "cohortes mensuales", f"""
        SELECT YEAR(p.f1) AS anio, MONTH(p.f1) AS mes, COUNT(DISTINCT p.uid) AS nuevos,
          SUM(CASE WHEN YEAR(a."Fecha y hora apuesta")*12+MONTH(a."Fecha y hora apuesta") = YEAR(p.f1)*12+MONTH(p.f1) THEN a."Importe" ELSE 0 END) AS importe_mes1,
          COUNT(DISTINCT CASE WHEN YEAR(a."Fecha y hora apuesta")*12+MONTH(a."Fecha y hora apuesta") = YEAR(p.f1)*12+MONTH(p.f1)+1 THEN p.uid END) AS recompra_mes2
        FROM (SELECT "ID User" AS uid, MIN("Fecha y hora apuesta") AS f1 FROM {T_APUESTAS} GROUP BY "ID User"
              HAVING MIN("Fecha y hora apuesta") >= '{mi}' AND MIN("Fecha y hora apuesta") < '{d1}') p
        INNER JOIN {T_APUESTAS} a ON a."ID User" = p.uid
        WHERE a."Fecha y hora apuesta" < '{d1}'
        GROUP BY YEAR(p.f1), MONTH(p.f1)""")
    coh = {(int(num(r["anio"])), int(num(r["mes"]))): r for r in coh}

    # 6) MENSUAL: registros GA4 (evento anterior hasta septiembre, nuevo desde octubre)
    en = EVENTO_NUEVO_DESDE.isoformat()
    filtro_ev = (f"((\"Date\" < '{en}' and \"Event name\" in ('{EV_ANTERIOR}','{EV_NUEVO}')) "
                 f"or (\"Date\" >= '{en}' and \"Event name\"='{EV_NUEVO}'))")
    ga_mes = consulta(tok, "GA4 mensual", f"""
        select year("Date") as anio, month("Date") as mes, sum("Event count") as total,
          sum(case when {PAUTA_GA} then "Event count" else 0 end) as pauta
        from {T_GA} where {filtro_ev} and "Date" between '{mi}' and '{cf}'
        group by year("Date"), month("Date")""")
    ga_mes = {(int(num(r["anio"])), int(num(r["mes"]))): r for r in ga_mes}

    # 7) MENSUAL: inversión total y de adquisición + awareness
    inv_mes = consulta(tok, "inversión mensual", f"""
        select year("Date") as anio, month("Date") as mes, sum("Amount Spent") as inv,
          sum(case when "Etapa" in ('ACQUISITION','AWARENESS') then "Amount Spent" else 0 end) as inv_adq
        from {T_INV} where "Fuente"='Plataforma' and "Date" >= '{mi}' and "Date" < '{d1}'
        group by year("Date"), month("Date")""")
    inv_mes = {(int(num(r["anio"])), int(num(r["mes"]))): r for r in inv_mes}

    mensual = []
    y, m = INICIO_MENSUAL.year, INICIO_MENSUAL.month
    while (y, m) <= (corte.year, corte.month):
        c, g, v = coh.get((y, m)), ga_mes.get((y, m)), inv_mes.get((y, m))
        if not c or not g:
            fallar(f"Faltan datos del mes {y}-{m:02d} (cohortes o GA4).")
        parcial = corte < fin_de_mes(date(y, m, 1))
        ys, ms = mes_siguiente(y, m)
        recompra_medible = fin_de_mes(date(ys, ms, 1)) <= corte
        item = {
            "m": MES_CORTO[m - 1],
            "full": MESES[m - 1] + (f" (al {corte.day})" if parcial else ""),
            "n": int(num(c["nuevos"])),
            "imp": round(num(c["importe_mes1"])),
            "r": int(num(c["recompra_mes2"])) if recompra_medible else None,
            "g": int(num(g["total"])),
            "p": int(num(g["pauta"])),
            "inv": round(num(v["inv"])) if v else 0,
            "ia": round(num(v["inv_adq"])) if v else 0,
            "ym": f"{y}-{m:02d}",
        }
        if date(y, m, 1) >= EVENTO_NUEVO_DESDE:
            item["newEv"] = True
        if not recompra_medible:
            item["est"] = True
        if parcial:
            item["partial"] = True
        mensual.append(item)
        y, m = ys, ms

    datos = {
        "mensual": mensual,
        "diario": {"dias": dias_out, "camp_reg": camp_reg, "camp_inv": camp_inv},
        "meta": {"corte": corte.isoformat(),
                 "actualizado": datetime.now(BOGOTA).isoformat(timespec="seconds"),
                 "fuente": "Zoho Analytics · workspace Zoho CRM Reports"},
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    ult = mensual[-1]
    log(f"data.json actualizado al {corte}: {len(dias_out)} días, {len(mensual)} meses; "
        f"último mes {ult['full']}: {ult['n']} compradores nuevos, {ult['p']}/{ult['g']} registros de pauta, inversión {ult['inv']:,}")


if __name__ == "__main__":
    for v in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
        if not os.environ.get(v):
            fallar(f"Falta el secreto {v} en el repositorio.")
    main()
