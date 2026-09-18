"""Persistencia en Supabase. Un repositorio por tabla, funciones pequeñas.

Sin credenciales (desarrollo local o secretos aún no configurados) todo
funciona contra `st.session_state`: el esqueleto arranca igual y la interfaz
avisa de que no hay persistencia. Cualquier error de red devuelve el valor
neutro (lista vacía, "") en vez de romper el análisis.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

import config_secretos


@st.cache_resource(show_spinner=False)
def _cliente():
    url, key = config_secretos.supabase()
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def disponible() -> bool:
    return _cliente() is not None


def _memoria(clave: str, defecto):
    return st.session_state.setdefault(f"_mem_{clave}", defecto)


# ---------------------------------------------------------------- favoritos --
def listar_favoritos() -> list[str]:
    cli = _cliente()
    if cli is None:
        return sorted(_memoria("favoritos", set()))
    try:
        filas = cli.table("favoritos").select("ticker").order("ticker").execute().data
        return [f["ticker"] for f in filas]
    except Exception:
        return []


def es_favorito(ticker: str) -> bool:
    return ticker in listar_favoritos()


def alternar_favorito(ticker: str) -> bool:
    """Añade o quita. Devuelve el estado nuevo (True = ahora es favorito)."""
    cli = _cliente()
    if cli is None:
        favs = _memoria("favoritos", set())
        if ticker in favs:
            favs.discard(ticker)
            return False
        favs.add(ticker)
        return True
    try:
        if es_favorito(ticker):
            cli.table("favoritos").delete().eq("ticker", ticker).execute()
            return False
        cli.table("favoritos").insert({"ticker": ticker}).execute()
        return True
    except Exception:
        return es_favorito(ticker)


# -------------------------------------------------------------- anotaciones --
# Desde la sesión 6 cada nota es una fila con su fecha (anotaciones_entradas);
# la tabla `anotaciones` (un texto por ticker) queda migrada por la 004.
def listar_anotaciones(ticker: str) -> list[dict]:
    """Notas del ticker, más reciente primero: [{id, texto, creado_en}]."""
    cli = _cliente()
    if cli is None:
        return list(reversed(_memoria("anotaciones", {}).get(ticker, [])))
    try:
        return (cli.table("anotaciones_entradas").select("id,texto,creado_en").eq("ticker", ticker)
                .order("creado_en", desc=True).execute().data or [])
    except Exception:
        return []


def anadir_anotacion(ticker: str, texto: str) -> bool:
    """Añade una nota; la fecha la pone la base de datos (o el reloj local
    sin Supabase) y viaja siempre con la nota."""
    texto = (texto or "").strip()
    if not texto:
        return False
    cli = _cliente()
    if cli is None:
        notas = _memoria("anotaciones", {}).setdefault(ticker, [])
        notas.append({"id": -(len(notas) + 1), "texto": texto, "creado_en": datetime.now(timezone.utc).isoformat()})
        return True
    try:
        cli.table("anotaciones_entradas").insert({"ticker": ticker, "texto": texto}).execute()
        return True
    except Exception:
        return False


def eliminar_anotacion(ticker: str, nota_id: int) -> bool:
    cli = _cliente()
    if cli is None:
        notas = _memoria("anotaciones", {}).get(ticker, [])
        notas[:] = [n for n in notas if n.get("id") != nota_id]
        return True
    try:
        cli.table("anotaciones_entradas").delete().eq("id", nota_id).execute()
        return True
    except Exception:
        return False


# -------------------------------------------------------- diario y análisis --
def registrar_decision(ticker: str, accion: str, motivo: str, plan_id: int | None = None) -> None:
    cli = _cliente()
    if cli is None:
        _memoria("diario", []).append({"ticker": ticker, "accion": accion, "motivo": motivo})
        return
    try:
        cli.table("diario_decisiones").insert({
            "ticker": ticker, "accion": accion, "motivo": motivo, "plan_id": plan_id,
        }).execute()
    except Exception:
        pass


def guardar_analisis(fila: dict) -> bool:
    """Histórico de análisis con deduplicación por (ticker, fecha, versión)."""
    cli = _cliente()
    if cli is None:
        return False
    try:
        cli.table("analisis_historico").upsert(
            fila, on_conflict="ticker,fecha_analisis,motor_version"
        ).execute()
        return True
    except Exception:
        return False


def listar_screener(desde: str, origen: str = "cron") -> list[dict]:
    """Último análisis persistido de cada ticker con ese origen desde la
    fecha indicada (modo Screener del Rastreador): UNA consulta paginada,
    el más reciente de cada ticker manda. Sin JSON de entradas ni plan."""
    from config_settings import SCREENER_MAX_FILAS
    cli = _cliente()
    if cli is None:
        return []
    columnas = ("ticker,fecha_analisis,motor_version,precio,divisa,nombre,sector,calidad,fair_value,upside_pct,"
                "timing,timing_bruto,senal_timing,veredicto,perfil,banda,plan")
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, SCREENER_MAX_FILAS, paso):
            lote = (cli.table("analisis_historico").select(columnas).eq("origen", origen)
                    .gte("fecha_analisis", desde).order("fecha_analisis", desc=True).order("id", desc=True)
                    .range(inicio, inicio + paso - 1).execute().data or [])
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return []
    ultimos: dict[str, dict] = {}
    for f in filas:
        ultimos.setdefault(f["ticker"], f)
    return list(ultimos.values())


# ------------------------------------------------------------ paper trading --
def guardar_plan_paper(fila: dict) -> int | None:
    """Inserta un plan en `paper_planes` (estado inicial 'vigilancia').
    Devuelve el id creado, o un id negativo en memoria si no hay Supabase, y
    None si la escritura falla."""
    cli = _cliente()
    if cli is None:
        planes = _memoria("paper_planes", [])
        fila = {**fila, "id": -(len(planes) + 1), "estado": "vigilancia",
                "creado_en": datetime.now(timezone.utc).isoformat()}
        planes.append(fila)
        return fila["id"]
    try:
        r = cli.table("paper_planes").insert({**fila, "estado": "vigilancia"}).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def listar_planes_paper(estados: tuple[str, ...] | None = None) -> list[dict]:
    """Planes guardados, más reciente primero; `estados` filtra si se indica."""
    cli = _cliente()
    if cli is None:
        planes = list(reversed(_memoria("paper_planes", [])))
        return [p for p in planes if not estados or p.get("estado") in estados]
    try:
        q = cli.table("paper_planes").select("*").order("creado_en", desc=True)
        if estados:
            q = q.in_("estado", list(estados))
        return q.execute().data or []
    except Exception:
        return []


def plan_activo_para(ticker: str) -> dict | None:
    """Último plan no descartado ni cerrado del ticker (evita duplicar planes)."""
    from config_settings import PAPER_ESTADOS_ACTIVOS
    for p in listar_planes_paper(PAPER_ESTADOS_ACTIVOS):
        if p.get("ticker") == ticker:
            return p
    return None


def actualizar_plan_paper(plan_id: int, campos: dict) -> bool:
    """Cambia estado, capital... de un plan. Sella `actualizado_en`."""
    cli = _cliente()
    if cli is None:
        for p in _memoria("paper_planes", []):
            if p.get("id") == plan_id:
                p.update(campos)
                return True
        return False
    try:
        cli.table("paper_planes").update({
            **campos, "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }).eq("id", plan_id).execute()
        return True
    except Exception:
        return False


def eliminar_plan_paper(plan_id: int) -> bool:
    """Borra el plan, sus ejecuciones (cascada en BD) y las operaciones
    'paper' que esas ejecuciones crearon en el libro: un plan borrado no
    puede dejar rastro en el rendimiento simulado."""
    cli = _cliente()
    if cli is None:
        planes = _memoria("paper_planes", [])
        planes[:] = [p for p in planes if p.get("id") != plan_id]
        ejec = _memoria("paper_ejecuciones", [])
        ejec[:] = [e for e in ejec if e.get("plan_id") != plan_id]
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if not (o.get("origen") == "paper" and o.get("plan_id") == plan_id)]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("origen", "paper").eq("plan_id", plan_id).execute()
        cli.table("paper_planes").delete().eq("id", plan_id).execute()
        return True
    except Exception:
        return False


def listar_ejecuciones_paper(plan_ids: tuple[int, ...] | None = None) -> list[dict]:
    """Ejecuciones de nivel, más antigua primero; una consulta para N planes."""
    cli = _cliente()
    if cli is None:
        ejec = _memoria("paper_ejecuciones", [])
        return [e for e in ejec if plan_ids is None or e.get("plan_id") in plan_ids]
    try:
        q = cli.table("paper_ejecuciones").select("*").order("fecha").order("id")
        if plan_ids is not None:
            if not plan_ids:
                return []
            q = q.in_("plan_id", list(plan_ids))
        return q.execute().data or []
    except Exception:
        return []


def registrar_ejecucion_paper(fila: dict) -> int | None:
    cli = _cliente()
    if cli is None:
        ejec = _memoria("paper_ejecuciones", [])
        fila = {**fila, "id": -(len(ejec) + 1)}
        ejec.append(fila)
        return fila["id"]
    try:
        r = cli.table("paper_ejecuciones").insert(fila).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def ejecutar_nivel_paper(plan: dict, ejecuciones: list[dict], nivel: str, precio: float, fecha, acciones: float,
                         fx: float | None, capital: float | None = None, automatica: bool = False) -> dict | None:
    """Flujo completo de una ejecución de nivel (manual desde la vista o
    automática desde la vista/cron): capital del plan si es la primera
    entrada -> operación 'paper' en el libro (en EUR, si la divisa es
    convertible: `fx` es EUR por unidad de la divisa del plan el día de la
    ejecución) -> fila en paper_ejecuciones -> estado derivado -> diario.
    Devuelve la fila de ejecución registrada o None si falló."""
    from config_settings import PAPER_NIVELES_ENTRADA
    import core_paper
    pid = plan["id"]
    if capital is not None:
        actualizar_plan_paper(pid, {"capital_eur": capital})
        plan["capital_eur"] = capital
    precio_eur = precio * fx if fx is not None else None
    op_id = None
    if precio_eur is not None:
        op_id = insertar_operacion({
            "ticker": plan["ticker"], "tipo": "compra" if nivel in PAPER_NIVELES_ENTRADA else "venta",
            "fecha": fecha.isoformat(), "acciones": float(acciones), "precio_eur": float(precio_eur), "comision_eur": 0.0,
            "origen": "paper", "plan_id": pid if pid > 0 else None,
            "nota": f"Paper {nivel}" + (" (automática)" if automatica else ""),
            "divisa": plan.get("divisa"), "precio_origen": float(precio), "fx_aplicado": fx,
        })
    fila = core_paper.fila_ejecucion(pid, nivel, fecha, precio, acciones, op_id if op_id and op_id > 0 else None,
                                     automatica)
    ejec_id = registrar_ejecucion_paper(fila)
    if ejec_id is None:
        if op_id is not None:
            eliminar_operacion(op_id)
        return None
    fila["id"] = ejec_id
    nuevo = core_paper.estado(plan, ejecuciones + [fila])
    if nuevo != plan.get("estado"):
        actualizar_plan_paper(pid, {"estado": nuevo})
        plan["estado"] = nuevo
    registrar_decision(plan["ticker"], "ejecutar_nivel",
                       f"{nivel} a {precio:g} {plan.get('divisa') or ''}" + (" · automática al alcanzar el nivel" if automatica else ""),
                       pid if pid > 0 else None)
    return fila


def ultimos_analisis(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Último análisis guardado de cada ticker: {ticker: {fecha, veredicto,
    upside_pct, calidad, timing, senal_timing, fair_value, sector}}. UNA
    consulta para N tickers; el sector sale del JSON `entradas`. Lo usan la
    exposición sectorial de Cartera (cero peticiones a Yahoo para lo ya
    analizado) y el veto de la recomendación por posición."""
    cli = _cliente()
    if cli is None or not tickers:
        return {}
    try:
        filas = (cli.table("analisis_historico")
                 .select("ticker,fecha_analisis,veredicto,upside_pct,calidad,timing,senal_timing,fair_value,entradas")
                 .in_("ticker", list(tickers)).order("fecha_analisis", desc=True).limit(len(tickers) * 5)
                 .execute().data or [])
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for f in filas:                                  # más reciente primero: el primero que aparece manda
        if f["ticker"] in out:
            continue
        out[f["ticker"]] = {k: f.get(k) for k in ("veredicto", "upside_pct", "calidad", "timing", "senal_timing", "fair_value")}
        out[f["ticker"]]["fecha"] = f.get("fecha_analisis")
        out[f["ticker"]]["sector"] = (f.get("entradas") or {}).get("sector")
    return out


def sectores_conocidos(tickers: tuple[str, ...]) -> dict[str, str]:
    """Sector de cada ticker según su ÚLTIMO análisis guardado."""
    return {t: a["sector"] for t, a in ultimos_analisis(tickers).items() if a.get("sector")}


def listar_analisis(desde: str | None = None, hasta: str | None = None,
                    origenes: tuple[str, ...] | None = ("individual", "rastreador")) -> list[dict]:
    """Filas de `analisis_historico` (sin el JSON de entradas) para la
    evaluación de señales del Rastreador, paginadas, más antigua primero.
    Por defecto EXCLUYE el origen 'cron': 500 filas por noche harían
    inabarcable la descarga de cierres de la evaluación; las señales del
    screener se evalúan cuando se abren en vivo o individualmente."""
    cli = _cliente()
    if cli is None:
        return []
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, 20000, paso):
            q = (cli.table("analisis_historico")
                 .select("id,ticker,fecha_analisis,motor_version,precio,divisa,calidad,fair_value,upside_pct,timing,"
                         "senal_timing,veredicto,plan,origen")
                 .order("fecha_analisis").order("id"))
            if desde:
                q = q.gte("fecha_analisis", desde)
            if hasta:
                q = q.lte("fecha_analisis", hasta)
            if origenes:
                q = q.in_("origen", list(origenes))
            lote = q.range(inicio, inicio + paso - 1).execute().data or []
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return filas
    return filas


def guardar_backtest(filas: list[dict]) -> bool:
    """Retornos a 3/6/12 meses de cada señal, deduplicados por (versión,
    ticker, fecha): se reescriben conforme se cumplen horizontes."""
    cli = _cliente()
    if cli is None or not filas:
        return False
    try:
        cli.table("backtest_resultados").upsert(filas, on_conflict="motor_version,ticker,fecha_senal").execute()
        return True
    except Exception:
        return False


def historial_ticker(ticker: str) -> list[dict]:
    """Análisis guardados del ticker (todos los orígenes), más antiguo
    primero, para el histórico de veredictos de Análisis Individual."""
    from config_settings import HISTORIAL_TICKER_MAX
    cli = _cliente()
    if cli is None:
        return []
    try:
        filas = (cli.table("analisis_historico")
                 .select("fecha_analisis,motor_version,origen,precio,divisa,calidad,fair_value,upside_pct,timing,timing_bruto,"
                         "senal_timing,veredicto")
                 .eq("ticker", ticker).order("fecha_analisis", desc=True).order("id", desc=True)
                 .limit(HISTORIAL_TICKER_MAX).execute().data or [])
    except Exception:
        return []
    vistos: dict[str, dict] = {}
    for f in filas:                                  # un punto por día: el más reciente del día manda
        vistos.setdefault(str(f["fecha_analisis"])[:10], f)
    return [vistos[k] for k in sorted(vistos)]


def listar_analisis_cron_en(fechas: list[str]) -> list[dict]:
    """Análisis del cron cuya fecha está en la lista (ventanas de
    evaluación): una consulta paginada, sin JSON de entradas."""
    cli = _cliente()
    if cli is None or not fechas:
        return []
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, 50000, paso):
            lote = (cli.table("analisis_historico")
                    .select("id,ticker,fecha_analisis,motor_version,precio,divisa,senal_timing,veredicto,origen")
                    .eq("origen", "cron").in_("fecha_analisis", fechas).order("id")
                    .range(inicio, inicio + paso - 1).execute().data or [])
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return filas
    return filas


def listar_backtest(origen_cron: bool = True) -> list[dict]:
    """Filas de `backtest_resultados` (evaluación persistida). Con
    `origen_cron` solo las que escribió el cron (parametros.origen = 'cron')."""
    cli = _cliente()
    if cli is None:
        return []
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, 50000, paso):
            lote = (cli.table("backtest_resultados").select("*").order("fecha_senal")
                    .range(inicio, inicio + paso - 1).execute().data or [])
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return filas
    if origen_cron:
        filas = [f for f in filas if (f.get("parametros") or {}).get("origen") == "cron"]
    return filas


def listar_comparables_todos() -> list[str]:
    """Todos los tickers que figuran como comparable validado o sugerido
    (no rechazado), en cualquier dirección: el índice virtual del cron."""
    cli = _cliente()
    if cli is None:
        m = _memoria("comparables", {})
        return sorted({p for d in m.values() for p, o in d.items() if o != "rechazado"} | set(m))
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, 20000, paso):
            lote = (cli.table("comparables").select("ticker,peer").neq("origen", "rechazado")
                    .range(inicio, inicio + paso - 1).execute().data or [])
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return []
    return sorted({f["peer"] for f in filas} | {f["ticker"] for f in filas})


# ------------------------------------------------------------------ cartera --
def listar_operaciones(origen: str = "real", ticker: str | None = None) -> list[dict]:
    """Libro de operaciones por orden cronológico (fecha, id): el orden es
    lo que hace válido el FIFO de core_cartera."""
    cli = _cliente()
    if cli is None:
        ops = [o for o in _memoria("operaciones", []) if o.get("origen") == origen]
        if ticker:
            ops = [o for o in ops if o.get("ticker") == ticker]
        return sorted(ops, key=lambda o: (str(o.get("fecha")), abs(o.get("id", 0))))   # ids en memoria: negativos
    try:
        q = cli.table("cartera_operaciones").select("*").eq("origen", origen).order("fecha").order("id")
        if ticker:
            q = q.eq("ticker", ticker)
        return q.execute().data or []
    except Exception:
        return []


def insertar_operacion(fila: dict) -> int | None:
    """Inserta una compra/venta. La validación (no vender más de lo que se
    tiene) es responsabilidad de core_cartera ANTES de llamar aquí."""
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        fila = {**fila, "id": -(len(ops) + 1), "creado_en": datetime.now(timezone.utc).isoformat()}
        fila.setdefault("origen", "real")
        ops.append(fila)
        return fila["id"]
    try:
        r = cli.table("cartera_operaciones").insert(fila).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def eliminar_operacion(op_id: int) -> bool:
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if o.get("id") != op_id]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("id", op_id).execute()
        return True
    except Exception:
        return False


def eliminar_posicion(ticker: str, origen: str = "real") -> bool:
    """Botón papelera de la ficha: borra TODAS las operaciones del ticker
    (compras y ventas). Es un borrado del libro, no una venta."""
    cli = _cliente()
    if cli is None:
        ops = _memoria("operaciones", [])
        ops[:] = [o for o in ops if not (o.get("ticker") == ticker and o.get("origen") == origen)]
        return True
    try:
        cli.table("cartera_operaciones").delete().eq("ticker", ticker).eq("origen", origen).execute()
        return True
    except Exception:
        return False


# ------------------------------------------------------------- rastreador --
def listar_universo() -> list[str]:
    """Tickers del universo propio del Rastreador (persistidos)."""
    cli = _cliente()
    if cli is None:
        return sorted(_memoria("universo", set()))
    try:
        return [f["ticker"] for f in cli.table("rastreador_universo").select("ticker").order("ticker").execute().data or []]
    except Exception:
        return []


def anadir_universo(tickers: list[str]) -> bool:
    cli = _cliente()
    tickers = [t for t in dict.fromkeys(t.strip().upper() for t in tickers) if t]
    if not tickers:
        return True
    if cli is None:
        _memoria("universo", set()).update(tickers)
        return True
    try:
        cli.table("rastreador_universo").upsert([{"ticker": t} for t in tickers], on_conflict="ticker").execute()
        return True
    except Exception:
        return False


def quitar_universo(ticker: str) -> bool:
    cli = _cliente()
    if cli is None:
        _memoria("universo", set()).discard(ticker)
        return True
    try:
        cli.table("rastreador_universo").delete().eq("ticker", ticker).execute()
        return True
    except Exception:
        return False


# ------------------------------------------------------------ comparables --
# Peer to peer (sesión 6). Un comparable MANUAL se guarda en las dos
# direcciones (si AMD es competencia de NVDA, NVDA lo es de AMD) y se quita
# de las dos; una sugerencia de Finnhub solo vive en la dirección en que se
# sembró, y al descartarla se marca 'rechazado' para no volver a sembrarla.
def listar_comparables(ticker: str) -> list[dict]:
    """[{peer, origen}] incluyendo los rechazados (el consumidor filtra)."""
    cli = _cliente()
    if cli is None:
        return [{"peer": p, "origen": o} for p, o in _memoria("comparables", {}).get(ticker, {}).items()]
    try:
        return cli.table("comparables").select("peer,origen").eq("ticker", ticker).order("peer").execute().data or []
    except Exception:
        return []


def _comp_mem(ticker: str) -> dict:
    return _memoria("comparables", {}).setdefault(ticker, {})


def sembrar_comparables(ticker: str, peers: list[str]) -> bool:
    """Guarda las sugerencias de Finnhub (origen 'finnhub') sin pisar filas
    ya existentes (manuales o rechazadas)."""
    peers = [p for p in dict.fromkeys(p.strip().upper() for p in peers) if p and p != ticker]
    if not peers:
        return True
    cli = _cliente()
    if cli is None:
        m = _comp_mem(ticker)
        for p in peers:
            m.setdefault(p, "finnhub")
        return True
    try:
        existentes = {f["peer"] for f in listar_comparables(ticker)}
        nuevos = [{"ticker": ticker, "peer": p, "origen": "finnhub"} for p in peers if p not in existentes]
        if nuevos:
            cli.table("comparables").insert(nuevos).execute()
        return True
    except Exception:
        return False


def anadir_comparable(ticker: str, peer: str) -> bool:
    """Alta manual simétrica: (ticker, peer) y (peer, ticker) con origen
    'manual' (sustituye a 'finnhub' o 'rechazado' si existían)."""
    peer = (peer or "").strip().upper()
    if not peer or peer == ticker:
        return False
    cli = _cliente()
    if cli is None:
        _comp_mem(ticker)[peer] = "manual"
        _comp_mem(peer)[ticker] = "manual"
        return True
    try:
        cli.table("comparables").upsert([{"ticker": ticker, "peer": peer, "origen": "manual"},
                                         {"ticker": peer, "peer": ticker, "origen": "manual"}],
                                        on_conflict="ticker,peer").execute()
        return True
    except Exception:
        return False


def quitar_comparable(ticker: str, peer: str, origen: str) -> bool:
    """Baja: un manual desaparece en las dos direcciones; una sugerencia de
    Finnhub pasa a 'rechazado'."""
    cli = _cliente()
    if cli is None:
        if origen == "manual":
            _comp_mem(ticker).pop(peer, None)
            _comp_mem(peer).pop(ticker, None)
        else:
            _comp_mem(ticker)[peer] = "rechazado"
        return True
    try:
        if origen == "manual":
            cli.table("comparables").delete().eq("ticker", ticker).eq("peer", peer).execute()
            cli.table("comparables").delete().eq("ticker", peer).eq("peer", ticker).execute()
        else:
            cli.table("comparables").upsert({"ticker": ticker, "peer": peer, "origen": "rechazado"},
                                            on_conflict="ticker,peer").execute()
        return True
    except Exception:
        return False


# --------------------------------------------------------------- múltiplos --
def leer_multiplos(tickers: tuple[str, ...]) -> dict[str, dict]:
    """{ticker: {nombre, sector, industria, divisa, valores, actualizado_en}}
    en UNA consulta."""
    cli = _cliente()
    if cli is None:
        m = _memoria("multiplos", {})
        return {t: m[t] for t in tickers if t in m}
    if not tickers:
        return {}
    try:
        filas = cli.table("multiplos").select("*").in_("ticker", list(tickers)).execute().data or []
        return {f["ticker"]: f for f in filas}
    except Exception:
        return {}


def guardar_multiplos(fila: dict) -> bool:
    """Upsert de los múltiplos de un ticker (cada análisis, propio o de
    comparable, refresca su fila)."""
    cli = _cliente()
    fila = {**fila, "actualizado_en": datetime.now(timezone.utc).isoformat()}
    if cli is None:
        _memoria("multiplos", {})[fila["ticker"]] = fila
        return True
    try:
        cli.table("multiplos").upsert(fila, on_conflict="ticker").execute()
        return True
    except Exception:
        return False


def listar_multiplos_todos() -> list[dict]:
    """Toda la tabla (para recalcular las medianas por sector en el cron)."""
    cli = _cliente()
    if cli is None:
        return list(_memoria("multiplos", {}).values())
    filas: list[dict] = []
    try:
        paso = 1000
        for inicio in range(0, 20000, paso):
            lote = cli.table("multiplos").select("ticker,sector,valores,actualizado_en").range(inicio, inicio + paso - 1).execute().data or []
            filas += lote
            if len(lote) < paso:
                break
    except Exception:
        return filas
    return filas


def leer_sector_referencias(sector: str | None) -> dict | None:
    """{referencias: {clave: {mediana, n}}, n, actualizado_en} del sector."""
    cli = _cliente()
    if cli is None or not sector:
        return None
    try:
        filas = cli.table("sector_referencias").select("*").eq("sector", sector).limit(1).execute().data
        return filas[0] if filas else None
    except Exception:
        return None


def guardar_sector_referencias(filas: list[dict]) -> bool:
    cli = _cliente()
    if cli is None or not filas:
        return False
    try:
        ahora = datetime.now(timezone.utc).isoformat()
        cli.table("sector_referencias").upsert([{**f, "actualizado_en": ahora} for f in filas],
                                               on_conflict="sector").execute()
        return True
    except Exception:
        return False


# -------------------------------------------------------- índices y pases --
def listar_indices() -> list[dict]:
    """Índices conocidos por el rastreo nocturno: [{nombre, activo, tickers, n, actualizado_en}]."""
    cli = _cliente()
    if cli is None:
        return list(_memoria("indices", {}).values())
    try:
        return cli.table("rastreador_indices").select("*").order("nombre").execute().data or []
    except Exception:
        return []


def guardar_indice(nombre: str, tickers: list[str] | None = None, activo: bool | None = None) -> bool:
    """Crea o actualiza un índice: sus constituyentes (con fecha) y/o si
    está activo para el rastreo nocturno."""
    cli = _cliente()
    fila: dict = {"nombre": nombre}
    if tickers is not None:
        fila.update({"tickers": tickers, "n": len(tickers), "actualizado_en": datetime.now(timezone.utc).isoformat()})
    if activo is not None:
        fila["activo"] = bool(activo)
    if cli is None:
        m = _memoria("indices", {})
        m[nombre] = {**m.get(nombre, {"activo": False, "tickers": [], "n": 0, "actualizado_en": None}), **fila}
        return True
    try:
        cli.table("rastreador_indices").upsert(fila, on_conflict="nombre").execute()
        return True
    except Exception:
        return False


def abrir_pase(indice: str, n_total: int) -> int | None:
    cli = _cliente()
    if cli is None:
        return None
    try:
        r = cli.table("rastreo_pases").insert({"indice": indice, "n_total": n_total}).execute()
        return r.data[0]["id"] if r.data else None
    except Exception:
        return None


def cerrar_pase(pase_id: int | None, estado: str, n_ok: int, n_error: int, detalle: dict | None = None) -> None:
    cli = _cliente()
    if cli is None or pase_id is None:
        return
    try:
        cli.table("rastreo_pases").update({"fin": datetime.now(timezone.utc).isoformat(), "estado": estado,
                                          "n_ok": n_ok, "n_error": n_error, "detalle": detalle}).eq("id", pase_id).execute()
    except Exception:
        pass


def ultimos_pases(n: int = 5) -> list[dict]:
    cli = _cliente()
    if cli is None:
        return []
    try:
        return cli.table("rastreo_pases").select("*").order("inicio", desc=True).limit(n).execute().data or []
    except Exception:
        return []


# ---------------------------------------------------------------- alertas --
def alertas_ya_enviadas(claves: list[str]) -> set[str]:
    """Claves de deduplicación ya registradas (una consulta)."""
    cli = _cliente()
    if cli is None or not claves:
        return set()
    try:
        filas = cli.table("alertas_enviadas").select("clave_dedup").in_("clave_dedup", claves).execute().data or []
        return {f["clave_dedup"] for f in filas}
    except Exception:
        return set()


def registrar_alerta(tipo: str, ticker: str, clave: str) -> bool:
    cli = _cliente()
    if cli is None:
        return False
    try:
        cli.table("alertas_enviadas").upsert({"tipo": tipo, "ticker": ticker, "clave_dedup": clave},
                                             on_conflict="clave_dedup").execute()
        return True
    except Exception:
        return False
