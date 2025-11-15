# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from pypdf import PdfReader
import sqlite3, json, os, aiofiles, asyncio, httpx

app = FastAPI(title="MathOlympiad PDF -> Módulo Generator")

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

def init_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        subject TEXT,
        content JSON,
        exercises JSON
    )
    """)
    conn.commit()
    conn.close()

init_db()

async def call_openai(prompt: str, max_tokens: int = 800):
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",  # adapte se quiser outro modelo
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    # salvar temporariamente
    tmp_path = f"tmp_{file.filename}"
    async with aiofiles.open(tmp_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # extrair texto do pdf
    try:
        reader = PdfReader(tmp_path)
        text = ""
        for p in reader.pages:
            txt = p.extract_text() or ""
            text += txt + "\n"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro lendo PDF: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass

    # gerar título e estrutura com a IA
    prompt_title = (
        "Você é um professor experiente de Olimpíadas de Matemática. "
        "Recebi o texto abaixo (trecho de PDF) sobre um tópico. "
        "Resuma em um título de módulo curto (ex: 'Área de triângulos'), "
        "indique a matéria (ex: Geometria / Álgebra), e gere um índice com 4 aulas curtas."
        "Retorne apenas JSON com campos: title, subject, lessons (lista de strings)."
        f"\n\nTEXTO DO PDF:\n{text[:3000]}"
    )

    try:
        resp = await call_openai(prompt_title, max_tokens=500)
        # tentar interpretar JSON retornado
        parsed = json.loads(resp)
    except Exception:
        # se não foi JSON, tenta pedir à IA em outro prompt (fallback)
        resp2 = await call_openai(
            "Por favor retorne exatamente um JSON com campos title, subject, lessons (lista). Texto: " + resp,
            max_tokens=300
        )
        parsed = json.loads(resp2)

    title = parsed.get("title", file.filename)
    subject = parsed.get("subject", "Matemática")
    lessons = parsed.get("lessons", [])

    # gerar exercícios (25) com passo a passo
    prompt_ex = (
        "Com base no módulo abaixo gere 25 exercícios graduados (fácil -> difícil -> olímpico) "
        "sobre o tema. Para cada exercício retorne um objeto com: question, solution_step_by_step.\n\n"
        f"MODULE TITLE: {title}\nLESSONS: {lessons[:3]}"
    )
    ex_resp = await call_openai(prompt_ex, max_tokens=2500)
    # esperar que a IA retorne JSON: list of {question, solution}
    try:
        exercises = json.loads(ex_resp)
    except Exception:
        # se não for JSON direto, pede novamente para formatar como JSON
        ex_resp2 = await call_openai("Retorne apenas JSON - uma lista de objetos {\"question\":...,\"solution\":...}: " + ex_resp, max_tokens=2500)
        exercises = json.loads(ex_resp2)

    # salvar no banco
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO modules (title, subject, content, exercises) VALUES (?, ?, ?, ?)",
        (title, subject, json.dumps({"lessons": lessons}), json.dumps(exercises))
    )
    conn.commit()
    module_id = c.lastrowid
    conn.close()

    return {"status": "ok", "module_id": module_id, "title": title, "subject": subject}
Replace placeholder main.py with FastAPI upload + OpenAI logic
