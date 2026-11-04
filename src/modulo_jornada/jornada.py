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
    CONFIRMADO = auto()
    CONFIRMED = CONFIRMADO
    COMPLETED = auto()


@dataclass
class CartItem:
    produto_id: int
    nome: str
    quantidade: int
    preco_unitario: float
    variacoes: List[str] = field(default_factory=list)
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
        item_variacoes = sorted(set(item.variacoes))
        item.variacoes = item_variacoes
        for existing in self.itens:
            if existing.produto_id == item.produto_id and sorted(set(existing.variacoes)) == item_variacoes:
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
                    "variacoes": i.variacoes,
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
        self.last_user_text: Optional[str] = None
        self.last_message: Optional[str] = None
        self.last_intent: Optional[str] = None
        self.created_at: float = time.time()
        self.last_updated: float = time.time()

    def _reset_pending(self) -> None:
        self.pending_reason = None
        if self.state in (SessionState.PENDING, SessionState.CONFIRMADO, SessionState.COMPLETED):
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
        itens = nlu_payload.get("itens") or entidades.get("itens", [])
        repo = catalogo_repo or CatalogoRepository(json_path="data/cardapio_mock.json")

        # 2. Intenção ADICIONAR_ITEM
        if intencao == "ADICIONAR_ITEM":
            # Caso 2A: Lista de múltiplos itens detectados pelo SLM
            if itens:
                itens_adicionados = []
                itens_indisponiveis = list(nlu_payload.get("itens_invalidos", []))

                for it in itens:
                    p_id = it.get("produto_id")
                    p_nome = it.get("nome") or it.get("produto")
                    p_qtd = it.get("quantidade", 1)

                    produto = None
                    if p_id:
                        for p in repo.produtos:
                            if p.id == p_id:
                                produto = p
                                break
                    if not produto and p_nome:
                        produto = repo.buscar_produto_com_fuzzy(p_nome)

                    if not produto or not produto.disponibilidade:
                        itens_indisponiveis.append(p_nome or f"ID {p_id}")
                    else:
                        cart_item = CartItem(
                            produto_id=produto.id,
                            nome=produto.nome,
                            quantidade=p_qtd,
                            preco_unitario=produto.preco,
                            variacoes=list(it.get("variacoes", [])),
                        )
                        self.cart.add_item(cart_item)
                        itens_adicionados.append(f"{p_qtd}x {produto.nome}")

                if itens_indisponiveis:
                    self.state = SessionState.PENDING
                    self.pending_reason = f"Item(ns) indisponível(is) ou não encontrado(s): {', '.join(itens_indisponiveis)}."
                    msg = (
                        f"Adicionado: {', '.join(itens_adicionados)}. Atenção: {self.pending_reason}"
                        if itens_adicionados else self.pending_reason
                    )
                    return {
                        "origem": self.origem,
                        "estado": self.state.name,
                        "mensagem": msg,
                        "carrinho": self.cart.to_dict(),
                    }

                if itens_adicionados:
                    self._reset_pending()
                    return {
                        "origem": self.origem,
                        "estado": self.state.name,
                        "mensagem": f"Item(ns) adicionado(s): {', '.join(itens_adicionados)}.",
                        "carrinho": self.cart.to_dict(),
                    }

            # Caso 2B: Formato clássico de produto único (retrocompatibilidade)
            disponivel = entidades.get("disponivel")
            produto_id = entidades.get("produto_id")
            produto_nome = entidades.get("produto")
            quantidade = entidades.get("quantidade", 1)

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
                variacoes=list(entidades.get("variacoes", [])),
            )
            self.cart.add_item(item)
            self._reset_pending()

            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": f"Item '{produto.nome}' adicionado ({quantidade}x) na origem '{self.origem}'.",
                "carrinho": self.cart.to_dict(),
            }

        # 3. Intenção REMOVER_ITEM
        if intencao == "REMOVER_ITEM":
            itens_removidos = []
            for it in (itens or ([entidades] if entidades.get("produto_id") else [])):
                p_id = it.get("produto_id")
                p_nome = it.get("nome") or it.get("produto")
                p_qtd = it.get("quantidade", 1)

                produto = None
                if p_id:
                    for p in repo.produtos:
                        if p.id == p_id:
                            produto = p
                            break
                if not produto and p_nome:
                    produto = repo.buscar_produto_com_fuzzy(p_nome)

                if produto and self.cart.remove_item(produto.id, quantidade=p_qtd):
                    itens_removidos.append(f"{p_qtd}x {produto.nome}")

            if itens_removidos:
                return {
                    "origem": self.origem,
                    "estado": self.state.name,
                    "mensagem": f"Item(ns) removido(s): {', '.join(itens_removidos)}.",
                    "carrinho": self.cart.to_dict(),
                }
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": "Nenhum dos itens informados foi encontrado no carrinho para remoção.",
                "carrinho": self.cart.to_dict(),
            }

        # 4. Intenção CANCELAR_PEDIDO
        if intencao == "CANCELAR_PEDIDO":
            self.cart.clear()
            self.state = SessionState.ACTIVE
            self.pending_reason = None
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": f"Pedido cancelado e carrinho esvaziado para a origem '{self.origem}'.",
                "carrinho": self.cart.to_dict(),
            }

        # 5. Intenção CONFIRMAR_PEDIDO ou PEDIR_CONTA
        if intencao in ("CONFIRMAR_PEDIDO", "PEDIR_CONTA"):
            if not self.cart.itens:
                return {
                    "origem": self.origem,
                    "estado": self.state.name,
                    "mensagem": "Não é possível confirmar um pedido com carrinho vazio.",
                    "carrinho": self.cart.to_dict(),
                }
            self.state = SessionState.CONFIRMED
            self.pending_reason = None
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": f"Pedido confirmado com sucesso! Total: R$ {self.cart.total:.2f}.",
                "carrinho": self.cart.to_dict(),
            }

        # 6. Intenção INICIAR_PEDIDO (saudação / abertura de comanda por voz)
        if intencao == "INICIAR_PEDIDO":
            if self.state in (SessionState.CONFIRMADO, SessionState.COMPLETED):
                self.cart.clear()
            self._reset_pending()
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": f"Pedido aberto para {self.origem}",
                "carrinho": self.cart.to_dict(),
            }

        # 7. Intenção CHAMAR_ATENDIMENTO
        if intencao == "CHAMAR_ATENDIMENTO":
            return {
                "origem": self.origem,
                "estado": self.state.name,
                "mensagem": "Atendente chamado! Um colaborador já está indo até você.",
                "carrinho": self.cart.to_dict() if self.state != SessionState.PENDING else None,
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
            "texto_usuario": self.last_user_text,
            "mensagem": self.last_message,
            "intencao": self.last_intent,
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
        self._listeners: List[Any] = []

    def subscribe(self, listener: Any) -> Any:
        """Registra um observador para cada resultado processado pela jornada."""
        if listener not in self._listeners:
            self._listeners.append(listener)
        return listener

    def unsubscribe(self, listener: Any) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self, payload: Dict[str, Any]) -> None:
        for listener in list(self._listeners):
            listener(payload)

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
        texto_usuario = nlu_payload.get("texto_transcrito") or nlu_payload.get("texto_bruto") or ""
        intencao = nlu_payload.get("intencao")
        result = session.handle_nlu_result(nlu_payload, catalogo_repo=self.catalogo_repo)
        session.last_user_text = texto_usuario
        session.last_message = result.get("mensagem")
        session.last_intent = intencao
        broadcast_payload = {
            **result,
            "intencao": intencao,
            "texto_usuario": texto_usuario,
            "confianca": nlu_payload.get("confianca"),
            "pending_reason": session.pending_reason,
            "created_at": session.created_at,
            "last_updated": session.last_updated,
            "carrinho": session.cart.to_dict(),
        }
        self._notify_listeners(broadcast_payload)
        return result

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
