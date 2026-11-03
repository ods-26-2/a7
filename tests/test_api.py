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
