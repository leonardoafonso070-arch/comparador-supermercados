from datetime import datetime
from typing import Any
import urllib.parse
import urllib.request
import json

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Coletor de Preços de Supermercados",
    version="2.0.0"
)


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
    return {
        "sistema": "Coletor de preços",
        "status": "online",
        "versao": "2.0.0"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


def buscar_atacadao(produto: Produto, cep: str | None):
    termo = produto.ean if produto.ean else produto.produto

    if produto.marca:
        termo_nome = f"{produto.produto} {produto.marca}"
    else:
        termo_nome = produto.produto

    # Primeiro tenta pelo EAN.
    # Se não encontrar, tenta pelo nome + marca.
    termos = []

    if produto.ean:
        termos.append(produto.ean)

    termos.append(termo_nome)

    for busca in termos:
        try:
            termo_codificado = urllib.parse.quote(busca)

            url_api = (
                "https://www.atacadao.com.br/"
                "api/catalog_system/pub/products/search/"
                + termo_codificado
            )

            requisicao = urllib.request.Request(
                url_api,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json"
                }
            )

            with urllib.request.urlopen(
                requisicao,
                timeout=20
            ) as resposta:
                dados = json.loads(
                    resposta.read().decode("utf-8")
                )

            if not dados:
                continue

            produto_encontrado = dados[0]

            nome = produto_encontrado.get(
                "productName",
                produto.produto
            )

            link = produto_encontrado.get("link", "")

            itens = produto_encontrado.get("items", [])

            melhor_preco = None
            disponivel = False

            for item in itens:
                sellers = item.get("sellers", [])

                for seller in sellers:
                    oferta = seller.get(
                        "commertialOffer",
                        {}
                    )

                    quantidade = oferta.get(
                        "AvailableQuantity",
                        0
                    )

                    preco = oferta.get("Price")

                    if (
                        quantidade
                        and quantidade > 0
                        and preco
                        and preco > 0
                    ):
                        disponivel = True

                        if (
                            melhor_preco is None
                            or preco < melhor_preco
                        ):
                            melhor_preco = preco

            if melhor_preco is not None:
                return {
                    "produto_id": produto.id,
                    "produto": nome,
                    "supermercado": "Atacadão",
                    "preco_unitario": melhor_preco,
                    "preco_atacado": None,
                    "quantidade_minima": None,
                    "disponivel": disponivel,
                    "url": link,
                    "status": "OK",
                    "observacao": (
                        "Preço obtido do catálogo online "
                        "do Atacadão."
                    )
                }

        except Exception as erro:
            ultimo_erro = str(erro)

    return {
        "produto_id": produto.id,
        "produto": produto.produto,
        "supermercado": "Atacadão",
        "preco_unitario": None,
        "preco_atacado": None,
        "quantidade_minima": None,
        "disponivel": False,
        "url": "",
        "status": "NAO_ENCONTRADO",
        "observacao": (
            "Não foi possível obter preço do Atacadão."
        )
    }


@app.post("/coletar")
def coletar(pedido: PedidoColeta):
    resultados = []

    for produto in pedido.produtos:

        # ATACADÃO
        resultado_atacadao = buscar_atacadao(
            produto,
            pedido.cep
        )

        resultado_atacadao["loja"] = pedido.lojas.get(
            "atacadao",
            ""
        )

        resultados.append(resultado_atacadao)

        # PÃO DE AÇÚCAR
        resultados.append({
            "produto_id": produto.id,
            "produto": produto.produto,
            "supermercado": "Pão de Açúcar",
            "loja": pedido.lojas.get(
                "pao_de_acucar",
                ""
            ),
            "preco_unitario": None,
            "preco_atacado": None,
            "quantidade_minima": None,
            "disponivel": False,
            "url": "",
            "status": "PENDENTE",
            "observacao": (
                "Coletor do Pão de Açúcar "
                "ainda será configurado."
            )
        })

        # SUPER MUFFATO
        resultados.append({
            "produto_id": produto.id,
            "produto": produto.produto,
            "supermercado": "Super Muffato",
            "loja": pedido.lojas.get(
                "super_muffato",
                ""
            ),
            "preco_unitario": None,
            "preco_atacado": None,
            "quantidade_minima": None,
            "disponivel": False,
            "url": "",
            "status": "PENDENTE",
            "observacao": (
                "Coletor do Super Muffato "
                "ainda será configurado."
            )
        })

    return {
        "data_hora": datetime.now().isoformat(),
        "cidade": pedido.cidade,
        "cep": pedido.cep,
        "precos": resultados
    }
