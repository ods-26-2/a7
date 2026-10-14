# src/modulo_jornada/jornada.py
"""Módulo de jornada (gerenciador de sessões e ciclo de vida de pedidos).

Este módulo organiza o atendimento em duas classes complementares:

1️⃣ **OrderSession**: Representa o ciclo de vida e carrinho de UMA única mesa/microfone (`origem`).
   - Mantém estado (`ACTIVE`, `PENDING`, `COMPLETED`), carrinho isolado (`Cart`), timestamps de interação.
   - Aplica regras de negócio específicas daquela mesa (RF07: não avançar sob ambiguidade/indisponibilidade).

2️⃣ **SessionManager**: Orquestrador/Registry de múltiplas sessões simultâneas em memória.
   - Mapeia `origem -> OrderSession` (ex: "mesa_01", "mic_balcao", "mic_totem_streaming").
   - Recupera a sessão existente ou cria uma nova sob demanda.
   - Permite listar comandas abertas e gerenciar timeout/inatividade (RNF07).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Any, Optional

from src.modulo_catalogo.repository import CatalogoRepository


class SessionState(Enum):
    """Representa os estados possíveis da sessão de pedido."""
    ACTIVE = auto()
    PENDING = auto()
    COMPLETED = auto()


@dataclass
class CartItem:
    produto_id: int
    nome: str
    quantidade: int
    preco_unitario: float
    subtotal: float = field(init=False)

    def __post_init__(self) -> None:
        self.subtotal = round(self.quantidade * self.preco_unitario, 2)


class Cart:
    """Carrinho de compras isolado em memória."""

    def __init__(self) -> None:
        self.itens: List[CartItem] = []
        self.total: float = 0.0

    def add_item(self, item: CartItem) -> None:
        """Adiciona ou acumula quantidade do mesmo produto e atualiza total."""
        for existing in self.itens:
            if existing.produto_id == item.produto_id:
                existing.quantidade += item.quantidade
                existing.subtotal = round(existing.quantidade * existing.preco_unitario, 2)
                break
        else:
            self.itens.append(item)
        self._recalc_total()

    def remove_item(self, produto_id: int, quantidade: Optional[int] = None) -> bool:
        """Remove ou decrementa um item do carrinho."""
        for i, existing in enumerate(self.itens):
            if existing.produto_id == produto_id:
                if quantidade is None or existing.quantidade <= quantidade:
                    self.itens.pop(i)
                else:
                    existing.quantidade -= quantidade
                    existing.subtotal = round(existing.quantidade * existing.preco_unitario, 2)
                self._recalc_total()
                return True
        return False

    def clear(self) -> None:
        self.itens.clear()
        self.total = 0.0

    def _recalc_total(self) -> None:
        self.total = round(sum(i.subtotal for i in self.itens), 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "itens": [
                {
                    "produto_id": i.produto_id,
                    "nome": i.nome,
                    "quantidade": i.quantidade,
                    "preco_unitario": i.preco_unitario,
                    "subtotal": i.subtotal,
                }
                for i in self.itens
            ],
            "total": self.total,
        }


class OrderSession:
    """Representa a sessão individual de UMA origem/mesa/totem."""

    def __init__(self, origem: str):
        self.origem: str = origem
        self.state: SessionState = SessionState.ACTIVE
        self.cart: Cart = Cart()
        self.pending_reason: Optional[str] = None
        self.created_at: float = time.time()
        self.last_updated: float = time.time()

    def _reset_pending(self) -> None:
        self.pending_reason = None
        if self.state == SessionState.PENDING:
            self.state = SessionState.ACTIVE

    def handle_nlu_result(
        self, nlu_payload: Dict[str, Any], catalogo_repo: Optional[CatalogoRepository] = None
    ) -> Dict[str, Any]:
        """
        Processa um evento de NLU para esta sessão específica.
        Aplica a regra RF07 de dúvida explícita / ambiguidade.
        """
        self.last_updated = time.time()

        # 1. Erro ou baixa confiança do áudio (I5 / RF07)
        if nlu_payload.get("intencao") == "INDETERMINADO":
            self.state = SessionState.PENDING
            self.pending_reason = "Confiança baixa na transcrição de áudio."
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": self.pending_reason,
                "carrinho": None,
            }

        intencao = nlu_payload.get("intencao")
        entidades = nlu_payload.get("entidades", {})

        # 2. Intenção ADICIONAR_ITEM
        if intencao == "ADICIONAR_ITEM":
            disponivel = entidades.get("disponivel")
            produto_id = entidades.get("produto_id")
            produto_nome = entidades.get("produto")
            quantidade = entidades.get("quantidade", 1)

            # Trava de indisponibilidade ou item não identificado (RF07)
            if not disponivel or produto_id is None:
                self.state = SessionState.PENDING
                self.pending_reason = (
                    f"Item '{produto_nome}' indisponível ou não reconhecido no catálogo. "
                    "Solicite ao cliente que escolha outro produto."
                )
                return {
                    "origem": self.origem,
                    "estado": self.state.name,
                    "mensagem": self.pending_reason,
                    "carrinho": None,
                }

            # Busca preço no catálogo
            repo = catalogo_repo or CatalogoRepository(json_path="data/cardapio_mock.json")
            produto = repo.buscar_produto(produto_nome)
            if not produto:
                self.state = SessionState.PENDING
                self.pending_reason = "Produto não encontrado no catálogo após validação."
                return {
                    "origem": self.origem,
                    "estado": self.state.name,
                    "mensagem": self.pending_reason,
                    "carrinho": None,
                }

            item = CartItem(
                produto_id=produto.id,
                nome=produto.nome,
                quantidade=quantidade,
                preco_unitario=produto.preco,
            )
            self.cart.add_item(item)
            self._reset_pending()

            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": f"Item '{produto.nome}' adicionado ({quantidade}x) na origem '{self.origem}'.",
                "carrinho": self.cart.to_dict(),
            }

        # Demais intenções mantêm o estado atual
        return {
            "origem": self.origem,
            "estado": self.state.name,
            "mensagem": f"Intenção '{intencao}' recebida para a origem '{self.origem}'.",
            "carrinho": self.cart.to_dict() if self.state != SessionState.PENDING else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origem": self.origem,
            "estado": self.state.name,
            "pending_reason": self.pending_reason,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "carrinho": self.cart.to_dict(),
        }


class SessionManager:
    """
    Gerenciador global (Registry) de múltiplas sessões em memória.
    Indexa sessões por 'origem' (nome do microfone, mesa ou totem).
    """

    def __init__(self, catalogo_repo: Optional[CatalogoRepository] = None):
        self.catalogo_repo = catalogo_repo or CatalogoRepository(json_path="data/cardapio_mock.json")
        self.sessions: Dict[str, OrderSession] = {}

    def get_or_create_session(self, origem: str) -> OrderSession:
        """Recupera a sessão ativa para a origem informada ou instancia uma nova."""
        if origem not in self.sessions:
            self.sessions[origem] = OrderSession(origem=origem)
        return self.sessions[origem]

    def handle_nlu_result(self, nlu_payload: Dict[str, Any], origem: Optional[str] = None) -> Dict[str, Any]:
        """
        Recebe o resultado do NLU, identifica a origem e despacha para a OrderSession correspondente.
        """
        # A origem pode vir como parâmetro explícito ou dentro do próprio payload (AudioEventSubscriber)
        origem_id = origem or nlu_payload.get("origem", "default")
        session = self.get_or_create_session(origem_id)
        return session.handle_nlu_result(nlu_payload, catalogo_repo=self.catalogo_repo)

    def obter_sessao(self, origem: str) -> Optional[OrderSession]:
        return self.sessions.get(origem)

    def encerrar_sessao(self, origem: str) -> bool:
        if origem in self.sessions:
            del self.sessions[origem]
            return True
        return False

    def listar_sessoes_ativas(self) -> List[Dict[str, Any]]:
        """Devolve todas as comandas/sessões para exibição no frontend (B6)."""
        return [sess.to_dict() for sess in self.sessions.values()]

    def limpar_sessoes_inativas(self, timeout_segundos: float = 300.0) -> int:
        """Aplica a regra RNF07 de timeout de sessão inativa."""
        agora = time.time()
        expiradas = [
            origem for origem, sess in self.sessions.items()
            if agora - sess.last_updated > timeout_segundos
        ]
        for origem in expiradas:
            del self.sessions[origem]
        return len(expiradas)

    # Propriedades de conveniência para retrocompatibilidade com a sessão 'default'
    @property
    def cart(self) -> Cart:
        return self.get_or_create_session("default").cart

    @property
    def state(self) -> SessionState:
        return self.get_or_create_session("default").state

    @property
    def pending_reason(self) -> Optional[str]:
        return self.get_or_create_session("default").pending_reason


__all__ = ["SessionManager", "OrderSession", "SessionState", "Cart", "CartItem"]
