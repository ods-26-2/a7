"""Servidor FastAPI para o terminal de operação do projeto A7."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_jornada.jornada import SessionManager, SessionState
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[WebSocket, Optional[str]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = RLock()

    async def connect(self, websocket: WebSocket, origem: Optional[str] = None) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._loop = loop
            self._connections[websocket] = origem

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            self._connections.pop(websocket, None)

    async def _send(self, websocket: WebSocket, payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:
            self.disconnect(websocket)

    def publish(self, payload: Dict[str, Any]) -> None:
        """Publica no loop do servidor com latência mínima e sem bloquear a jornada."""
        with self._lock:
            targets = list(self._connections.items())
            loop = self._loop
        if loop is None:
            return

        for websocket, origem in targets:
            if origem and origem != payload.get("origem"):
                continue
            loop.call_soon_threadsafe(asyncio.create_task, self._send(websocket, payload))


def _normalize_origem(value: str) -> str:
    origem = value.strip()
    if not origem:
        raise HTTPException(status_code=400, detail="Origem da sessão é obrigatória.")
    return origem


def create_app(session_manager: Optional[SessionManager] = None) -> FastAPI:
    catalogo = CatalogoRepository(str(PROJECT_ROOT / "data" / "cardapio_mock.json"))
    manager = session_manager or SessionManager(catalogo_repo=catalogo)
    subscriber = AudioEventSubscriber(IntentClassifier(catalogo))
    connections = ConnectionManager()
    manager.subscribe(connections.publish)

    app = FastAPI(title="ODS A7 - Terminal de Operação", version="1.0.0")
    app.state.session_manager = manager
    app.state.catalogo = catalogo
    app.state.subscriber = subscriber
    app.state.connections = connections

    def process_event(event_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = event_payload.get("payload", event_payload)
        texto = payload.get("texto_transcrito") or payload.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise HTTPException(status_code=400, detail="O campo texto ou texto_transcrito é obrigatório.")
        nlu_result = subscriber.on_message_received(event_payload)
        return manager.handle_nlu_result(nlu_result)

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/cardapio")
    @app.get("/api/cardapio")
    def consultar_cardapio() -> Dict[str, Any]:
        produtos = [
            {
                "id": produto.id,
                "nome": produto.nome,
                "preco": produto.preco,
                "variacoes": produto.variacoes,
                "disponibilidade": produto.disponibilidade,
            }
            for produto in catalogo.produtos
        ]
        return {"produtos": produtos}

    @app.get("/menu")
    def consultar_menu() -> Dict[str, Any]:
        return consultar_cardapio()

    @app.get("/sessoes")
    def listar_sessoes() -> Dict[str, Any]:
        return {"sessoes": manager.listar_sessoes_ativas()}

    @app.get("/sessoes/{origem}")
    def consultar_sessao(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.obter_sessao(origem)
        if session is None:
            raise HTTPException(status_code=404, detail="Sessão não encontrada.")
        return session.to_dict()

    @app.get("/carrinho/{origem}")
    @app.get("/api/carrinho/{origem}")
    @app.get("/sessoes/{origem}/carrinho")
    def consultar_carrinho(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.obter_sessao(origem)
        if session is None:
            raise HTTPException(status_code=404, detail="Sessão não encontrada.")
        return session.cart.to_dict()

    @app.post("/eventos/nlu")
    @app.post("/eventos/voz")
    def receber_evento(event_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event_payload, dict):
            raise HTTPException(status_code=400, detail="Evento inválido.")
        return process_event(event_payload)

    def reset_session(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.get_or_create_session(origem)
        session.cart.clear()
        session.state = SessionState.ACTIVE
        session.pending_reason = None
        import time
        session.last_updated = time.time()
        payload = session.to_dict()
        payload["mensagem"] = "Carrinho resetado com sucesso."
        connections.publish(payload)
        return payload

    @app.post("/sessoes/{origem}/reset")
    @app.post("/reset/{origem}")
    @app.post("/api/reset/{origem}")
    def resetar_sessao(origem: str) -> Dict[str, Any]:
        return reset_session(origem)

    @app.post("/sessoes/{origem}/cancelar")
    @app.post("/cancelar/{origem}")
    @app.post("/api/cancelar/{origem}")
    def cancelar_sessao(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.get_or_create_session(origem)
        session.cart.clear()
        session.state = SessionState.ACTIVE
        session.pending_reason = None
        payload = session.to_dict()
        payload["mensagem"] = "Sessão cancelada; carrinho esvaziado."
        connections.publish(payload)
        return payload

    @app.delete("/sessoes/{origem}")
    def encerrar_sessao(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        if not manager.encerrar_sessao(origem):
            raise HTTPException(status_code=404, detail="Sessão não encontrada.")
        payload = {"origem": origem, "mensagem": "Sessão encerrada.", "estado": "COMPLETED"}
        connections.publish(payload)
        return payload

    @app.websocket("/ws/sessao")
    async def websocket_sessao(websocket: WebSocket, origem: Optional[str] = Query(default=None)) -> None:
        await connections.connect(websocket, origem)
        try:
            await websocket.send_json({"tipo": "conectado", "origem": origem})
            while True:
                text = await websocket.receive_text()
                try:
                    event_payload = json.loads(text)
                except json.JSONDecodeError:
                    await websocket.send_json({"tipo": "erro", "mensagem": "JSON inválido.", "status": 400})
                    continue
                try:
                    process_event(event_payload)
                except Exception as exc:
                    await websocket.send_json({"tipo": "erro", "mensagem": str(exc), "status": 400})
        except WebSocketDisconnect:
            connections.disconnect(websocket)

    return app


app = create_app()
