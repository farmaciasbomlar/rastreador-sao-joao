from __future__ import annotations

import io
import json
import os
import tempfile
from typing import Any, Callable

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
)

# === importe seu módulo exatamente como ele está ===
import rastrear_saojoao as _rsj  # tem buscar_item, _consultar, _search_term, _search_ean, processar_dataframe

app = FastAPI(title="Rastreador São João API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ajuste em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# guardamos o último XLSX gerado aqui
_LAST_XLSX_PATH: str | None = None


# --------------------------
# Utilitários
# --------------------------
def _resolver_funcao(
    modulo: Any,
    candidatos: list[str],
    papel: str,
    heuristica_substrings: list[str] | None = None,
) -> Callable[..., Any]:
    # 1) tentativas por nome exato (case-insensitive)
    tried = []
    for nome in candidatos:
        tried.append(nome)
        for attr_name, obj in vars(modulo).items():
            if not callable(obj):
                continue
            if attr_name.lower() == nome.lower():
                return obj

    # 2) heurística por substrings
    if heuristica_substrings:
        for attr_name, obj in vars(modulo).items():
            if not callable(obj):
                continue
            low = attr_name.lower()
            if any(sub in low for sub in heuristica_substrings):
                return obj

    raise ImportError(
        f"Não encontrei função para {papel} em rastrear_saojoao.py. "
        f"Tentei: {', '.join(tried)}"
    )


def _is_list_of_dicts(x: Any) -> bool:
    return isinstance(x, list) and (len(x) == 0 or isinstance(x[0], dict))


def _normalize_result(obj: Any) -> list[dict]:
    if _is_list_of_dicts(obj):
        return obj
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, (list, tuple)):
        for item in obj:
            if _is_list_of_dicts(item):
                return item
            if isinstance(item, dict):
                return [item]
            if isinstance(item, pd.DataFrame):
                return item.to_dict(orient="records")
    raise HTTPException(
        status_code=500,
        detail="A função de busca deve retornar dados convertíveis em lista de dicionários.",
    )


def _criar_xlsx(resultados: list[dict]) -> str:
    df = pd.DataFrame(resultados) if resultados else pd.DataFrame([{}])

    if {"Link", "Preco"}.issubset(df.columns):
        def _mk(row: pd.Series):
            link = str(row.get("Link", ""))
            preco = str(row.get("Preco", ""))
            return f'=HYPERLINK("{link}","{preco}")' if link else preco
        df["Preco"] = df.apply(_mk, axis=1)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = tmp.name
    tmp.close()

    with pd.ExcelWriter(tmp_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Resultado")

    return tmp_path


def _responder(resultados: list[dict], request: Request):
    global _LAST_XLSX_PATH
    _LAST_XLSX_PATH = _criar_xlsx(resultados)

    wants_html = "text/html" in (request.headers.get("accept") or "").lower()
    download_url = "/baixar_resultado"

    if wants_html:
        pretty = json.dumps(resultados, ensure_ascii=False, indent=2)
        html = f"""
        <h3>Resultado da busca</h3>
        <pre>{pretty}</pre>
        <form action="{download_url}" method="get">
            <button type="submit" style="padding:10px; background:green; color:white; border:none; border-radius:5px; cursor:pointer;">
                📄 Baixar Planilha
            </button>
        </form>
        """
        return HTMLResponse(html)

    return JSONResponse({"resultados": resultados, "download_url": download_url})


# --------------------------
# Resolver funções do módulo
# --------------------------
_buscar_impl = _resolver_funcao(
    _rsj,
    candidatos=["buscar_item", "_consultar", "_search_term", "_search_ean"],
    papel="BUSCA (por EAN/NOME)",
    heuristica_substrings=["busc", "consult", "search", "ean", "term"],
)

_processar_df_impl = _resolver_funcao(
    _rsj,
    candidatos=["processar_dataframe"],
    papel="PROCESSAMENTO DA PLANILHA",
    heuristica_substrings=["process", "planilh", "datafram", "excel"],
)


# --------------------------
# Rotas
# --------------------------
@app.get("/")
def raiz():
    return {"status": "ok", "app": "Rastreador São João API"}


@app.post("/buscar")
async def buscar(request: Request, q: str = Query(..., description="Nome ou EAN")):
    try:
        bruto = _buscar_impl(q)
        resultados = _normalize_result(bruto)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na busca: {e!s}")
    return _responder(resultados, request)


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .xlsx")

    data = await file.read()
    try:
        df_in = pd.read_excel(io.BytesIO(data))
        bruto = _processar_df_impl(df_in)
        resultados = _normalize_result(bruto)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar planilha: {e!s}")

    return _responder(resultados, request)


@app.get("/baixar_resultado")
def baixar_resultado():
    global _LAST_XLSX_PATH
    if not _LAST_XLSX_PATH or not os.path.exists(_LAST_XLSX_PATH):
        raise HTTPException(status_code=404, detail="Nenhuma planilha gerada ainda.")

    return FileResponse(
        path=_LAST_XLSX_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="resultado.xlsx",
    )
