from __future__ import annotations
import time, re, urllib.parse
from typing import Dict, List, Optional

import pandas as pd
import requests

BASE = "https://www.saojoaofarmacias.com.br"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PAUSA = 0.5

# ------------ utils ------------
def _limpa(v) -> str:
    if v is None: return ""
    s = str(v).strip()
    return "" if s.lower() in {"nan", "none"} else s

def _preco_br(v) -> str:
    try:
        n = float(v)
        return "R$ " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "Produto não encontrado"

def _breadcrumb(prod: dict) -> str:
    tree = prod.get("categoryTree")
    if isinstance(tree, list) and tree:
        nomes = [n.get("name") for n in tree if isinstance(n, dict) and n.get("name")]
        nomes = [n for n in nomes if n.strip().lower() != "início"]
        if nomes: return " > ".join(nomes)
    cats = prod.get("categories") or []
    if cats:
        caminho = max(cats, key=len).strip("/")
        partes = [p.replace("-", " ").strip() for p in caminho.split("/") if p.lower() != "início"]
        if partes: return " > ".join(partes)
    return "—"

def _price_from_product(prod: dict) -> float:
    try:
        return float(prod["items"][0]["sellers"][0]["commertialOffer"].get("Price") or 0)
    except Exception: return 0.0

def _link_from_product(prod: dict) -> str:
    link_text = prod.get("linkText") or ""
    if not link_text:
        name = (prod.get("productName") or "").lower().strip().replace(" ", "-")
        link_text = urllib.parse.quote(name)
    return f"{BASE}/{link_text}/p"

def _best_match(lista: List[dict], termo_ref: str) -> Optional[dict]:
    if not lista: return None
    ref = (termo_ref or "").lower()
    tokens = [t for t in re.split(r"\s+", ref) if t]
    def score(p): return (-sum(1 for t in tokens if t in (p.get("productName","") or "").lower()), len(p.get("productName","")))
    return sorted(lista, key=score)[0]

# ------------ consultas ------------
def _search_ean(ean: str) -> List[dict]:
    url = f"{BASE}/api/catalog_system/pub/products/search/?fq=alternateIds_Ean:{urllib.parse.quote(ean)}"
    return requests.get(url, headers=HEADERS, timeout=25).json()

def _search_term(term: str, _from=0, _to=19) -> List[dict]:
    url = f"{BASE}/api/catalog_system/pub/products/search/?ft={urllib.parse.quote(term)}&_from={_from}&_to={_to}"
    return requests.get(url, headers=HEADERS, timeout=25).json()

def _term_simplify(term: str) -> str:
    t = term.lower()
    t = re.sub(r"\b\d+\s?(mg|g|mcg|µg|ml|kg|l)\b", " ", t)
    t = re.sub(r"\b\d+\s?(comprimidos?|cp|caps?|tabletes?)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip() or term

def _consultar(termo: str, nome_ref: str="") -> Dict[str,str]:
    produtos = []
    t = termo.strip()

    # tenta termo primeiro
    try: produtos = _search_term(t)
    except: produtos = []

    # fallback: EAN
    if not produtos and t.isdigit() and len(t) >= 8:
        try: produtos = _search_ean(t)
        except: produtos = []

    if not produtos:
        t2 = _term_simplify(t)
        if t2 != t:
            try: produtos = _search_term(t2)
            except: produtos = []

    if not produtos: return {"Preco":"Produto não encontrado","Link":"","Classificacao":"—","Observacao":"Sem resultados"}

    prod = _best_match(produtos, nome_ref or t)
    if not prod: return {"Preco":"Produto não encontrado","Link":"","Classificacao":"—","Observacao":"Sem match"}

    return {"Preco": _preco_br(_price_from_product(prod)), "Link": _link_from_product(prod), "Classificacao": _breadcrumb(prod), "Observacao":"—"}

# ------------ público ------------
def buscar_item(q: str) -> list[dict]:
    dados = _consultar(q, q)
    return [{
        "EAN": q if q.isdigit() else "",
        "NOME": q,  # garante nome preenchido
        "Preco": dados.get("Preco","Produto não encontrado"),
        "Link": dados.get("Link",""),
        "Classificacao": dados.get("Classificacao","—"),
        "Observacao": dados.get("Observacao","—"),
    }]

def processar_dataframe(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df.columns = [c.upper().strip() for c in df.columns]

    # aceita NOME ou EAN; se só tiver 1 coluna, assume NOME
    if ("EAN" not in df.columns) and ("NOME" not in df.columns):
        if df.shape[1] == 1:
            df.columns = ["NOME"]
        else:
            raise ValueError("A planilha precisa ter ao menos a coluna NOME ou EAN.")

    saida = []
    for _, row in df.iterrows():
        ean = _limpa(row.get("EAN", ""))
        nome = _limpa(row.get("NOME", ""))
        termo = ean or nome

        if not termo:
            saida.append({
                "EAN": ean, "NOME": nome,
                "Preco": "Produto não encontrado", "Link": "",
                "Classificacao": "—", "Observacao": "Linha vazia"
            })
            continue

        # 1) tenta pelo EAN se houver
        dados = {}
        if ean:
            try:
                dados = _consultar(ean, nome or ean)
            except Exception as e:
                dados = {"Preco": "Produto não encontrado", "Link": "", "Classificacao": "—", "Observacao": f"Erro: {e}"}

        # 2) fallback: se falhou com EAN, tenta pelo NOME
        if (not dados) or (dados.get("Preco") == "Produto não encontrado"):
            if nome:
                try:
                    dados = _consultar(nome, nome)
                except Exception as e:
                    dados = {"Preco": "Produto não encontrado", "Link": "", "Classificacao": "—", "Observacao": f"Erro: {e}"}
            else:
                # se não tinha nome, mantém o resultado anterior (provavelmente "não encontrado")
                if not dados:
                    dados = {"Preco": "Produto não encontrado", "Link": "", "Classificacao": "—", "Observacao": "Sem resultados"}

        saida.append({"EAN": ean, "NOME": nome or termo, **dados})
        time.sleep(PAUSA)

    return pd.DataFrame(saida, columns=["EAN", "NOME", "Preco", "Link", "Classificacao", "Observacao"])
