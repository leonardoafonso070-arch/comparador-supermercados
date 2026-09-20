from datetime import datetime
from typing import Any
import json
import urllib.parse
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Coletor de Preços de Supermercados",
    version="2.1.0"
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


# Atacadão - Loja São José do Rio Preto América
ATACADAO_API = "https://www.atacadao.com.br/api/graphql"
ATACADAO_SELLER = "atacadaobr949"
ATACADAO_REGION_ID = "v2.EB9CBB9497C9DD495FB7A98C30D4069D"
ATACADAO_SALES_CHANNEL = "1"


@app.get("/")
def inicio():
    return {
        "sistema": "Coletor de preços",
        "status": "online",
        "versao": "2.1.0"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


def consultar_atacadao(termo: str):
    canal = json.dumps(
        {
            "salesChannel": ATACADAO_SALES_CHANNEL,
            "regionId": ATACADAO_REGION_ID,
            "seller": ATACADAO_SELLER
        },
        separators=(",", ":")
    )

    variables = {
        "term": termo,
        "selectedFacets": [
            {
                "key": "channel",
                "value": canal
            },
            {
                "key": "locale",
                "value": "pt-BR"
            }
        ]
    }

    parametros = urllib.parse.urlencode({
        "operationName": "SearchSuggestionsQuery",
        "variables": json.dumps(
            variables,
            ensure_ascii=False,
            separators=(",", ":")
        )
    })

    url = f"{ATACADAO_API}?{parametros}"

    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": "https://www.atacadao.com.br/"
        }
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=25
    ) as resposta:
        return json.loads(
            resposta.read().decode("utf-8")
        )


def obter_produtos_atacadao(dados: dict):
    return (
        dados.get("data", {})
        .get("search", {})
        .get("suggestions", {})
        .get("products", [])
    )


def extrair_ofertas_atacadao(item: dict):
    ofertas = item.get(
        "offers",
        {}
    ).get(
        "offers",
        []
    )

    validas = []

    for oferta in ofertas:
        try:
            preco = float(oferta.get("price"))
            minimo = int(
                oferta.get("minQuantity") or 1
            )
        except (TypeError, ValueError):
            continue

        if preco > 0:
            validas.append({
                "preco": preco,
                "minimo": minimo
            })

    if not validas:
        return None, None, None

    unitarias = [
        x for x in validas
        if x["minimo"] <= 1
    ]

    if unitarias:
        preco_unitario = min(
            x["preco"] for x in unitarias
        )
    else:
        preco_unitario = min(
            validas,
            key=lambda x: x["minimo"]
        )["preco"]

    atacado = [
        x for x in validas
        if x["minimo"] > 1
    ]

    if atacado:
        melhor_atacado = min(
            atacado,
            key=lambda x: x["preco"]
        )

        preco_atacado = melhor_atacado["preco"]
        quantidade_minima = melhor_atacado["minimo"]

    else:
        preco_atacado = None
        quantidade_minima = None

    return (
        preco_unitario,
        preco_atacado,
        quantidade_minima
    )


def buscar_atacadao(produto: Produto):
    termos = []

    if produto.ean:
        termos.append(
            produto.ean.strip()
        )

    nome = produto.produto.strip()

    if produto.marca:
        nome = (
            f"{nome} "
            f"{produto.marca.strip()}"
        )

    if nome:
        termos.append(nome)

    ultimo_erro = None

    for termo in termos:
        try:
            dados = consultar_atacadao(termo)

            produtos = obter_produtos_atacadao(
                dados
            )

            if not produtos:
                continue

            # O Atacadão pode devolver um GTIN
            # diferente do EAN pesquisado.
            # Por isso usamos o produto que
            # a própria busca retornou.
            item = produtos[0]

            (
                preco_unitario,
                preco_atacado,
                quantidade_minima
            ) = extrair_ofertas_atacadao(
                item
            )

            if preco_unitario is None:
                continue

            slug = item.get("slug", "")

            if slug:
                url_produto = (
                    "https://www.atacadao.com.br/"
                    f"{slug}/p"
                )
            else:
                url_produto = ""

            return {
                "produto_id": produto.id,
                "produto": item.get(
                    "name",
                    produto.produto
                ),
                "supermercado": "Atacadão",
                "preco_unitario": preco_unitario,
                "preco_atacado": preco_atacado,
                "quantidade_minima": quantidade_minima,
                "disponivel": True,
                "url": url_produto,
                "status": "OK",
                "observacao": (
                    "Preço obtido do Atacadão - "
                    "São José do Rio Preto América."
                )
            }

        except Exception as erro:
            ultimo_erro = (
                f"{type(erro).__name__}: {erro}"
            )

    if ultimo_erro:
        observacao = (
            "Falha ao consultar o Atacadão: "
            + ultimo_erro[:180]
        )
    else:
        observacao = (
            "Produto não encontrado no Atacadão."
        )

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
        "observacao": observacao
    }


@app.post("/coletar")
def coletar(pedido: PedidoColeta):
    resultados = []

    for produto in pedido.produtos:

        atacadao = buscar_atacadao(
            produto
        )

        atacadao["loja"] = (
            pedido.lojas.get(
                "atacadao",
                ""
            )
        )

        resultados.append(atacadao)

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
