import sys
import os
import pytest

# Adiciona o diretório raiz do projeto ao sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber

@pytest.fixture
def nlu_pipeline():
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")
    classifier = IntentClassifier(catalogo_repo=catalogo)
    subscriber = AudioEventSubscriber(classifier)
    return subscriber

def test_criterio_de_aceite_nlu1_e_nlu2(nlu_pipeline):
    # Evento simulado do componente i5 via barramento
    evento_i5 = {
        "texto": "quero dois x-saladas",
        "confianca": 0.95
    }

    resultado = nlu_pipeline.on_message_received(evento_i5)

    assert resultado["intencao"] == "ADICIONAR_ITEM"
    assert resultado["texto_bruto"] == "dois x-saladas"
    
    # Validações da Task 18 (Slots com ID Oficial e Quantidade Numérica)
    entidades = resultado["entidades"]
    assert entidades["produto_id"] == 1
    assert entidades["produto"] == "X-Salada"
    assert entidades["quantidade"] == 2
    assert entidades["disponivel"] is True

def test_variacao_verbos_e_quantidade_extenso(nlu_pipeline):
    evento = {"texto": "me vê uma coca cola por favor", "confianca": 0.90}
    resultado = nlu_pipeline.on_message_received(evento)

    assert resultado["intencao"] == "ADICIONAR_ITEM"
    assert resultado["entidades"]["quantidade"] == 1
    assert "Coca-Cola" in resultado["entidades"]["produto"]

def test_quantidade_maior_com_limite(nlu_pipeline):
    # Testa extração de numerais maiores e a trava de segurança (máx 20)
    evento = {"texto": "quero 15 x-saladas", "confianca": 0.95}
    resultado = nlu_pipeline.on_message_received(evento)

    assert resultado["intencao"] == "ADICIONAR_ITEM"
    assert resultado["entidades"]["quantidade"] == 15
    assert resultado["entidades"]["produto_id"] == 1

def test_intencoes_remover_confirmar_cancelar(nlu_pipeline):
    remover = nlu_pipeline.on_message_received({"texto": "tira o x-salada", "confianca": 0.95})
    confirmar = nlu_pipeline.on_message_received({"texto": "confirmo o pedido", "confianca": 0.95})
    cancelar = nlu_pipeline.on_message_received({"texto": "cancela meu pedido", "confianca": 0.95})

    assert remover["intencao"] == "REMOVER_ITEM"
    assert remover["entidades"]["produto_id"] == 1

    remover_um = nlu_pipeline.on_message_received({"texto": "tira uma x-salada", "confianca": 0.95})
    assert remover_um["intencao"] == "REMOVER_ITEM"
    assert remover_um["entidades"]["produto_id"] == 1
    assert remover_um["entidades"]["quantidade"] == 1
    assert confirmar["intencao"] == "CONFIRMAR_PEDIDO"
    assert cancelar["intencao"] == "CANCELAR_PEDIDO"


def test_variacao_dinamica_vinculada_ao_produto(nlu_pipeline):
    resultado = nlu_pipeline.on_message_received({
        "texto": "quero um x-salada sem cebola",
        "confianca": 0.95,
    })
    assert resultado["entidades"]["produto_id"] == 1
    assert resultado["entidades"]["variacoes"] == ["sem cebola"]


def test_intencao_chamar_atendimento(nlu_pipeline):
    evento = {"texto": "pode chamar o garçom", "confianca": 0.88}
    resultado = nlu_pipeline.on_message_received(evento)

    assert resultado["intencao"] == "CHAMAR_ATENDIMENTO"


def test_slm_carregamento_config_yaml():
    from src.modulo_nlu.slm_classifier import SLMIntentClassifier
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")

    assert slm.model_name is not None
    assert "llama3.2" in slm.model_name or slm.model_name == "llama3.2:1b"
    assert slm.endpoint_url == "http://127.0.0.1:11434"
    assert len(slm.intencoes) >= 6
    assert slm.catalogo_repo is not None
    assert len(slm.catalogo_repo.produtos) > 0


def test_slm_classificacao_multiplos_itens():
    from src.modulo_nlu.slm_classifier import SLMIntentClassifier
    slm = SLMIntentClassifier(config_path="config/slm_config.yaml")

    res = slm.classify("eu quero um x-beico e uma batata frita")
    assert res["intencao"] == "ADICIONAR_ITEM"
    assert len(res["itens"]) == 2
    nomes = [item["nome"] for item in res["itens"]]
    assert "X-Bacon" in nomes
    assert "Batata Frita Padrão" in nomes
