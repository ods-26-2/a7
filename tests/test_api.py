import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from src.modulo_backend.api import create_app


def make_client():
    return TestClient(create_app())


def test_health_menu_cart_and_session_routes():
    client = make_client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health").status_code == 200

    menu = client.get("/cardapio")
    assert menu.status_code == 200
    assert len(menu.json()["produtos"]) == 18

    assert client.get("/carrinho/mesa_teste").status_code == 404

    event = {
        "payload": {
            "origem": "mesa_teste",
            "texto_transcrito": "quero duas x-saladas",
            "confianca_geral": 0.95,
        }
    }
    result = client.post("/eventos/nlu", json=event)
    assert result.status_code == 200
    assert result.json()["carrinho"]["total"] == 45.8

    session = client.get("/sessoes/mesa_teste")
    assert session.status_code == 200
    assert session.json()["estado"] == "ACTIVE"

    reset = client.post("/sessoes/mesa_teste/reset")
    assert reset.status_code == 200
    assert reset.json()["carrinho"]["total"] == 0.0


def test_cancel_delete_and_invalid_event():
    client = make_client()

    event = {
        "payload": {
            "origem": "cancelar_teste",
            "texto_transcrito": "me vê uma coca cola",
            "confianca_geral": 0.95,
        }
    }
    assert client.post("/eventos/voz", json=event).status_code == 200
    assert client.post("/sessoes/cancelar_teste/cancelar").status_code == 200
    assert client.delete("/sessoes/cancelar_teste").status_code == 200
    assert client.get("/sessoes/cancelar_teste").status_code == 404

    invalid = client.post("/eventos/nlu", json={"payload": {"origem": "mesa_teste"}})
    assert invalid.status_code == 400


def test_websocket_broadcast_and_latency():
    client = make_client()

    with client.websocket_connect("/ws/sessao?origem=mesa_ws") as websocket:
        welcome = websocket.receive_json()
        assert welcome["tipo"] == "conectado"

        started = time.perf_counter()
        websocket.send_json({
            "payload": {
                "origem": "mesa_ws",
                "texto_transcrito": "quero uma coca cola lata",
                "confianca_geral": 0.95,
            }
        })

        update = websocket.receive_json()
        elapsed_ms = (time.perf_counter() - started) * 1000

        assert update["origem"] == "mesa_ws"
        assert update["estado"] == "ACTIVE"
        assert update["carrinho"]["total"] == 6.5
        assert elapsed_ms < 200, f"Broadcast levou {elapsed_ms:.2f} ms"


def test_frontend_ui_and_lexie_voice_flow():
    client = make_client()

    # Verifica servimento da interface B6
    ui_resp = client.get("/")
    assert ui_resp.status_code == 200
    assert "lexie" in ui_resp.text

    with client.websocket_connect("/ws/sessao") as websocket:
        welcome = websocket.receive_json()
        assert welcome["tipo"] == "conectado"

        # 1. Abertura de pedido por voz ("Fazer pedido")
        websocket.send_json({
            "payload": {
                "origem": "mesa_05",
                "texto_transcrito": "Fazer pedido",
                "confianca_geral": 0.98,
            }
        })
        abertura = websocket.receive_json()
        assert abertura["origem"] == "mesa_05"
        assert abertura["estado"] == "ACTIVE"
        assert abertura["intencao"] == "INICIAR_PEDIDO"

        # 2. Pedido múltiplo da inspiração ("Gostaria de dois X-Bacon e um suco de laranja.")
        websocket.send_json({
            "payload": {
                "origem": "mesa_05",
                "texto_transcrito": "Gostaria de dois X-Bacon e um suco de laranja.",
                "confianca_geral": 0.96,
            }
        })
        pedido = websocket.receive_json()
        assert pedido["estado"] == "ACTIVE"
        assert len(pedido["carrinho"]["itens"]) == 2
        assert pedido["carrinho"]["total"] == 61.0  # 2 * 26.50 + 8.00

        # 3. Alerta PENDING por dúvida explícita do I5 (confiança < 0.5)
        websocket.send_json({
            "payload": {
                "origem": "mesa_05",
                "texto_transcrito": "ruído baixo",
                "confianca_geral": 0.30,
            }
        })
        alerta = websocket.receive_json()
        assert alerta["estado"] == "PENDING"
        assert alerta["pending_reason"] is not None
        assert len(alerta["carrinho"]["itens"]) == 2  # Carrinho preservado

        # 4. Confirmação via endpoint REST mapeado
        conf_resp = client.post("/sessoes/mesa_05/confirmar")
        assert conf_resp.status_code == 200
        assert conf_resp.json()["estado"] == "CONFIRMADO"

