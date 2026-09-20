from datetime import datetime
from typing import Any
import json
import urllib.parse
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Coletor de Preços de Supermercados",
    version="3.0.0"
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


# ============================================================
# ATACADÃO
# Loja São José do Rio Preto América
# ============================================================

ATACADAO_API = "https://www.atacadao.com.br/api/graphql"
ATACADAO_SELLER = "atacadaobr949"
ATACADAO_REGION_ID = "v2.EB9CBB9497C9DD495FB7A98C30D4069D"
ATACADAO_SALES_CHANNEL = "1"


# ============================================================
# PÃO DE AÇÚCAR
# Loja identificada pelo site para a localização configurada
# ============================================================

PAO_API = "https://api.vendas.gpa.digital/pa/search/search"
PAO_STORE_ID = 461


@app.get("/")
def inicio():
    return {
        "sistema": "Coletor de preços",
        "status": "online",
        "versao": "3.0.0"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# ATACADÃO
# ============================================================

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
    ofertas = (
        item.get("offers", {})
        .get("offers", [])
    )

    validas = []

    for oferta in ofertas:
        try:
            preco = float(
                oferta.get("price")
            )

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
        oferta
        for oferta in validas
        if oferta["minimo"] <= 1
    ]

    if unitarias:
        preco_unitario = min(
            oferta["preco"]
            for oferta in unitarias
        )
    else:
        preco_unitario = min(
            validas,
            key=lambda oferta: oferta["minimo"]
        )["preco"]

    atacado = [
        oferta
        for oferta in validas
        if oferta["minimo"] > 1
    ]

    if atacado:
        melhor_atacado = min(
            atacado,
            key=lambda oferta: oferta["preco"]
        )

        preco_atacado = (
            melhor_atacado["preco"]
        )

        quantidade_minima = (
            melhor_atacado["minimo"]
        )

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
            dados = consultar_atacadao(
                termo
            )

            produtos = (
                obter_produtos_atacadao(
                    dados
                )
            )

            if not produtos:
                continue

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

            slug = item.get(
                "slug",
                ""
            )

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
                f"{type(erro).__name__}: "
                f"{erro}"
            )

    if ultimo_erro:
        observacao = (
            "Falha ao consultar o Atacadão: "
            + ultimo_erro[:180]
        )
    else:
        observacao = (
            "Produto não encontrado "
            "no Atacadão."
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


# ============================================================
# PÃO DE AÇÚCAR
# ============================================================

def consultar_pao_de_acucar(
    termo: str
):
    payload = {
        "terms": termo,
        "page": 1,
        "sortBy": "relevance",
        "resultsPerPage": 8,
        "allowRedirect": True,
        "customerPlus": True,
        "department": "ecom",
        "partner": "fallback",
        "storeId": PAO_STORE_ID
    }

    corpo = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    requisicao = urllib.request.Request(
        PAO_API,
        data=corpo,
        method="POST",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://www.paodeacucar.com",
            "Referer": (
                "https://www.paodeacucar.com/"
            )
        }
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=25
    ) as resposta:
        return json.loads(
            resposta.read().decode("utf-8")
        )


def escolher_produto_pao(
    produtos: list[dict],
    produto: Produto
):
    if not produtos:
        return None

    marca = ""

    if produto.marca:
        marca = (
            produto.marca
            .strip()
            .lower()
        )

    nome_base = (
        produto.produto
        .strip()
        .lower()
    )

    disponiveis = [
        item
        for item in produtos
        if item.get("stock") is True
    ]

    if disponiveis:
        candidatos = disponiveis
    else:
        candidatos = produtos

    for item in candidatos:
        nome_item = str(
            item.get("name", "")
        ).lower()

        marca_item = str(
            item.get("brand", "")
        ).lower()

        marca_ok = (
            not marca
            or marca in marca_item
            or marca in nome_item
        )

        nome_ok = (
            not nome_base
            or nome_base in nome_item
        )

        if marca_ok and nome_ok:
            return item

    if marca:
        for item in candidatos:
            nome_item = str(
                item.get("name", "")
            ).lower()

            marca_item = str(
                item.get("brand", "")
            ).lower()

            if (
                marca in marca_item
                or marca in nome_item
            ):
                return item

    return candidatos[0]


def buscar_pao_de_acucar(
    produto: Produto
):
    termos = []

    nome_com_marca = (
        produto.produto.strip()
    )

    if produto.marca:
        nome_com_marca = (
            f"{nome_com_marca} "
            f"{produto.marca.strip()}"
        )

    if nome_com_marca:
        termos.append(
            nome_com_marca
        )

    nome_simples = (
        produto.produto.strip()
    )

    if nome_simples:
        termos.append(
            nome_simples
        )

    ultimo_erro = None

    for termo in termos:
        try:
            dados = (
                consultar_pao_de_acucar(
                    termo
                )
            )

            produtos = dados.get(
                "products",
                []
            )

            item = (
                escolher_produto_pao(
                    produtos,
                    produto
                )
            )

            if not item:
                continue

            preco = item.get(
                "price"
            )

            try:
                preco = float(
                    preco
                )
            except (
                TypeError,
                ValueError
            ):
                continue

            if preco <= 0:
                continue

            disponivel = bool(
                item.get("stock")
            )

            url_produto = (
                item.get(
                    "urlDetails",
                    ""
                )
            )

            if (
                url_produto
                and url_produto.startswith("/")
            ):
                url_produto = (
                    "https://www.paodeacucar.com"
                    + url_produto
                )

            return {
                "produto_id": produto.id,
                "produto": item.get(
                    "name",
                    produto.produto
                ),
                "supermercado": "Pão de Açúcar",
                "preco_unitario": preco,
                "preco_atacado": None,
                "quantidade_minima": None,
                "disponivel": disponivel,
                "url": url_produto,
                "status": (
                    "OK"
                    if disponivel
                    else "INDISPONIVEL"
                ),
                "observacao": (
                    "Preço obtido do "
                    "Pão de Açúcar."
                )
            }

        except Exception as erro:
            ultimo_erro = (
                f"{type(erro).__name__}: "
                f"{erro}"
            )

    if ultimo_erro:
        observacao = (
            "Falha ao consultar "
            "o Pão de Açúcar: "
            + ultimo_erro[:180]
        )
    else:
        observacao = (
            "Produto não encontrado "
            "no Pão de Açúcar."
        )

    return {
        "produto_id": produto.id,
        "produto": produto.produto,
        "supermercado": "Pão de Açúcar",
        "preco_unitario": None,
        "preco_atacado": None,
        "quantidade_minima": None,
        "disponivel": False,
        "url": "",
        "status": "NAO_ENCONTRADO",
        "observacao": observacao
    }


# ============================================================
# COLETA GERAL
# ============================================================

@app.post("/coletar")
def coletar(
    pedido: PedidoColeta
):
    resultados = []

    for produto in pedido.produtos:

        # ATACADÃO
        atacadao = buscar_atacadao(
            produto
        )

        atacadao["loja"] = (
            pedido.lojas.get(
                "atacadao",
                ""
            )
        )

        resultados.append(
            atacadao
        )

        # PÃO DE AÇÚCAR
        pao_de_acucar = (
            buscar_pao_de_acucar(
                produto
            )
        )

        pao_de_acucar["loja"] = (
            pedido.lojas.get(
                "pao_de_acucar",
                ""
            )
        )

        resultados.append(
            pao_de_acucar
        )

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
