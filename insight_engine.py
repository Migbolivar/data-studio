"""
Insight Engine — BMOPS Data Studio
====================================
Calcula métricas reales sobre cualquier CSV/Excel subido por el usuario
(concentración, anomalías, tendencia, oportunidad accionable) usando
pandas puro — sin IA. Los números que salen de aquí son 100% verificables.

La IA (Hermes / DeepSeek) solo entra DESPUÉS, para traducir estos números
a lenguaje humano. Nunca calcula ni inventa cifras — eso es justo lo que
evita alucinaciones y le da credibilidad al reporte frente al cliente.

Soporta datos financieros (ventas, montos) y no financieros (encuestas,
categorías, texto). Auto-detecta el tipo de datos y adapta el análisis.

Uso típico:
    df = pd.read_csv(archivo)  # o pd.read_excel(archivo)
    resultado = generate_insights(df)
    prompt = resultado["prompt"]          # listo para mandar a la API
    metrics = resultado["metrics"]        # números crudos, por si quieres graficarlos
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# 1. DETECCIÓN AUTOMÁTICA DE COLUMNAS
# ─────────────────────────────────────────────────────────────

VALUE_KEYWORDS = [
    "total", "monto", "venta", "ventas", "revenue", "amount", "precio",
    "valor", "importe", "sales", "price", "ingreso", "ingresos", "pago"
]
ENTITY_KEYWORDS = [
    "cliente", "customer", "producto", "product", "vendedor", "categoria",
    "categoría", "sku", "item", "articulo", "artículo", "empresa", "sector"
]
DATE_KEYWORDS = [
    "fecha", "date", "dia", "día", "mes", "periodo", "período", "created", "timestamp"
]


def _detect_value_column(df: pd.DataFrame) -> str | None:
    """Encuentra la columna numérica que representa 'el dinero' o la métrica principal."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_cols:
        return None
    for col in numeric_cols:
        if any(kw in col.lower() for kw in VALUE_KEYWORDS):
            return col
    sums = df[numeric_cols].abs().sum().sort_values(ascending=False)
    return sums.index[0] if len(sums) else None


def _detect_entity_column(df: pd.DataFrame, value_col: str | None) -> str | None:
    """Encuentra la columna categórica que agrupa (cliente, producto, etc.)."""
    candidate_cols = [c for c in df.columns if c != value_col]
    object_cols = [c for c in candidate_cols if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object]
    for col in object_cols:
        if any(kw in col.lower() for kw in ENTITY_KEYWORDS):
            return col
    best_col, best_score = None, -1
    n = len(df)
    for col in object_cols:
        nunique = df[col].nunique(dropna=True)
        if n == 0 or nunique <= 1 or nunique >= n * 0.9:
            continue
        score = nunique
        if score > best_score:
            best_col, best_score = col, score
    return best_col


def _detect_date_column(df: pd.DataFrame) -> str | None:
    """Encuentra la columna de fecha, por nombre o intentando parsear."""
    for col in df.columns:
        if any(kw in col.lower() for kw in DATE_KEYWORDS):
            try:
                pd.to_datetime(df[col], errors="raise")
                return col
            except Exception:
                continue
    text_cols = [c for c in df.columns if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == object]
    for col in text_cols:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().mean() > 0.8:
                return col
        except Exception:
            continue
    return None


# ─────────────────────────────────────────────────────────────
# 1b. DETECCIÓN DE TIPO DE DATOS
# ─────────────────────────────────────────────────────────────

def _detect_data_type(df: pd.DataFrame) -> str:
    """
    Determina si el dataset es financiero, cuantitativo o cualitativo.
    Retorna: 'financial', 'quantitative', 'qualitative'
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    text_cols = df.select_dtypes(include=['object']).columns.tolist()

    # Si hay columnas numéricas con keywords financieros
    if numeric_cols:
        for col in numeric_cols:
            if any(kw in col.lower() for kw in VALUE_KEYWORDS):
                return "financial"
        # Hay numéricas pero sin keywords → cuantitativo (stats, puntuaciones, etc.)
        return "quantitative"

    # Solo texto → cualitativo (encuestas, feedback, categorías)
    return "qualitative"


# ─────────────────────────────────────────────────────────────
# 2. MÉTRICAS — Financieras / Cuantitativas
# ─────────────────────────────────────────────────────────────

def concentration_insight(df: pd.DataFrame, entity_col: str, value_col: str) -> dict | None:
    if not entity_col or not value_col:
        return None
    grouped = df.groupby(entity_col)[value_col].sum().sort_values(ascending=False)
    total = grouped.sum()
    if total == 0 or len(grouped) < 2:
        return None
    n_entities = len(grouped)
    top_20pct_n = max(1, round(n_entities * 0.2))
    top_20pct_share = grouped.iloc[:top_20pct_n].sum() / total
    top3_share = grouped.iloc[:min(3, n_entities)].sum() / total
    return {
        "entity_column": entity_col,
        "value_column": value_col,
        "total_entities": int(n_entities),
        "top_20pct_count": int(top_20pct_n),
        "top_20pct_share_of_value": round(float(top_20pct_share) * 100, 1),
        "top3_entities": grouped.index[:3].tolist(),
        "top3_share_of_value": round(float(top3_share) * 100, 1),
        "is_high_risk": bool(top3_share > 0.5),
    }


def anomaly_insight(df: pd.DataFrame, date_col: str, value_col: str) -> dict | None:
    if not date_col or not value_col:
        return None
    temp = df[[date_col, value_col]].copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp = temp.dropna(subset=[date_col, value_col])
    if len(temp) < 4:
        return None
    span_days = (temp[date_col].max() - temp[date_col].min()).days
    freq = "D" if span_days <= 60 else ("W" if span_days <= 400 else "ME")
    series = temp.set_index(date_col)[value_col].resample(freq).sum()
    if len(series) < 4 or series.std() == 0:
        return None
    z_scores = (series - series.mean()) / series.std()
    anomalies = z_scores[z_scores.abs() > 2]
    if anomalies.empty:
        return {"has_anomalies": False, "frequency": freq}
    top_anomaly_period = anomalies.abs().idxmax()
    return {
        "has_anomalies": True, "frequency": freq, "anomaly_count": int(len(anomalies)),
        "most_significant_period": str(top_anomaly_period.date()),
        "most_significant_value": round(float(series[top_anomaly_period]), 2),
        "period_average": round(float(series.mean()), 2),
        "direction": "por encima" if z_scores[top_anomaly_period] > 0 else "por debajo",
    }


def trend_insight(df: pd.DataFrame, date_col: str, value_col: str) -> dict | None:
    if not date_col or not value_col:
        return None
    temp = df[[date_col, value_col]].copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp = temp.dropna(subset=[date_col, value_col])
    if len(temp) < 4:
        return None
    monthly = temp.set_index(date_col)[value_col].resample("ME").sum()
    if len(monthly) < 3:
        return None
    recent_avg = monthly.tail(3).mean()
    historical_avg = monthly.iloc[:-3].mean() if len(monthly) > 3 else monthly.mean()
    if historical_avg == 0 or pd.isna(historical_avg):
        return None
    change_pct = ((recent_avg - historical_avg) / abs(historical_avg)) * 100
    last_month_value = monthly.iloc[-1]
    last_month_vs_recent_avg = ((last_month_value - recent_avg) / abs(recent_avg)) * 100 if recent_avg else 0
    return {
        "recent_3month_avg": round(float(recent_avg), 2),
        "historical_avg": round(float(historical_avg), 2),
        "trend_change_pct": round(float(change_pct), 1),
        "is_real_trend": abs(last_month_vs_recent_avg) < 40,
        "direction": "creciendo" if change_pct > 5 else ("cayendo" if change_pct < -5 else "estable"),
    }


def actionable_delta_insight(df: pd.DataFrame, date_col: str, value_col: str, entity_col: str | None) -> dict | None:
    if not date_col or not value_col or not entity_col:
        return None
    temp = df[[date_col, value_col, entity_col]].copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp = temp.dropna(subset=[date_col, value_col, entity_col])
    if len(temp) < 4:
        return None
    monthly_by_entity = temp.set_index(date_col).groupby(
        [pd.Grouper(freq="ME"), entity_col]
    )[value_col].sum().unstack(fill_value=0)
    if len(monthly_by_entity) < 2:
        return None
    current = monthly_by_entity.iloc[-1]
    previous = monthly_by_entity.iloc[-2]
    delta = current - previous
    if delta.empty or delta.abs().sum() == 0:
        return None
    biggest_increase_entity = delta.idxmax()
    biggest_increase_value = delta.max()
    if biggest_increase_value <= 0:
        return None
    return {
        "entity_column": entity_col,
        "entity_with_biggest_increase": str(biggest_increase_entity),
        "increase_amount": round(float(biggest_increase_value), 2),
        "current_period_value": round(float(current[biggest_increase_entity]), 2),
        "previous_period_value": round(float(previous[biggest_increase_entity]), 2),
    }


# ─────────────────────────────────────────────────────────────
# 2b. MÉTRICAS — Cualitativas / No Financieras
# ─────────────────────────────────────────────────────────────

def qualitative_insights(df: pd.DataFrame) -> dict:
    """
    Analiza datos no financieros: frecuencias, distribuciones, patrones.
    Para encuestas, feedback, datos categóricos, etc.
    """
    insights = {"columns_analyzed": [], "missing_data_pct": 0}

    # Datos faltantes globales
    total_cells = df.shape[0] * df.shape[1]
    missing_cells = df.isnull().sum().sum() if total_cells > 0 else 0
    insights["missing_data_pct"] = round(missing_cells / total_cells * 100, 1) if total_cells > 0 else 0

    for col in df.columns:
        col_info = {"name": col, "dtype": str(df[col].dtype), "non_null": int(df[col].notna().sum())}
        n_unique = df[col].nunique(dropna=True)

        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
            col_info["type"] = "text"
            col_info["unique_values"] = n_unique
            if n_unique > 1 and n_unique <= 50:
                freq = df[col].value_counts()
                col_info["mode"] = str(freq.index[0])
                col_info["mode_pct"] = round(float(freq.iloc[0] / len(df) * 100), 1)
                col_info["top5"] = {str(k): int(v) for k, v in freq.head(5).items()}
            elif n_unique > 50:
                col_info["mode"] = str(df[col].mode().iloc[0]) if not df[col].mode().empty else "N/A"
                col_info["is_high_cardinality"] = True

        elif pd.api.types.is_numeric_dtype(df[col]):
            col_info["type"] = "numeric"
            col_info["mean"] = round(float(df[col].mean()), 2)
            col_info["median"] = round(float(df[col].median()), 2)
            col_info["min"] = round(float(df[col].min()), 2)
            col_info["max"] = round(float(df[col].max()), 2)
            col_info["std"] = round(float(df[col].std()), 2)

        elif pd.api.types.is_bool_dtype(df[col]):
            col_info["type"] = "boolean"
            col_info["true_pct"] = round(float(df[col].mean() * 100), 1)

        insights["columns_analyzed"].append(col_info)

    return insights


# ─────────────────────────────────────────────────────────────
# 3. ORQUESTADOR
# ─────────────────────────────────────────────────────────────

def generate_insights(df: pd.DataFrame, filters: dict = None, total_count: int = None) -> dict:
    """Punto de entrada único: recibe el DataFrame y devuelve métricas + prompt listo.
    Auto-detecta el tipo de datos (financiero/cuantitativo/cualitativo)."""
    data_type = _detect_data_type(df)

    if data_type in ("financial", "quantitative"):
        value_col = _detect_value_column(df)
        entity_col = _detect_entity_column(df, value_col)
        date_col = _detect_date_column(df)

        metrics = {
            "data_type": data_type,
            "detected_columns": {
                "value_column": value_col,
                "entity_column": entity_col,
                "date_column": date_col,
            },
            "filtered_count": len(df),
            "total_unfiltered": total_count or len(df),
            "has_filters": bool(filters and len(filters) > 0),
            "filters": filters or {},
            "concentration": concentration_insight(df, entity_col, value_col) if entity_col and value_col else None,
            "anomaly": anomaly_insight(df, date_col, value_col) if date_col and value_col else None,
            "trend": trend_insight(df, date_col, value_col) if date_col and value_col else None,
            "actionable_delta": actionable_delta_insight(df, date_col, value_col, entity_col) if date_col and value_col and entity_col else None,
        }
    else:
        # Cualitativo — encuestas, feedback, datos de texto
        metrics = {
            "data_type": data_type,
            "detected_columns": {"value_column": None, "entity_column": None, "date_column": None},
            "filtered_count": len(df),
            "total_unfiltered": total_count or len(df),
            "has_filters": bool(filters and len(filters) > 0),
            "filters": filters or {},
            "qualitative": qualitative_insights(df),
            "concentration": None, "anomaly": None, "trend": None, "actionable_delta": None,
        }

    return {
        "metrics": metrics,
        "prompt": build_interpretation_prompt(metrics, filters, total_count),
    }


# ─────────────────────────────────────────────────────────────
# 4. PROMPT PARA LA IA (solo interpreta, nunca calcula)
# ─────────────────────────────────────────────────────────────

def _format_metric_summary(metrics: dict) -> str:
    """Extrae los números clave de las métricas para que la IA los cite."""
    parts = []
    data_type = metrics.get("data_type", "financial")

    if data_type == "qualitative":
        qual = metrics.get("qualitative", {})
        parts.append(f"📊 Total de datos: {metrics.get('filtered_count', 0)} registros")
        for col in qual.get("columns_analyzed", [])[:5]:
            name = col["name"]
            if col.get("type") == "text":
                mode = col.get("mode", "N/A")
                pct = col.get("mode_pct", 0)
                unique = col.get("unique_values", 0)
                parts.append(f"📊 Columna '{name}': {unique} valores únicos · Moda: '{mode}' ({pct}%)")
            elif col.get("type") == "numeric":
                parts.append(f"📊 Columna '{name}': Prom={col.get('mean','-')} · Mediana={col.get('median','-')} · Min={col.get('min','-')} · Max={col.get('max','-')}")
        if qual.get("missing_data_pct", 0) > 0:
            parts.append(f"📊 Datos faltantes: {qual['missing_data_pct']}%")
    else:
        # Financial / Quantitative
        parts.append(f"📊 Registros analizados: {metrics.get('filtered_count', 0)}")
        c = metrics.get("concentration")
        if c:
            risk = "⚠️ ALTO RIESGO" if c.get("is_high_risk") else "✅ Moderado"
            parts.append(f"📊 Concentración: Top 3 ({', '.join(c.get('top3_entities',['?'])[:3])}) = {c.get('top3_share_of_value',0)}% del total · {risk}")
        a = metrics.get("anomaly")
        if a and a.get("has_anomalies"):
            parts.append(f"📊 Anomalías: {a['anomaly_count']} periodos atípicos · Mayor: {a['most_significant_period']} ({a['direction']}, ${a.get('most_significant_value',0):,.2f})")
        t = metrics.get("trend")
        if t:
            parts.append(f"📊 Tendencia: {t.get('trend_change_pct',0)}% ({t.get('direction','estable')}) · Últimos 3 meses vs histórico")
        d = metrics.get("actionable_delta")
        if d:
            parts.append(f"📊 Oportunidad: '{d.get('entity_with_biggest_increase','?')}' subió ${d.get('increase_amount',0):,.2f} vs periodo anterior")

    return "\n".join(parts)


def build_interpretation_prompt(metrics: dict, filters: dict = None, total_count: int = None) -> str:
    """Arma el prompt para la IA. Solo traduce, nunca calcula."""
    data_type = metrics.get("data_type", "financial")

    # Contexto de filtros
    filter_info = ""
    if filters and len(filters) > 0:
        filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items())
        filter_info = f"\nFILTROS ACTIVOS: {filter_desc}"
        if total_count and total_count > metrics.get('filtered_count', 0):
            filter_info += f"\n(de {total_count} registros totales → análisis sobre {metrics.get('filtered_count', 0)} registros filtrados)"
    else:
        filter_info = "\nANÁLISIS GENERAL — sin filtros aplicados (todos los datos)"

    # Resumen de métricas para que la IA las cite textualmente
    metric_summary = _format_metric_summary(metrics)

    if data_type == "qualitative":
        return f"""Eres un analista de datos senior. Analiza esta encuesta o dataset cualitativo.

MÉTRICAS CALCULADAS (DEBES citar estos números textualmente en cada insight):
{metric_summary}
{filter_info}

INSTRUCCIONES IMPORTANTES:
- Cada insight DEBE contener al menos un número de las métricas calculadas arriba
- No digas "la mayoría" sin decir el porcentaje exacto
- No digas "es alto/bajo" sin comparar con un número

ESTRUCTURA EXACTA DE RESPUESTA:

1. 🔍 [Hallazgo principal con número concreto]
2. 🔍 [Segundo hallazgo con número concreto]
3. 🔍 [Tercer hallazgo con número concreto]

al analizar los insights la conclusión es que [desarrolla una conclusión detallada de mínimo 300 palabras explicando el panorama general, conectando los hallazgos entre sí, identificando patrones subyacentes y explicando por qué estos números importan para el negocio. Habla de tendencias, riesgos y oportunidades de forma coherente, no como lista]

como recomendación [desarrolla una recomendación detallada de mínimo 300 palabras con acciones concretas, priorizadas por impacto, con plazos sugeridos y métricas para medir el éxito. Explica QUÉ hacer, POR QUÉ funcionará, CÓMO implementarlo y CÓMO medir resultados. Incluye al menos 3 acciones específicas con impacto cuantificado cuando sea posible]

FIN DEL ANÁLISIS"""
    else:
        return f"""Eres un analista de datos senior explicándole resultados a un dueño de PYME.

MÉTRICAS CALCULADAS (DEBES citar estos números textualmente en cada insight):
{metric_summary}
{filter_info}

INSTRUCCIONES IMPORTANTES:
- Cada insight DEBE contener al menos un número de las métricas calculadas arriba
- No digas "alto" sin decir el porcentaje. No digas "creció" sin decir cuánto
- Usa los filtros activos para contextualizar

ESTRUCTURA EXACTA DE RESPUESTA (NO INCLUYAS TÍTULOS NI INTRODUCCIONES):

1. 🔍 [Insight 1 con número concreto en lenguaje de negocio]
2. 🔍 [Insight 2 con número concreto en lenguaje de negocio]
3. 🔍 [Insight 3 con número concreto en lenguaje de negocio]

al analizar los insights la conclusión es que [desarrolla una conclusión detallada de mínimo 400 palabras explicando el panorama general del negocio, conectando los 3 hallazgos entre sí, identificando patrones subyacentes, riesgos no obvios y oportunidades estratégicas. Explica por qué estos números importan para el dueño de la PYME, no solo qué dicen sino qué IMPLICAN. Usa analogías de negocio si ayuda. Debe sonar como un consultor senior explicando el "qué significa esto para tu empresa"]

como recomendación [desarrolla una recomendación detallada de mínimo 300 palabras con:
- 3 acciones concretas priorizadas por impacto
- Para cada acción: QUÉ hacer, POR QUÉ funcionará (basado en los números), CÓMO implementarlo paso a paso
- Incluye plazos sugeridos (corto/mediano/largo plazo)
- Incluye cómo medir si la acción está funcionando (KPI de seguimiento)
- Cuantifica el impacto esperado cuando sea posible
Debe sonar como un consultor entregando un plan de acción, no como consejo genérico]

FIN DEL ANÁLISIS"""


# ─────────────────────────────────────────────────────────────
# Ejemplo de uso
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pass
