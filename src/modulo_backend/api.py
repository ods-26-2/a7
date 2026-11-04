"""Servidor FastAPI para o terminal de operação do projeto A7."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from threading import RLock
import time
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_jornada.jornada import CartItem, SessionManager, SessionState
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
I5_DIRS = [
    PROJECT_ROOT / "jsons_gerados copy",
    PROJECT_ROOT / "jsons_gerados",
    PROJECT_ROOT.parent / "ods-i5-audio-transcription" / "jsons_gerados",
]


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

    def process_event(event_payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = event_payload.get("payload", event_payload)
        texto = payload.get("texto_transcrito") or payload.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            raise HTTPException(status_code=400, detail="O campo texto ou texto_transcrito é obrigatório.")
        nlu_result = subscriber.on_message_received(event_payload)
        return manager.handle_nlu_result(nlu_result)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Monitora diretórios de saída do I5 para ingerir novos arquivos JSON automaticamente
        seen_files: Set[Path] = set()
        for d in I5_DIRS:
            if d.exists():
                for f in d.glob("*.json"):
                    seen_files.add(f.resolve())

        stop_event = asyncio.Event()

        async def _watch_i5_dirs():
            while not stop_event.is_set():
                for d in I5_DIRS:
                    if not d.exists():
                        continue
                    for f in sorted(d.glob("*.json")):
                        resolved = f.resolve()
                        if resolved in seen_files:
                            continue
                        seen_files.add(resolved)
                        try:
                            with open(resolved, "r", encoding="utf-8") as fp:
                                data = json.load(fp)
                            process_event(data)
                        except Exception:
                            pass
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

        watcher_task = asyncio.create_task(_watch_i5_dirs())
        try:
            yield
        finally:
            stop_event.set()
            watcher_task.cancel()

    app = FastAPI(title="ODS A7 - Terminal de Operação (UI/UX B6 - Lexie)", version="1.0.0", lifespan=lifespan)
    app.state.session_manager = manager
    app.state.catalogo = catalogo
    app.state.subscriber = subscriber
    app.state.connections = connections

    if WEB_DIR.exists():
        app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    @app.get("/", include_in_schema=False)
    @app.get("/ui", include_in_schema=False)
    def index_ui():
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse("<h1>Interface B6 não encontrada em /web/index.html</h1>", status_code=404)

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
        session.last_updated = time.time()
        session.last_message = "Sessão cancelada; carrinho esvaziado."
        payload = session.to_dict()
        payload["mensagem"] = "Sessão cancelada; carrinho esvaziado."
        connections.publish(payload)
        return payload

    @app.post("/sessoes/{origem}/confirmar")
    @app.post("/confirmar/{origem}")
    @app.post("/api/confirmar/{origem}")
    def confirmar_sessao(origem: str) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.get_or_create_session(origem)
        if not session.cart.itens:
            raise HTTPException(status_code=400, detail="Não é possível confirmar um pedido com carrinho vazio.")
        session.state = SessionState.CONFIRMED
        session.pending_reason = None
        session.last_updated = time.time()
        msg = f"Pedido confirmado com sucesso! Total: R$ {session.cart.total:.2f}."
        session.last_message = msg
        payload = session.to_dict()
        payload["mensagem"] = msg
        connections.publish(payload)
        return payload

    @app.post("/sessoes/{origem}/editar")
    @app.put("/sessoes/{origem}/itens")
    @app.post("/api/editar/{origem}")
    def editar_sessao(origem: str, body: Dict[str, Any]) -> Dict[str, Any]:
        origem = _normalize_origem(origem)
        session = manager.get_or_create_session(origem)
        acao = str(body.get("acao", "atualizar")).lower()
        produto_id = body.get("produto_id")
        quantidade = int(body.get("quantidade", 1))
        variacoes = body.get("variacoes", [])
        if isinstance(variacoes, str):
            variacoes = [v.strip() for v in variacoes.split(",") if v.strip()]

        produto = next((p for p in catalogo.produtos if p.id == produto_id), None)
        if not produto:
            raise HTTPException(status_code=404, detail="Produto não encontrado no catálogo.")

        if acao == "remover" or quantidade <= 0:
            session.cart.remove_item(produto.id, quantidade=abs(quantidade) if quantidade > 0 else None)
            msg = f"Item '{produto.nome}' removido/atualizado."
        elif acao == "definir":
            session.cart.remove_item(produto.id, quantidade=None)
            session.cart.add_item(
                CartItem(
                    produto_id=produto.id,
                    nome=produto.nome,
                    quantidade=quantidade,
                    preco_unitario=produto.preco,
                    variacoes=list(variacoes),
                )
            )
            msg = f"Item '{produto.nome}' ajustado para {quantidade}x."
        else:
            session.cart.add_item(
                CartItem(
                    produto_id=produto.id,
                    nome=produto.nome,
                    quantidade=quantidade,
                    preco_unitario=produto.preco,
                    variacoes=list(variacoes),
                )
            )
            msg = f"Item '{produto.nome}' ({quantidade}x) adicionado."

        session._reset_pending()
        session.last_updated = time.time()
        session.last_message = msg
        payload = session.to_dict()
        payload["mensagem"] = msg
        connections.publish(payload)
        return payload

    @app.get("/api/i5/arquivos")
    def listar_arquivos_i5() -> Dict[str, Any]:
        arquivos: List[Dict[str, Any]] = []
        for d in I5_DIRS:
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        conteudo = json.load(fp)
                    pl = conteudo.get("payload", conteudo)
                    arquivos.append({
                        "nome": f.name,
                        "caminho": str(f.resolve()),
                        "pasta": d.name,
                        "origem": pl.get("origem", "default"),
                        "texto_transcrito": pl.get("texto_transcrito") or pl.get("texto", ""),
                        "confianca_geral": pl.get("confianca_geral", pl.get("confianca", 0.0)),
                    })
                except Exception:
                    continue
        return {"arquivos": arquivos}

    @app.post("/api/i5/reproduzir")
    def reproduzir_arquivo_i5(body: Dict[str, Any]) -> Dict[str, Any]:
        nome_ou_caminho = body.get("arquivo") or body.get("nome")
        origem_override = body.get("origem")
        if not nome_ou_caminho:
            raise HTTPException(status_code=400, detail="Informe o campo 'arquivo'.")

        alvo: Optional[Path] = None
        cand = Path(str(nome_ou_caminho))
        if cand.exists() and cand.is_file():
            alvo = cand
        else:
            for d in I5_DIRS:
                if d.exists() and (d / str(nome_ou_caminho)).exists():
                    alvo = d / str(nome_ou_caminho)
                    break

        if alvo is None:
            raise HTTPException(status_code=404, detail=f"Arquivo I5 '{nome_ou_caminho}' não encontrado.")

        with open(alvo, "r", encoding="utf-8") as fp:
            evento = json.load(fp)

        if origem_override:
            if "payload" in evento and isinstance(evento["payload"], dict):
                evento["payload"]["origem"] = origem_override
            else:
                evento["origem"] = origem_override

        return process_event(evento)

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
