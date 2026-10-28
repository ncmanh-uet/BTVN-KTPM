from fastapi import FastAPI, HTTPException

app = FastAPI(title="User Service")
USERS = {
    1: {"id": 1, "name": "Nguyễn An", "email": "an@example.com"},
    2: {"id": 2, "name": "Trần Bình", "email": "binh@example.com"},
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users/{user_id}")
def user(user_id: int):
    if user_id not in USERS:
        raise HTTPException(404, "User not found")
    return USERS[user_id]
