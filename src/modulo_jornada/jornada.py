# src/modulo_jornada/jornada.py
"""Módulo de jornada (gerenciador de sessão de pedido).

Este módulo contém a lógica de ciclo de vida da sessão de compra:

1️⃣ **Abertura** – cria um carrinho vazio quando a primeira intenção válida chega.
2️⃣ **Adição de itens** – recebe os *slots* extraídos pelo NLU (produto_id, produto, quantidade,
   disponivel) e, se o item está disponível, adiciona ao carrinho calculando subtotal.
3️⃣ **Revisão / Estado** – mantém o estado da sessão (ativo, pendente por ambiguidade ou
   indisponibilidade) e expõe métodos de consulta.

A regra de negócio **RF07** (não enviar nada sob ambiguidade) está implementada:
* Quando a confiança do áudio < 0.5 o NLU já retorna `intencao == "INDETERMINADO"`.
* Quando o slot indica `disponivel == False` ou `produto_id` é ``None`` o gerenciador marca
  a sessão como *pendente* e não altera o carrinho.

A classe ``SessionManager`` pode ser utilizada pelos pontos de entrada (ex.: ``main.py``) da
forma simples:
```python
session = SessionManager()
payload = subscriber.on_message_received(event)
response = session.handle_nlu_result(payload)
print(response)
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Any, Optional


class SessionState(Enum):
    """Representa os estados possíveis da sessão de pedido.

    * ``ACTIVE`` – sessão normal, carrinho pode receber itens.
    * ``PENDING`` – algum problema (indisponibilidade ou NLU incerta) bloqueia a
      operação até que o cliente esclareça.
    * ``COMPLETED`` – sessão finalizada (não usado ainda, mas reservado).
    """

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
    """Carrinho de compra em memória.

    Mantém a lista de ``CartItem`` e o cálculo do total geral.
    """

    def __init__(self) -> None:
        self.itens: List[CartItem] = []
        self.total: float = 0.0

    def add_item(self, item: CartItem) -> None:
        """Adiciona ``item`` ao carrinho e atualiza o total.

        Se o mesmo ``produto_id`` já existir, acumula a quantidade.
        """
        for existing in self.itens:
            if existing.produto_id == item.produto_id:
                existing.quantidade += item.quantidade
                existing.subtotal = round(existing.quantidade * existing.preco_unitario, 2)
                break
        else:
            self.itens.append(item)
        self._recalc_total()

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


class SessionManager:
    """Gerencia a sessão completa de pedido.

    * Cria o carrinho na primeira chamada válida.
    * Aplica a regra de ambiguidade: se o NLU retornar ``intencao == "INDETERMINADO"``
      ou se o slot indica indisponibilidade, a sessão entra em ``PENDING`` e devolve um
      objeto de resposta descrevendo a pendência.
    * Caso contrário, adiciona o item ao carrinho e permanece ``ACTIVE``.
    """

    def __init__(self) -> None:
        self.state: SessionState = SessionState.ACTIVE
        self.cart: Cart = Cart()
        self.pending_reason: Optional[str] = None

    def _reset_pending(self) -> None:
        self.pending_reason = None
        if self.state == SessionState.PENDING:
            self.state = SessionState.ACTIVE

    def handle_nlu_result(self, nlu_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Processa o dicionário retornado por ``AudioEventSubscriber``.

        Parameters
        ----------
        nlu_payload: dict
            Deve conter ao menos as chaves ``intencao`` e ``entidades`` quando a confiança
            for suficiente. Em caso de baixa confiança o NLU já devolve ``intencao``
            ``INDETERMINADO`` e pode conter a chave ``erro``.

        Returns
        -------
        dict
            Estrutura normalizada para o front‑end/operador contendo:
            ``estado`` – um dos valores de ``SessionState`` (string);
            ``mensagem`` – texto livre explicativo;
            ``carrinho`` – representação atual do carrinho (ou ``None`` quando pendente).
        """
        # 1️⃣ Verifica erro de confiança baixo já filtrado pelo NLU
        if nlu_payload.get("intencao") == "INDETERMINADO":
            self.state = SessionState.PENDING
            self.pending_reason = "Confiança baixa na transcrição de áudio."
            return {
                "estado": self.state.name,
                "mensagem": self.pending_reason,
                "carrinho": None,
            }

        # 2️⃣ Processa apenas a intenção de adicionar item (outros intents podem ser ampliados
        #    futuramente). Qualquer outra intenção será devolvida como "não suportada" para
        #    evitar ação inesperada.
        intencao = nlu_payload.get("intencao")
        entidades = nlu_payload.get("entidades", {})

        if intencao != "ADICIONAR_ITEM":
            # Para este card focamos apenas em ADICIONAR_ITEM. Mantemos o estado atual.
            return {
                "estado": self.state.name,
                "mensagem": f"Intenção '{intencao}' ainda não implementada.",
                "carrinho": self.cart.to_dict() if self.state != SessionState.PENDING else None,
            }

        # 3️⃣ Verifica disponibilidade e integridade dos slots
        disponivel = entidades.get("disponivel")
        produto_id = entidades.get("produto_id")
        produto_nome = entidades.get("produto")
        quantidade = entidades.get("quantidade", 1)

        if not disponivel or produto_id is None:
            self.state = SessionState.PENDING
            self.pending_reason = (
                "Item indisponível ou não reconhecido no catálogo. "
                "Solicite ao cliente que escolha outro produto."
            )
            return {
                "estado": self.state.name,
                "mensagem": self.pending_reason,
                "carrinho": None,
            }

        # 4️⃣ Busca preço no catálogo (usamos o repositório já carregado pelo NLU). O payload
        #    já vem de um ``SlotExtractor`` que recebeu o ``CatalogoRepository``; porém o
        #    preço não está no slot. Precisamos consultar novamente.
        #    **Nota:** O ``CatalogoRepository`` pode ser passado ao ``SessionManager`` quando
        #    houver necessidade; aqui, para manter a independência, importamos dinamicamente.
        from src.modulo_catalogo.repository import CatalogoRepository

        repo = CatalogoRepository(json_path="data/cardapio_mock.json")
        produto = repo.buscar_produto(produto_nome)
        if not produto:
            # Isso não deveria acontecer já que o slot já fez fuzzy‑match, mas tratamos
            # como fallback de ambiguidade.
            self.state = SessionState.PENDING
            self.pending_reason = "Produto não encontrado no catálogo após validação."
            return {
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
            "estado": self.state.name,
            "mensagem": f"Item '{produto.nome}' adicionado ({quantidade}x).",
            "carrinho": self.cart.to_dict(),
        }

__all__ = ["SessionManager", "SessionState", "Cart", "CartItem"]
