from datetime import datetime
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Coletor de Preços de Supermercados", version="1.0.0")

class Produto(BaseModel):
    id: Any = None
    produto: str
    marca: str | None = None
    ean: str | None = None
    unidade: str | None = None
    quantidade: float | None = 1

class PedidoColeta(BaseModel):
    cidade: str | None = None
    cep: str | None = None
    lojas: dict[str, Any] = {}
    produtos: list[Produto]

@app.get("/")
def inicio():
    return {"sistema": "Coletor de preços", "status": "online"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/coletar")
def coletar(pedido: PedidoColeta):
    resultados = []

    for produto in pedido.produtos:
        lojas = [
            ("Atacadão", pedido.lojas.get("atacadao", "")),
            ("Pão de Açúcar", pedido.lojas.get("pao_de_acucar", "")),
            ("Super Muffato", pedido.lojas.get("super_muffato", ""))
        ]

        for supermercado, loja in lojas:
            resultados.append({
                "produto_id": produto.id,
                "produto": produto.produto,
                "supermercado": supermercado,
                "loja": loja,
                "preco_unitario": None,
                "preco_atacado": None,
                "quantidade_minima": None,
                "disponivel": False,
                "url": "",
                "status": "PENDENTE",
                "observacao": "Adaptador real deste supermercado ainda precisa ser configurado."
            })

    return {
        "data_hora": datetime.now().isoformat(),
        "cidade": pedido.cidade,
        "precos": resultados
    }
