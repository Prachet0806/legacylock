from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import SessionLocal, Vault, VaultMessage, init_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.2.0.2:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


class MessageRequest(BaseModel):
    label: str
    encrypted_content: str


@app.post("/vault/messages")
def save_message(data: MessageRequest):
    db = SessionLocal()

    vault = db.query(Vault).first()
    if not vault:
        vault = Vault()
        db.add(vault)
        db.commit()
        db.refresh(vault)

    message = VaultMessage(
        vault_id=vault.id,
        label=data.label,
        encrypted_content=data.encrypted_content,
    )
    db.add(message)
    db.commit()
    db.close()

    return {"message": "Message saved"}


@app.get("/vault/messages")
def list_messages():
    db = SessionLocal()
    messages = db.query(VaultMessage).all()
    db.close()

    return [
        {
            "id": m.id,
            "label": m.label,
            "created_at": m.created_at,
        }
        for m in messages
    ]


@app.get("/vault/messages/{message_id}")
def load_message(message_id: int):
    db = SessionLocal()
    message = db.query(VaultMessage).filter_by(id=message_id).first()
    db.close()

    if not message:
        return {"error": "Not found"}

    return {
        "id": message.id,
        "label": message.label,
        "encrypted_content": message.encrypted_content
    }