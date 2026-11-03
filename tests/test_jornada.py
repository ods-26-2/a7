import sys
import os
import pytest

# Adiciona o diretório raiz ao sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber
from src.modulo_jornada.jornada import SessionManager, SessionState, OrderSession

@pytest.fixture
def session_manager():
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")
    return SessionManager(catalogo_repo=catalogo)

@pytest.fixture
def nlu_subscriber():
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")
    classifier = IntentClassifier(catalogo_repo=catalogo)
    return AudioEventSubscriber(classifier)

def test_multi_origem_sessoes_independentes(session_manager, nlu_subscriber):
    """
    Testa que chamadas vindas de origens diferentes (ex: mic_mesa_1 e mic_mesa_2)
    criam e acumulam itens em carrinhos completamente isolados.
    """
    # Evento para Mesa 1
    evento_mesa_1 = {
        "payload": {
            "origem": "mic_mesa_1",
            "texto_transcrito": "quero dois x-saladas",
            "confianca_geral": 0.95
        }
    }
    # Evento para Mesa 2
    evento_mesa_2 = {
        "payload": {
            "origem": "mic_mesa_2",
            "texto_transcrito": "me vê uma coca cola por favor",
            "confianca_geral": 0.90
        }
    }

    resp_nlu_1 = nlu_subscriber.on_message_received(evento_mesa_1)
    resp_nlu_2 = nlu_subscriber.on_message_received(evento_mesa_2)

    res_1 = session_manager.handle_nlu_result(resp_nlu_1)
    res_2 = session_manager.handle_nlu_result(resp_nlu_2)

    # Verifica Mesa 1
    assert res_1["origem"] == "mic_mesa_1"
    assert res_1["estado"] == "ACTIVE"
    assert len(res_1["carrinho"]["itens"]) == 1
    assert res_1["carrinho"]["itens"][0]["nome"] == "X-Salada"
    assert res_1["carrinho"]["itens"][0]["quantidade"] == 2

    # Verifica Mesa 2
    assert res_2["origem"] == "mic_mesa_2"
    assert res_2["estado"] == "ACTIVE"
    assert len(res_2["carrinho"]["itens"]) == 1
    assert "Coca-Cola" in res_2["carrinho"]["itens"][0]["nome"]
    assert res_2["carrinho"]["itens"][0]["quantidade"] == 1

    # Confirma isolamento no registry
    sess_1 = session_manager.obter_sessao("mic_mesa_1")
    sess_2 = session_manager.obter_sessao("mic_mesa_2")
    assert sess_1 is not None and sess_2 is not None
    assert sess_1.cart.total != sess_2.cart.total

def test_duvida_explicita_bloqueia_apenas_a_mesa_afetada(session_manager, nlu_subscriber):
    """
    Se a Mesa 1 receber áudio com baixa confiança (< 0.5), ela vai para PENDING,
    mas a Mesa 2 continua funcionando normalmente em ACTIVE.
    """
    # Mesa 1 pede com áudio inaudível
    evento_ruim_mesa_1 = {
        "payload": {
            "origem": "mic_mesa_1",
            "texto_transcrito": "blah ruído",
            "confianca_geral": 0.30
        }
    }
    # Mesa 2 pede com áudio bom
    evento_bom_mesa_2 = {
        "payload": {
            "origem": "mic_mesa_2",
            "texto_transcrito": "quero um x-salada",
            "confianca_geral": 0.92
        }
    }

    nlu_1 = nlu_subscriber.on_message_received(evento_ruim_mesa_1)
    nlu_2 = nlu_subscriber.on_message_received(evento_bom_mesa_2)

    res_1 = session_manager.handle_nlu_result(nlu_1)
    res_2 = session_manager.handle_nlu_result(nlu_2)

    assert res_1["estado"] == "PENDING"
    assert res_1["carrinho"] is None

    assert res_2["estado"] == "ACTIVE"
    assert res_2["carrinho"] is not None
    assert len(res_2["carrinho"]["itens"]) == 1

def test_remover_decrementa_quantidade_e_depois_exclui(session_manager, nlu_subscriber):
    origem = "mesa_decremento"

    adicionar = nlu_subscriber.on_message_received({
        "payload": {"origem": origem, "texto_transcrito": "quero duas x-saladas", "confianca_geral": 0.95}
    })
    resultado = session_manager.handle_nlu_result(adicionar)
    assert resultado["carrinho"]["itens"][0]["quantidade"] == 2
    assert resultado["carrinho"]["total"] == 45.8

    remover_um = nlu_subscriber.on_message_received({
        "payload": {"origem": origem, "texto_transcrito": "tira uma x-salada", "confianca_geral": 0.95}
    })
    resultado = session_manager.handle_nlu_result(remover_um)
    assert resultado["carrinho"]["itens"][0]["quantidade"] == 1
    assert resultado["carrinho"]["itens"][0]["subtotal"] == 22.9
    assert resultado["carrinho"]["total"] == 22.9

    remover_tudo = nlu_subscriber.on_message_received({
        "payload": {"origem": origem, "texto_transcrito": "tira o x-salada", "confianca_geral": 0.95}
    })
    resultado = session_manager.handle_nlu_result(remover_tudo)
    assert resultado["carrinho"]["itens"] == []
    assert resultado["carrinho"]["total"] == 0.0


def test_remover_confirmar_cancelar_e_variacoes(session_manager, nlu_subscriber):
    origem = "mesa_card"

    adicionar = nlu_subscriber.on_message_received({
        "payload": {
            "origem": origem,
            "texto_transcrito": "quero um x-salada sem cebola",
            "confianca_geral": 0.95,
        }
    })
    resultado = session_manager.handle_nlu_result(adicionar)
    assert resultado["carrinho"]["total"] == 22.9
    assert resultado["carrinho"]["itens"][0]["variacoes"] == ["sem cebola"]

    remover = nlu_subscriber.on_message_received({
        "payload": {
            "origem": origem,
            "texto_transcrito": "tira o x-salada",
            "confianca_geral": 0.95,
        }
    })
    resultado = session_manager.handle_nlu_result(remover)
    assert resultado["carrinho"]["total"] == 0.0
    assert resultado["carrinho"]["itens"] == []

    adicionar = nlu_subscriber.on_message_received({
        "payload": {
            "origem": origem,
            "texto_transcrito": "quero um x-salada",
            "confianca_geral": 0.95,
        }
    })
    session_manager.handle_nlu_result(adicionar)

    confirmar = nlu_subscriber.on_message_received({
        "payload": {
            "origem": origem,
            "texto_transcrito": "confirmo o pedido",
            "confianca_geral": 0.95,
        }
    })
    resultado = session_manager.handle_nlu_result(confirmar)
    assert resultado["estado"] == "CONFIRMADO"

    cancelar = nlu_subscriber.on_message_received({
        "payload": {
            "origem": origem,
            "texto_transcrito": "cancela meu pedido",
            "confianca_geral": 0.95,
        }
    })
    resultado = session_manager.handle_nlu_result(cancelar)
    assert resultado["estado"] == "ACTIVE"
    assert resultado["carrinho"]["total"] == 0.0


def test_listar_sessoes_ativas(session_manager, nlu_subscriber):
    evento = {
        "payload": {
            "origem": "mic_balcao",
            "texto_transcrito": "quero uma batata frita",
            "confianca_geral": 0.95
        }
    }
    nlu_res = nlu_subscriber.on_message_received(evento)
    session_manager.handle_nlu_result(nlu_res)

    lista = session_manager.listar_sessoes_ativas()
    assert len(lista) >= 1
    assert any(s["origem"] == "mic_balcao" for s in lista)

