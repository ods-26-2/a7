#!/usr/bin/env python3
"""Demonstração visual dos critérios do card de operações do pedido."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_jornada.jornada import SessionManager
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber


def enviar(subscriber, manager, origem, texto):
    evento = {
        "payload": {
            "origem": origem,
            "texto_transcrito": texto,
            "confianca_geral": 0.95,
        }
    }
    nlu = subscriber.on_message_received(evento)
    return nlu, manager.handle_nlu_result(nlu)


def mostrar(numero, titulo, frase, resultado):
    carrinho = resultado.get("carrinho") or {"itens": [], "total": 0.0}
    print("\n" + "=" * 72)
    print(f"TESTE {numero}: {titulo}")
    print("=" * 72)
    print(f"Entrada:       {frase}")
    print(f"Intenção NLU:  {resultado.get('intencao', '—')}")
    print(f"Estado:        {resultado['estado']}")
    print(f"Mensagem:      {resultado['mensagem']}")
    print(f"Total:         R$ {carrinho['total']:.2f}")

    if carrinho["itens"]:
        print("Itens no carrinho:")
        for item in carrinho["itens"]:
            variacoes = ", ".join(item["variacoes"]) if item["variacoes"] else "nenhuma"
            print(
                f"  - {item['quantidade']}x {item['nome']} | "
                f"Variações: {variacoes} | Subtotal: R$ {item['subtotal']:.2f}"
            )
    else:
        print("Itens no carrinho: nenhum")


def validar(condicao, descricao):
    simbolo = "PASSOU" if condicao else "FALHOU"
    print(f"Resultado:     [{simbolo}] {descricao}\n")
    return condicao


def main():
    catalogo = CatalogoRepository(str(ROOT / "data" / "cardapio_mock.json"))
    manager = SessionManager(catalogo_repo=catalogo)
    subscriber = AudioEventSubscriber(IntentClassifier(catalogo_repo=catalogo))
    origem = "teste_visual"
    todos_passaram = True

    print("\nTESTE VISUAL DO CARD - OPERAÇÕES DE PEDIDO")
    print("Origem da sessão:", origem)

    # 1. Adicionar com variação
    frase = "quero um x-salada sem cebola"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]
    mostrar(1, "Adicionar item com variação", frase, resultado)
    ok = (
        resultado["estado"] == "ACTIVE"
        and resultado["carrinho"]["itens"][0]["variacoes"] == ["sem cebola"]
        and resultado["carrinho"]["total"] == 22.9
    )
    todos_passaram &= validar(ok, "Item adicionado, variação exibida e total recalculado")

    # 2. Preparar duas unidades e decrementar uma
    enviar(subscriber, manager, origem, "cancela meu pedido")

    frase = "quero duas x-saladas"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]

    frase_remocao = "tira uma x-salada"
    nlu, resultado = enviar(subscriber, manager, origem, frase_remocao)
    resultado["intencao"] = nlu["intencao"]
    mostrar(2, "Remover apenas uma unidade", frase_remocao, resultado)
    ok = (
        resultado["carrinho"]["total"] == 22.9
        and resultado["carrinho"]["itens"][0]["quantidade"] == 1
    )
    todos_passaram &= validar(ok, "Quantidade decrementada parcialmente e total recalculado")

    # 3. Remover item inteiro
    frase = "tira o x-salada"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]
    mostrar(3, "Remover item do carrinho", frase, resultado)
    ok = resultado["carrinho"]["total"] == 0.0 and resultado["carrinho"]["itens"] == []
    todos_passaram &= validar(ok, "Item removido e total recalculado para zero")

    # 4. Adicionar novamente
    frase = "quero um x-salada"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]
    mostrar(4, "Adicionar item antes da confirmação", frase, resultado)
    ok = resultado["carrinho"]["total"] == 22.9
    todos_passaram &= validar(ok, "Carrinho preparado para confirmação")

    # 5. Confirmar pedido
    frase = "confirmo o pedido"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]
    mostrar(5, "Confirmar pedido", frase, resultado)
    ok = resultado["estado"] == "CONFIRMADO"
    todos_passaram &= validar(ok, 'Estado alterado para "CONFIRMADO"')

    # 6. Cancelar pedido
    frase = "cancela meu pedido"
    nlu, resultado = enviar(subscriber, manager, origem, frase)
    resultado["intencao"] = nlu["intencao"]
    mostrar(6, "Cancelar pedido e limpar carrinho", frase, resultado)
    ok = resultado["estado"] == "ACTIVE" and resultado["carrinho"]["total"] == 0.0
    todos_passaram &= validar(ok, "Sessão resetada para ACTIVE e carrinho vazio")

    print("\n" + "#" * 72)
    if todos_passaram:
        print("RESULTADO FINAL: TODOS OS TESTES DO CARD PASSARAM")
    else:
        print("RESULTADO FINAL: ALGUM TESTE DO CARD FALHOU")
        return 1
    print("#" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
