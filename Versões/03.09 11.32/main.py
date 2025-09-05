from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
from rastrear_saojoao import processar_dataframe

app = FastAPI(title=Rastreador São João API)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=True,
    allow_methods=[],
    allow_headers=[],
)


@app.post(buscar)
async def buscar_item(q str = Query(..., description=Nome ou EAN))
    try
        # Cria um dataframe apenas com o resultado da busca
        df = pd.DataFrame([{
            EAN ,
            NOME q,
            Preco R$ 16,31,   # aqui você já coloca o que raspou
            Link httpswww.saojoaofarmacias.com.brexemplo,
            Classificacao Medicamentos  Analgésicos  Dor de Cabeça,
            Observacao _
        }])

        # Salva esse dataframe em memória
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine=openpyxl) as writer
            df.to_excel(writer, index=False, sheet_name=Resultado)
        buf.seek(0)

        # Retorna o mesmo comportamento do upload → link Download file
        return StreamingResponse(
            buf,
            media_type=applicationvnd.openxmlformats-officedocument.spreadsheetml.sheet,
            headers={Content-Disposition fattachment; filename=resultado_busca.xlsx},
        )

    except Exception as e
        raise HTTPException(status_code=500, detail=fErro ao buscar {e})


@app.post(upload)
async def upload_planilha(file UploadFile = File(...))
    try
        df_in = pd.read_excel(file.file)
        df_out = processar_dataframe(df_in)

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine=openpyxl) as writer
            df_out.to_excel(writer, index=False, sheet_name=Resultado)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type=applicationvnd.openxmlformats-officedocument.spreadsheetml.sheet,
            headers={Content-Disposition attachment; filename=resultado_upload.xlsx},
        )

    except Exception as e
        raise HTTPException(status_code=500, detail=fErro ao processar upload {e})
