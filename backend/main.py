from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine
from rag.router import router as documents_router


app = FastAPI(title="RAG Chatbot API")
app.include_router(documents_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def database_health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error

    return {"status": "ok"}
