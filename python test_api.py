import os
import io
import json
import time
import requests

# ============================
# Config
# ============================
BASE_URL = os.getenv("SAOJOAO_API_URL", "http://127.0.0.1:8000")
ARQ_UPLOAD = os.getenv("ARQ_UPLOAD", "exemplo_upload.xlsx")  # mude se quiser
ARQ_SAIDA  = os.getenv("ARQ_SAIDA",  "resultado_teste.xlsx")

# ============================
# Helpers
# ============================
def _mk_planilha_exemplo(path: str):
    """Cria uma planilha mínima se não existir."""
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Instale pandas para gerar planilha de exemplo: pip install pandas openpyxl")

    df = pd.DataFrame({
        "EAN":  ["7891058014684", "7896422503184", ""],
        "NOME": ["Dipirona 500mg", "Paracetamol 750mg", "Omeprazol 20mg"],
    })
    df.to_excel(path, index=False)
    return path

def _pretty(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)

# ============================
# Tests
# ============================
def test_buscar(q: str):
    url = f"{BASE_URL}/buscar"
    print(f"\n[POST] {url}?q={q}")
    r = requests.post(url, params={"q": q}, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    print("→ resposta JSON:")
    print(_pretty(data))
    return data.get("download_url", "/baixar_resultado")

def test_upload(filepath: str):
    url = f"{BASE_URL}/upload"
    print(f"\n[POST] {url}  (arquivo: {filepath})")
    with open(filepath, "rb") as f:
        files = {"file": (os.path.basename(filepath), f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(url, files=files, headers={"Accept": "application/json"})
    r.raise_for_status()
    data = r.json()
    print("→ resposta JSON:")
    print(_pretty(data))
    return data.get("download_url", "/baixar_resultado")

def test_baixar(download_url: str, saida: str):
    url = download_url if download_url.startswith("http") else f"{BASE_URL}{download_url}"
    print(f"\n[GET] {url}")
    r = requests.get(url, stream=True)
    r.raise_for_status()
    with open(saida, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
    print(f"→ arquivo salvo: {saida} ({len(open(saida,'rb').read())} bytes)")
    return saida

# ============================
# Run all
# ============================
if __name__ == "__main__":
    print("=== Rastreador São João API – teste automático ===")
    print(f"Base URL: {BASE_URL}")

    # 1) /buscar
    dl1 = test_buscar("dipirona 500mg")

    # 2) /upload (usa a planilha existente ou cria uma)
    if not os.path.exists(ARQ_UPLOAD):
        print(f"\n⚠️  {ARQ_UPLOAD} não encontrado. criando planilha de exemplo…")
        _mk_planilha_exemplo(ARQ_UPLOAD)
    dl2 = test_upload(ARQ_UPLOAD)

    # 3) /baixar_resultado (primeiro do /upload; se falhar, o do /buscar)
    try:
        test_baixar(dl2, ARQ_SAIDA)
    except Exception as e:
        print(f"Falha ao baixar resultado do upload ({e}). Tentando o da busca…")
        test_baixar(dl1, ARQ_SAIDA)

    print("\n✅ Teste concluído.")
