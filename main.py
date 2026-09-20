from datetime import datetime
from typing import Any
import base64
import json
import urllib.parse
import urllib.request

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Coletor de Preços de Supermercados",
    version="4.0.0"
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
# ============================================================

ATACADAO_API = "https://www.atacadao.com.br/api/graphql"
ATACADAO_SELLER = "atacadaobr949"
ATACADAO_REGION_ID = "v2.EB9CBB9497C9DD495FB7A98C30D4069D"
ATACADAO_SALES_CHANNEL = "1"


# ============================================================
# PÃO DE AÇÚCAR
# ============================================================

PAO_API = "https://api.vendas.gpa.digital/pa/search/search"
PAO_STORE_ID = 461


# ============================================================
# SUPER MUFFATO
# São José do Rio Preto - JK
# ============================================================

MUFFATO_AUTOCOMPLETE_API = (
    "https://www.supermuffato.com.br/_v/segment/graphql/v1"
)

MUFFATO_PRODUCT_API = (
    "https://www.supermuffato.com.br/"
    "api/catalog_system/pub/products/search/"
)

MUFFATO_SALES_CHANNEL = "16"

MUFFATO_BINDING_ID = (
    "7d99bd6c-e905-4258-8c5c-4ff47a370f11"
)

MUFFATO_AUTOCOMPLETE_HASH = (
    "dfdfa1d63a3244a3b78af4c2da594d69"
    "dded502faea04b7c2c115b34f253d2b1"
)


@app.get("/")
def inicio():
    return {
        "sistema": "Coletor de preços",
        "status": "online",
        "versao": "4.0.0"
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
            "User-Agent": "Mozilla/5.0",
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
            dados = consultar_atacadao(
                termo
            )

            produtos = obter_produtos_atacadao(
                dados
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
                f"{type(erro).__name__}: {erro}"
            )

    observacao = (
        "Falha ao consultar o Atacadão: "
        + ultimo_erro[:180]
        if ultimo_erro
        else "Produto não encontrado no Atacadão."
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

def consultar_pao_de_acucar(termo: str):
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
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://www.paodeacucar.com",
            "Referer": "https://www.paodeacucar.com/"
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

    marca = (
        produto.marca.strip().lower()
        if produto.marca
        else ""
    )

    nome_base = (
        produto.produto.strip().lower()
    )

    disponiveis = [
        item
        for item in produtos
        if item.get("stock") is True
    ]

    candidatos = (
        disponiveis
        if disponiveis
        else produtos
    )

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

    return candidatos[0]


def buscar_pao_de_acucar(produto: Produto):
    termos = []

    nome_com_marca = produto.produto.strip()

    if produto.marca:
        nome_com_marca = (
            f"{nome_com_marca} "
            f"{produto.marca.strip()}"
        )

    if nome_com_marca:
        termos.append(nome_com_marca)

    if produto.produto.strip():
        termos.append(
            produto.produto.strip()
        )

    ultimo_erro = None

    for termo in termos:
        try:
            dados = consultar_pao_de_acucar(
                termo
            )

            produtos = dados.get(
                "products",
                []
            )

            item = escolher_produto_pao(
                produtos,
                produto
            )

            if not item:
                continue

            try:
                preco = float(
                    item.get("price")
                )
            except (TypeError, ValueError):
                continue

            if preco <= 0:
                continue

            disponivel = bool(
                item.get("stock")
            )

            url_produto = item.get(
                "urlDetails",
                ""
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
                    "Preço obtido do Pão de Açúcar."
                )
            }

        except Exception as erro:
            ultimo_erro = (
                f"{type(erro).__name__}: {erro}"
            )

    observacao = (
        "Falha ao consultar o Pão de Açúcar: "
        + ultimo_erro[:180]
        if ultimo_erro
        else "Produto não encontrado no Pão de Açúcar."
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
# SUPER MUFFATO
# ============================================================

def consultar_muffato_autocomplete(
    termo: str
):
    variaveis = json.dumps(
        {
            "inputValue": termo
        },
        ensure_ascii=False,
        separators=(",", ":")
    ).encode("utf-8")

    variaveis_base64 = (
        base64.b64encode(
            variaveis
        ).decode("ascii")
    )

    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": (
                MUFFATO_AUTOCOMPLETE_HASH
            ),
            "sender": (
                "vtex.store-components@3.x"
            ),
            "provider": (
                "vtex.search-graphql@0.x"
            )
        },
        "variables": variaveis_base64
    }

    parametros = urllib.parse.urlencode({
        "workspace": "master",
        "maxAge": "medium",
        "appsEtag": "remove",
        "domain": "store",
        "locale": "pt-BR",
        "__bindingId": MUFFATO_BINDING_ID,
        "operationName": "Autocomplete",
        "variables": "{}",
        "extensions": json.dumps(
            extensions,
            separators=(",", ":")
        )
    })

    url = (
        f"{MUFFATO_AUTOCOMPLETE_API}"
        f"?{parametros}"
    )

    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.supermuffato.com.br/"
        }
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=25
    ) as resposta:
        return json.loads(
            resposta.read().decode("utf-8")
        )


def obter_sugestoes_muffato(
    dados: dict
):
    return (
        dados.get("data", {})
        .get("autocomplete", {})
        .get("itemsReturned", [])
    )


def escolher_sugestao_muffato(
    sugestoes: list[dict],
    produto: Produto
):
    candidatos = [
        item
        for item in sugestoes
        if item.get("productId")
    ]

    if not candidatos:
        return None

    ean = (
        produto.ean.strip()
        if produto.ean
        else ""
    )

    marca = (
        produto.marca.strip().lower()
        if produto.marca
        else ""
    )

    nome_base = (
        produto.produto.strip().lower()
    )

    if ean:
        for item in candidatos:
            thumb = str(
                item.get("thumb", "")
            )

            if ean in thumb:
                return item

    for item in candidatos:
        nome_item = str(
            item.get("name", "")
        ).lower()

        marca_ok = (
            not marca
            or marca in nome_item
        )

        nome_ok = (
            not nome_base
            or nome_base in nome_item
        )

        if marca_ok and nome_ok:
            return item

    return None

def consultar_muffato_produto(
    product_id: str
):
    parametros = urllib.parse.urlencode({
        "fq": f"productId:{product_id}",
        "sc": MUFFATO_SALES_CHANNEL
    })

    url = (
        f"{MUFFATO_PRODUCT_API}"
        f"?{parametros}"
    )

    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.supermuffato.com.br/"
        }
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=25
    ) as resposta:
        return json.loads(
            resposta.read().decode("utf-8")
        )


def extrair_oferta_muffato(
    produto_vtex: dict
):
    itens = produto_vtex.get(
        "items",
        []
    )

    for item in itens:
        for seller in item.get(
            "sellers",
            []
        ):
            oferta = seller.get(
                "commertialOffer",
                {}
            )

            disponivel = bool(
                oferta.get("IsAvailable")
            )

            quantidade = (
                oferta.get(
                    "AvailableQuantity",
                    0
                )
                or 0
            )

            try:
                preco = float(
                    oferta.get("Price")
                )
            except (TypeError, ValueError):
                continue

            if (
                disponivel
                and quantidade > 0
                and preco > 0
            ):
                return {
                    "preco": preco,
                    "disponivel": True
                }

    return None


def buscar_super_muffato(
    produto: Produto
):
    termos = []

    if produto.ean:
        termos.append(
            produto.ean.strip()
    )

    nome_com_marca = produto.produto.strip()

    if produto.marca:
        nome_com_marca = (
            f"{nome_com_marca} "
            f"{produto.marca.strip()}"
        )

    if nome_com_marca:
        termos.append(nome_com_marca)

    if produto.produto.strip():
        termos.append(
            produto.produto.strip()
        )

    ultimo_erro = None
    if produto.ean:
        try:
            parametros_ean = urllib.parse.urlencode({
                "fq": f"alternateIds_Ean:{produto.ean.strip()}",
                "sc": MUFFATO_SALES_CHANNEL
            })

            url_ean = (
                f"{MUFFATO_PRODUCT_API}"
                f"?{parametros_ean}"
            )

            requisicao_ean = urllib.request.Request(
                url_ean,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Referer": "https://www.supermuffato.com.br/"
                }
            )

            with urllib.request.urlopen(
                requisicao_ean,
                timeout=25
            ) as resposta:
                produtos_vtex = json.loads(
                    resposta.read().decode("utf-8")
                )

            if produtos_vtex:
                produto_vtex = produtos_vtex[0]

                oferta = extrair_oferta_muffato(
                    produto_vtex
                )

                if oferta:
                    return {
                        "produto_id": produto.id,
                        "produto": produto_vtex.get(
                            "productName",
                            produto.produto
                        ),
                        "supermercado": "Super Muffato",
                        "preco_unitario": oferta["preco"],
                        "preco_atacado": None,
                        "quantidade_minima": None,
                        "disponivel": True,
                        "url": produto_vtex.get(
                            "link",
                            ""
                        ),
                        "status": "OK",
                        "observacao": (
                            "Preço obtido do Super Muffato "
                            "diretamente pelo EAN."
                        )
                    }

        except Exception as erro:
            ultimo_erro = (
                f"{type(erro).__name__}: {erro}"
            )
    for termo in termos:
        try:
            dados_busca = (
                consultar_muffato_autocomplete(
                    termo
                )
            )

            sugestoes = obter_sugestoes_muffato(
                dados_busca
            )

            sugestao = escolher_sugestao_muffato(
                sugestoes,
                produto
            )

            if not sugestao:
                continue

            product_id = str(
                sugestao.get(
                    "productId",
                    ""
                )
            ).strip()

            if not product_id:
                continue

            produtos_vtex = (
                consultar_muffato_produto(
                    product_id
                )
            )

            if not produtos_vtex:
                continue

            produto_vtex = produtos_vtex[0]

            oferta = extrair_oferta_muffato(
                produto_vtex
            )

            if not oferta:
                continue

            link = produto_vtex.get(
                "link",
                ""
            )

            if not link:
                slug = sugestao.get(
                    "slug",
                    ""
                )

                if slug:
                    link = (
                        "https://www.supermuffato.com.br/"
                        f"{slug}/p"
                    )

            return {
                "produto_id": produto.id,
                "produto": produto_vtex.get(
                    "productName",
                    produto.produto
                ),
                "supermercado": "Super Muffato",
                "preco_unitario": oferta["preco"],
                "preco_atacado": None,
                "quantidade_minima": None,
                "disponivel": True,
                "url": link,
                "status": "OK",
                "observacao": (
                    "Preço obtido do Super Muffato - "
                    "São José do Rio Preto JK."
                )
            }

        except Exception as erro:
            ultimo_erro = (
                f"{type(erro).__name__}: {erro}"
            )

    observacao = (
        "Falha ao consultar o Super Muffato: "
        + ultimo_erro[:180]
        if ultimo_erro
        else "Produto não encontrado no Super Muffato."
    )

    return {
        "produto_id": produto.id,
        "produto": produto.produto,
        "supermercado": "Super Muffato",
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

        super_muffato = (
            buscar_super_muffato(
                produto
            )
        )

        super_muffato["loja"] = (
            pedido.lojas.get(
                "super_muffato",
                ""
            )
        )

        resultados.append(
            super_muffato
        )

    return {
        "data_hora": datetime.now().isoformat(),
        "cidade": pedido.cidade,
        "cep": pedido.cep,
        "precos": resultados
    }
