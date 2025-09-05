# main.py
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
import rastrear_saojoao as _rsj  # tem _consultar, _search_term, _search_ean, processar_dataframe

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
    """
    Procura uma função no módulo por nome exato primeiro;
    se não encontrar, usa heurística por substrings no nome (case-insensitive).
    """
    # 1) tentativas por nome exato (case-insensitive)
    tried = []
    for nome in candidatos:
        tried.append(nome)
        for attr_name, obj in vars(modulo).items():
            if not callable(obj):
                continue
            if attr_name.lower() == nome.lower():
                # print(f"[resolver] {papel}: usando função '{attr_name}' (match exato)")
                return obj

    # 2) heurística por substrings
    if heuristica_substrings:
        for attr_name, obj in vars(modulo).items():
            if not callable(obj):
                continue
            low = attr_name.lower()
            if any(sub in low for sub in heuristica_substrings):
                # print(f"[resolver] {papel}: usando função '{attr_name}' (match por heurística)")
                return obj

    # 3) falhou
    extra = f" | Heurística: {heuristica_substrings}" if heuristica_substrings else ""
    raise ImportError(
        f"Não encontrei função para {papel} em rastrear_saojoao.py. "
        f"Tentei: {', '.join(tried)}{extra}. "
        "Você pode ajustar os nomes aqui ou criar um wrapper no seu módulo."
    )


def _is_list_of_dicts(x: Any) -> bool:
    return isinstance(x, list) and (len(x) == 0 or isinstance(x[0], dict))


def _normalize_result(obj: Any) -> list[dict]:
    """
    Aceita: list[dict], dict, pandas.DataFrame, (list|dict|DataFrame, ...), etc.
    Converte sempre para list[dict].
    """
    # list de dicts
    if _is_list_of_dicts(obj):
        return obj

    # dict único
    if isinstance(obj, dict):
        return [obj]

    # DataFrame
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")

    # tuplas/listas compostas
    if isinstance(obj, (list, tuple)):
        # varre para achar algo útil
        for item in obj:
            if _is_list_of_dicts(item):
                return item
            if isinstance(item, dict):
                return [item]
            if isinstance(item, pd.DataFrame):
                return item.to_dict(orient="records")

    raise HTTPException(
        status_code=500,
        detail="A função de busca deve retornar dados que possam ser convertidos em lista de dicionários (list[dict]).",
    )


def _criar_xlsx(resultados: list[dict]) -> str:
    """
    Gera XLSX em arquivo temporário e retorna o caminho.
    Se houver colunas 'Link' e 'Preco', cria hiperlink no Excel (coluna Preco).
    """
    df = pd.DataFrame(resultados) if resultados else pd.DataFrame([{}])

    # hiperlink: se houver as colunas Link e Preco
    if {"Link", "Preco"}.issubset(df.columns):
        def _mk(cell):
            link = str(cell.get("Link", "")) if isinstance(cell, dict) else ""
            preco = str(cell.get("Preco", "")) if isinstance(cell, dict) else ""
            # quando aplicamos linha-a-linha, 'cell' representa a linha toda (Series)
            if isinstance(cell, pd.Series):
                link = str(cell.get("Link", ""))
                preco = str(cell.get("Preco", ""))
            if link:
                return f'=HYPERLINK("{link}","{preco}")'
            return preco

        df["Preco"] = df.apply(_mk, axis=1)

    # grava em temp
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = tmp.name
    tmp.close()

    with pd.ExcelWriter(tmp_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Resultado")

    return tmp_path


def _responder(resultados: list[dict], request: Request) -> JSONResponse | HTMLResponse:
    """
    Content negotiation:
    - Se o cliente pedir text/html, devolvemos uma página simples com o <pre> e o botão/link para baixar.
    - Caso contrário (application/json), devolvemos JSON incluindo 'download_url'.
    """
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

    # JSON (default)
    payload = {
        "resultados": resultados,
        "download_url": download_url,
    }
    return JSONResponse(payload)


# --------------------------
# Resolver as funções reais no seu módulo
# --------------------------
# BUSCA por nome/EAN – tenta achar _consultar / _search_* ou nomes "buscar"
_buscar_impl = _resolver_funcao(
    _rsj,
    candidatos=[
        # nomes "comuns"
        "buscar_item",
        "buscar",
        "buscar_por_nome_ean",
        "buscar_por_nome",
        "rastrear_item",
        "rastrear",
        # nomes que você realmente tem:
        "_consultar",
        "_search_term",
        "_search_ean",
    ],
    papel="BUSCA (por EAN/NOME)",
    heuristica_substrings=["busc", "rastre", "consult", "search", "ean", "term"],
)

# PROCESSAMENTO da planilha
_processar_df_impl = _resolver_funcao(
    _rsj,
    candidatos=[
        "processar_dataframe",
        "processar_df",
        "tratar_planilha",
        "processar_planilha",
    ],
    papel="PROCESSAMENTO DA PLANILHA",
    heuristica_substrings=["process", "planilh", "datafram", "tratar", "excel"],
)


# --------------------------
# Rotas
# --------------------------
@app.get("/", tags=["default"])
def raiz():
    return {"status": "ok", "app": "Rastreador São João API"}


@app.post("/buscar", tags=["default"])
async def buscar(
    request: Request,
    q: str = Query(..., description="Nome ou EAN"),
):
    """
    Busca por nome/EAN usando a função encontrada no módulo.
    Retorna HTML (se o Accept pedir) ou JSON com 'resultados' e 'download_url'.
    """
    try:
        bruto = _buscar_impl(q)
        resultados = _normalize_result(bruto)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na busca: {e!s}")

    return _responder(resultados, request)


@app.post("/upload", tags=["default"])
async def upload(
    request: Request,
    file: UploadFile = File(..., description="Arquivo XLSX no modelo da planilha"),
):
    """
    Processa a planilha enviada (usa 'processar_dataframe' do seu módulo).
    Retorna HTML (se o Accept pedir) ou JSON com 'resultados' e 'download_url'.
    """
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


@app.get("/baixar_resultado", tags=["default"])
def baixar_resultado():
    """
    Baixa o último XLSX gerado por /buscar ou /upload.
    Swagger mostrará o botão 'Download file' aqui.
    """
    global _LAST_XLSX_PATH
    if not _LAST_XLSX_PATH or not os.path.exists(_LAST_XLSX_PATH):
        raise HTTPException(status_code=404, detail="Nenhuma planilha gerada ainda.")

    filename = "resultado.xlsx"
    return FileResponse(
        path=_LAST_XLSX_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )
