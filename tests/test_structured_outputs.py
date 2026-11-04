"""
Testes unitários para Structured Outputs com JSON Schema Estrito (Grammar-based Decoding)
no classificador SLM do Módulo NLU (A7).
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from src.modulo_nlu.slm_classifier import SLMIntentClassifier


def test_geracao_dinamica_json_schema():
    """Valida se o JSON Schema é gerado dinamicamente com todas as intenções do catálogo."""
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")
    schema = slm._gerar_json_schema()

    assert schema["type"] == "object"
    assert set(schema["required"]) == {"intencao", "confianca", "itens", "itens_invalidos"}

    # Verifica enum de intenções
    enum_intencoes = schema["properties"]["intencao"]["enum"]
    assert "ADICIONAR_ITEM" in enum_intencoes
    assert "REMOVER_ITEM" in enum_intencoes
    assert "CONFIRMAR_PEDIDO" in enum_intencoes
    assert "CANCELAR_PEDIDO" in enum_intencoes
    assert "CONSULTAR_CARDAPIO" in enum_intencoes
    assert "CHAMAR_ATENDIMENTO" in enum_intencoes
    assert "PEDIR_CONTA" in enum_intencoes
    assert "DESCONHECIDO" in enum_intencoes

    # Verifica estrutura de itens e suporte a variações
    item_props = schema["properties"]["itens"]["items"]["properties"]
    assert item_props["produto_id"]["type"] == "integer"
    assert item_props["nome"]["type"] == "string"
    assert item_props["quantidade"]["type"] == "integer"
    assert item_props["quantidade"]["minimum"] == 1
    assert item_props["quantidade"]["maximum"] == 20
    assert "variacoes" in item_props
    assert item_props["variacoes"]["type"] == "array"


def test_envio_json_schema_no_payload_ollama():
    """Verifica se o JSON Schema completo é enviado no campo 'format' para o Ollama."""
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")
    slm.model_driver = "ollama"
    slm.structured_outputs = True

    resposta_mock_ollama = {
        "response": json.dumps(
            {
                "intencao": "ADICIONAR_ITEM",
                "confianca": 0.97,
                "itens": [
                    {
                        "produto_id": 6,
                        "nome": "Refrigerante",
                        "quantidade": 2,
                        "variacoes": ["lata", "zero"],
                    }
                ],
                "itens_invalidos": [],
            }
        )
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(resposta_mock_ollama).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        resultado = slm.invocar_slm("Prompt de teste", texto_usuario="quero dois refrigerantes lata zero")

        assert mock_urlopen.called
        req_enviada = mock_urlopen.call_args[0][0]
        body_enviado = json.loads(req_enviada.data.decode("utf-8"))

        # O campo format deve ser um dicionário contendo o JSON Schema
        assert isinstance(body_enviado["format"], dict)
        assert body_enviado["format"]["type"] == "object"
        assert "ADICIONAR_ITEM" in body_enviado["format"]["properties"]["intencao"]["enum"]

        # Valida resposta processada
        assert resultado["intencao"] == "ADICIONAR_ITEM"
        assert resultado["confianca"] == 0.97
        assert len(resultado["itens"]) == 1
        assert resultado["itens"][0]["variacoes"] == ["lata", "zero"]
        assert "JSON Schema Estrito" in resultado["justificativa"]


def test_fallback_para_format_json_em_ollama_legado():
    """
    Garante que, se uma versão antiga do Ollama rejeitar o objeto de schema com HTTP 400,
    o classificador refaz a chamada usando 'format': 'json'.
    """
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")
    slm.model_driver = "ollama"
    slm.structured_outputs = True

    resposta_sucesso = {
        "response": json.dumps(
            {
                "intencao": "PEDIR_CONTA",
                "confianca": 0.92,
                "itens": [],
                "itens_invalidos": [],
            }
        )
    }

    mock_resp_ok = MagicMock()
    mock_resp_ok.status = 200
    mock_resp_ok.read.return_value = json.dumps(resposta_sucesso).encode("utf-8")
    mock_resp_ok.__enter__.return_value = mock_resp_ok

    erro_400 = urllib.error.HTTPError(
        url="http://127.0.0.1:11434/api/generate",
        code=400,
        msg="Bad Request: format must be 'json'",
        hdrs=None,
        fp=io.BytesIO(b"error"),
    )

    with patch("urllib.request.urlopen", side_effect=[erro_400, mock_resp_ok]) as mock_urlopen:
        resultado = slm.invocar_slm("Prompt de teste", texto_usuario="pode fechar a conta")

        assert mock_urlopen.call_count == 2
        # Primeira chamada tentou usar o dicionário de schema
        req_1 = json.loads(mock_urlopen.call_args_list[0][0][0].data.decode("utf-8"))
        assert isinstance(req_1["format"], dict)

        # Segunda chamada fez fallback para string "json"
        req_2 = json.loads(mock_urlopen.call_args_list[1][0][0].data.decode("utf-8"))
        assert req_2["format"] == "json"

        assert resultado["intencao"] == "PEDIR_CONTA"
        assert resultado["confianca"] == 0.92


def test_sanitizacao_de_resposta_malformada():
    """Verifica se o sanitizador corrige tipos inválidos, limites de quantidade e confiança."""
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")
    nomes_validos = [item["nome"] for item in slm.intencoes] + ["DESCONHECIDO"]

    dados_sujos = {
        "intencao": "adicionar_item",
        "confianca": "1.5",  # Acima de 1.0 e como string
        "itens": [
            {
                "produto_id": "2",
                "nome": "  X-Bacon  ",
                "quantidade": "99",  # Acima do limite máximo de 20
                "variacoes": ["  bem passado ", ""],
            }
        ],
        "itens_invalidos": ["  sushi  ", ""],
    }

    limpo = slm._validar_e_sanitizar_resposta(dados_sujos, nomes_validos)
    assert limpo["intencao"] == "ADICIONAR_ITEM"
    assert limpo["confianca"] == 1.0
    assert len(limpo["itens"]) == 1
    assert limpo["itens"][0]["produto_id"] == 2
    assert limpo["itens"][0]["nome"] == "X-Bacon"
    assert limpo["itens"][0]["quantidade"] == 20
    assert limpo["itens"][0]["variacoes"] == ["bem passado"]
    assert limpo["itens_invalidos"] == ["sushi"]


def test_selecao_e_troca_de_perfis_slm():
    """Valida se o classificador resolve corretamente perfis ativos e por parâmetro."""
    # Perfil padrão ativo
    slm_default = SLMIntentClassifier(config_path="config/slm_config.yaml")
    assert slm_default.perfil_ativo in ["llama3.2_ollama", "bonsai2_27b", "llama3.2_finetuned"]

    # Forçando perfil bonsai2_27b
    slm_bonsai = SLMIntentClassifier(config_path="config/slm_config.yaml", perfil="bonsai2_27b")
    assert slm_bonsai.perfil_ativo == "bonsai2_27b"
    assert slm_bonsai.provedor == "llama_server"
    assert slm_bonsai.endpoint_url == "http://127.0.0.1:8080"
    assert "Bonsai" in slm_bonsai.model_name

    # Forçando perfil llama3.2_ollama
    slm_llama = SLMIntentClassifier(config_path="config/slm_config.yaml", perfil="llama3.2_ollama")
    assert slm_llama.perfil_ativo == "llama3.2_ollama"
    assert slm_llama.provedor == "ollama"
    assert slm_llama.endpoint_url == "http://127.0.0.1:11434"


def test_envio_json_schema_para_llama_server_bonsai():
    """Valida envio do json_schema para o endpoint /completion do llama-server (Bonsai 2)."""
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml", perfil="bonsai2_27b")
    slm.model_driver = "llama_server"

    resposta_mock_llama_server = {
        "content": json.dumps(
            {
                "intencao": "ADICIONAR_ITEM",
                "confianca": 0.99,
                "itens": [
                    {
                        "produto_id": 2,
                        "nome": "X-Bacon",
                        "quantidade": 1,
                        "variacoes": ["bem passado"],
                    }
                ],
                "itens_invalidos": [],
            }
        )
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(resposta_mock_llama_server).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        resultado = slm.invocar_slm("Prompt para Bonsai", texto_usuario="quero um x-bacon bem passado")

        assert mock_urlopen.called
        req_enviada = mock_urlopen.call_args[0][0]
        assert req_enviada.full_url == "http://127.0.0.1:8080/completion"
        body = json.loads(req_enviada.data.decode("utf-8"))

        assert "json_schema" in body
        assert isinstance(body["json_schema"], dict)
        assert "ADICIONAR_ITEM" in body["json_schema"]["properties"]["intencao"]["enum"]

        assert resultado["intencao"] == "ADICIONAR_ITEM"
        assert resultado["confianca"] == 0.99
        assert len(resultado["itens"]) == 1
        assert resultado["itens"][0]["nome"] == "X-Bacon"
        assert "llama-server (JSON Schema Estrito)" in resultado["justificativa"]


