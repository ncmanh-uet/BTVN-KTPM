from fastapi import FastAPI, Query

app = FastAPI(title="Order Service")
ORDERS = [
    {"id": 101, "user_id": 1, "product": "Bàn phím", "total": 750000},
    {"id": 102, "user_id": 1, "product": "Chuột", "total": 250000},
    {"id": 103, "user_id": 2, "product": "Màn hình", "total": 3500000},
]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/orders")
def orders(user_id: int = Query(gt=0)):
    return [order for order in ORDERS if order["user_id"] == user_id]
