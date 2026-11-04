#!/usr/bin/env python3
"""
Gerador de Dataset Sintético para Fine-Tuning (LoRA / QLoRA) do Motor NLU (A7 Varejo).

Lê dinamicamente `data/cardapio_mock.json` e `data/intencoes_catalogo.json` para
construir centenas de exemplos variados (ShareGPT / ChatML e Alpaca) cobrindo:
  - Pedidos simples e múltiplos com quantidades (dígitos e por extenso)
  - Variações de produtos (ex: "sem cebola", "Zero Açúcar", "com cheddar e bacon")
  - Erros fonéticos do Whisper e gírias (ex: "xizbeito", "chi-salada", "batatinha", "coca lata")
  - Conversas paralelas e ruído de fundo antes do pedido
  - Autocorreções na mesma frase (ex: "quero um x-salada, não pera, vê um x-bacon")
  - Pedidos mistos com itens fora do cardápio (populando `itens_invalidos`)
  - Dúvidas explícitas / hesitações (Regra RF07 -> DESCONHECIDO ou baixa confiança)
  - Remoção de itens, confirmação, cancelamento, consulta, atendente e conta.

Uso:
  python3 scripts/gerar_dataset_lora.py
  python3 scripts/gerar_dataset_lora.py --total 800 --output data/dataset_lora_nlu.jsonl
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
CARDAPIO_PATH = ROOT_DIR / "data" / "cardapio_mock.json"
INTENCOES_PATH = ROOT_DIR / "data" / "intencoes_catalogo.json"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "dataset_lora_nlu.jsonl"

# Mapeamento de variações fonéticas / apelidos realistas do ASR (Whisper) para treino de robustez
APELIDOS_FONETICOS: Dict[int, List[str]] = {
    1: ["x-salada", "xis salada", "chi-salada", "x salada", "xis-salada"],
    2: ["x-bacon", "xis bacon", "xizbeito", "chi-bacon", "x-beico", "xis beico"],
    3: ["x-tudo", "xis tudo", "chi-tudo", "xtudo", "x tudo completo"],
    4: ["hamburguer artesanal", "smash burger", "artesanal smash", "hambúrguer smash"],
    5: ["vegetariano", "lanche vegetariano", "vegetariano futuro", "hamburguer vegano"],
    6: ["coca lata", "coca-cola lata", "coca 350", "uma coquinha lata", "refrigerante coca lata"],
    7: ["coca 600", "coca-cola 600ml", "coca garrafa", "coca de 600"],
    8: ["guaraná", "guaraná lata", "guaraná antarctica", "guarana 350"],
    9: ["suco de laranja", "suco natural", "suquinho de laranja", "suco laranja 500ml"],
    10: ["água", "água mineral", "aguinha", "garrafa de água"],
    11: ["batata frita", "batatinha frita", "batata padrão", "porção de batata", "patata frita"],
    12: ["batata grande", "batata frita grande", "batatona frita"],
    13: ["onion rings", "anéis de cebola", "cebola empanada"],
    14: ["nuggets", "nuggets de frango", "porção de nuggets", "8 nuggets"],
    15: ["milkshake de chocolate", "milk shake chocolate", "shake de chocolate"],
    16: ["milkshake de morango", "milk shake morango", "shake de morango"],
    17: ["pudim", "pudim de leite", "pudim de leite condensado"],
    18: ["brownie", "brownie com sorvete", "brownie de chocolate"],
}

ITENS_INVALIDOS_POOL = [
    "sushi de salmão",
    "pizza de calabresa",
    "pastel de queijo",
    "coxinha de frango",
    "chopp gelado",
    "açaí na tigela",
    "espetinho de carne",
    "lasanha à bolonhesa",
    "cerveja heineken",
    "tapioca de frango",
    "cachorro-quente",
    "empada de palmito",
]

RUIDOS_INICIAIS = [
    "",
    "",
    "",
    "Oi, boa noite... ",
    "Hoje gente estamos testando aqui. ",
    "Deixa eu ver o que eu vou querer... ",
    "Então, o trânsito tava horrível hoje né, mas ",
    "Ô amigo, tudo bom? ",
    "Metaspoye. Oi, eu queria fazer um pedido... ",
    "Hum, estou pensando aqui... já sei: ",
]

VERBOS_ADICIONAR = [
    "quero",
    "eu quero",
    "me vê",
    "me traz",
    "vou pedir",
    "adiciona aí",
    "bota no pedido",
    "gostaria de pedir",
    "manda pra mim",
    "inclui por favor",
]

VERBOS_REMOVER = [
    "tira",
    "remove",
    "pode tirar",
    "exclui do carrinho",
    "não quero mais",
    "retira",
    "cancela só",
]

NUMERAIS_TEXTO = {
    1: ["um", "uma", "1"],
    2: ["dois", "duas", "2"],
    3: ["três", "tres", "3"],
    4: ["quatro", "4"],
    5: ["cinco", "5"],
}

FALAS_FORA_CONTEXTO_E_DUVIDA = [
    "Amigo, onde que fica o banheiro aqui do shopping?",
    "Qual é a senha do wi-fi da lanchonete?",
    "Nossa, será que vai chover mais tarde?",
    "Não sei se peço um x-tudo ou se cancelo tudo... espera aí, deixa eu perguntar pro meu amigo antes.",
    "Tô em dúvida ainda, não anota nada por enquanto não.",
    "Espera só um minutinho que minha esposa já vem escolher.",
    "Vocês aceitam vale-refeição ou só cartão de crédito?",
    "Que horas a loja fecha hoje?",
    "Alô, tá me ouvindo? Teste um dois três.",
]


def carregar_dados() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    with open(CARDAPIO_PATH, "r", encoding="utf-8") as f:
        cardapio = json.load(f)
    with open(INTENCOES_PATH, "r", encoding="utf-8") as f:
        intencoes = json.load(f)
    return cardapio, intencoes


def montar_instrucao_sistema(cardapio: List[Dict[str, Any]], incluir_cardapio: bool = True) -> str:
    resumo_cardapio = "\n".join([f"- ID {p['id']}: {p['nome']}" for p in cardapio])
    base = (
        "Você é o motor de NLU de uma lanchonete/restaurante de varejo.\n"
        "Classifique a intenção do cliente e extraia os itens do cardápio oficial ESTRITAMENTE em JSON puro."
    )
    if incluir_cardapio:
        return f"{base}\n\nCARDÁPIO OFICIAL:\n{resumo_cardapio}"
    return base


def sortear_apelido(produto: Dict[str, Any]) -> str:
    pid = produto["id"]
    opcoes = APELIDOS_FONETICOS.get(pid, [produto["nome"].lower()])
    return random.choice(opcoes + [produto["nome"]])


def sortear_quantidade() -> Tuple[int, str]:
    qtd = random.choices([1, 2, 3, 4], weights=[65, 22, 9, 4])[0]
    texto_qtd = random.choice(NUMERAIS_TEXTO[qtd])
    return qtd, texto_qtd


def gerar_exemplo_adicionar_simples(cardapio: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    prod = random.choice(cardapio)
    qtd, qtd_txt = sortear_quantidade()
    apelido = sortear_apelido(prod)
    ruido = random.choice(RUIDOS_INICIAIS)
    verbo = random.choice(VERBOS_ADICIONAR)

    variacoes_escolhidas = []
    var_txt = ""
    if prod.get("variacoes") and random.random() < 0.45:
        var = random.choice(prod["variacoes"])
        variacoes_escolhidas.append(var)
        var_txt = f" {var.lower()}"

    cortesia = random.choice(["", " por favor", " pra viagem", " bem caprichado"])
    fala = f"{ruido}{verbo} {qtd_txt} {apelido}{var_txt}{cortesia}".strip()

    item_dict: Dict[str, Any] = {
        "produto_id": prod["id"],
        "nome": prod["nome"],
        "quantidade": qtd,
    }
    if variacoes_escolhidas:
        item_dict["variacoes"] = variacoes_escolhidas

    saida = {
        "intencao": "ADICIONAR_ITEM",
        "confianca": round(random.uniform(0.92, 0.99), 2),
        "itens": [item_dict],
        "itens_invalidos": [],
    }
    return fala, saida


def gerar_exemplo_adicionar_multiplo(cardapio: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    num_itens = random.choice([2, 3])
    prods = random.sample(cardapio, k=num_itens)
    ruido = random.choice(RUIDOS_INICIAIS)
    verbo = random.choice(VERBOS_ADICIONAR)

    partes_fala = []
    itens_saida = []

    for p in prods:
        qtd, qtd_txt = sortear_quantidade()
        apelido = sortear_apelido(p)
        variacoes_escolhidas = []
        var_txt = ""
        if p.get("variacoes") and random.random() < 0.35:
            var = random.choice(p["variacoes"])
            variacoes_escolhidas.append(var)
            var_txt = f" {var.lower()}"

        partes_fala.append(f"{qtd_txt} {apelido}{var_txt}")
        item_obj: Dict[str, Any] = {
            "produto_id": p["id"],
            "nome": p["nome"],
            "quantidade": qtd,
        }
        if variacoes_escolhidas:
            item_obj["variacoes"] = variacoes_escolhidas
        itens_saida.append(item_obj)

    if len(partes_fala) == 2:
        conector = random.choice([" e ", " com ", " mais "])
        corpo = conector.join(partes_fala)
    else:
        corpo = f"{partes_fala[0]}, {partes_fala[1]} e {partes_fala[2]}"

    fala = f"{ruido}{verbo} {corpo}".strip()
    saida = {
        "intencao": "ADICIONAR_ITEM",
        "confianca": round(random.uniform(0.90, 0.98), 2),
        "itens": itens_saida,
        "itens_invalidos": [],
    }
    return fala, saida


def gerar_exemplo_autocorrecao(cardapio: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Simula o cliente mudando de ideia na mesma frase."""
    p_errado, p_certo = random.sample(cardapio, k=2)
    qtd, qtd_txt = sortear_quantidade()
    fala_template = random.choice(
        [
            f"Eu ia querer um {sortear_apelido(p_errado)}, não pera, troca por {qtd_txt} {sortear_apelido(p_certo)}",
            f"Me vê um {sortear_apelido(p_errado)}... quer dizer, melhor não, coloca {qtd_txt} {sortear_apelido(p_certo)}",
            f"Quero {sortear_apelido(p_errado)}, opa, falei errado, é {qtd_txt} {sortear_apelido(p_certo)} por favor",
        ]
    )
    saida = {
        "intencao": "ADICIONAR_ITEM",
        "confianca": round(random.uniform(0.88, 0.95), 2),
        "itens": [
            {
                "produto_id": p_certo["id"],
                "nome": p_certo["nome"],
                "quantidade": qtd,
            }
        ],
        "itens_invalidos": [],
    }
    return fala_template, saida


def gerar_exemplo_pedido_misto_invalido(cardapio: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Simula pedido com item válido + item fora do cardápio (ou apenas item inválido)."""
    invalido = random.choice(ITENS_INVALIDOS_POOL)
    verbo = random.choice(VERBOS_ADICIONAR)

    if random.random() < 0.65:
        # Misto: 1 válido + 1 inválido
        prod = random.choice(cardapio)
        qtd, qtd_txt = sortear_quantidade()
        apelido = sortear_apelido(prod)
        fala = f"{verbo} {qtd_txt} {apelido} e também me vê um {invalido}"
        itens_validos = [{"produto_id": prod["id"], "nome": prod["nome"], "quantidade": qtd}]
    else:
        # Apenas inválido
        fala = f"{verbo} uma porção de {invalido} por favor"
        itens_validos = []

    saida = {
        "intencao": "ADICIONAR_ITEM",
        "confianca": round(random.uniform(0.85, 0.95), 2),
        "itens": itens_validos,
        "itens_invalidos": [invalido],
    }
    return fala, saida


def gerar_exemplo_remover(cardapio: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    prod = random.choice(cardapio)
    qtd, qtd_txt = sortear_quantidade()
    verbo = random.choice(VERBOS_REMOVER)
    apelido = sortear_apelido(prod)

    if qtd == 1:
        fala = f"{verbo} o {apelido} do meu pedido por favor"
    else:
        fala = f"{verbo} {qtd_txt} {apelido} da comanda"

    saida = {
        "intencao": "REMOVER_ITEM",
        "confianca": round(random.uniform(0.92, 0.99), 2),
        "itens": [
            {
                "produto_id": prod["id"],
                "nome": prod["nome"],
                "quantidade": qtd,
            }
        ],
        "itens_invalidos": [],
    }
    return fala, saida


def gerar_exemplo_intencao_fixa(
    intencoes: List[Dict[str, Any]], cardapio: List[Dict[str, Any]], nome_intencao: str
) -> Tuple[str, Dict[str, Any]]:
    catalogo_map = {i["nome"]: i.get("exemplos", []) for i in intencoes}
    exemplos_base = list(catalogo_map.get(nome_intencao, []))

    extras = {
        "CONFIRMAR_PEDIDO": [
            "Pode confirmar meu pedido",
            "É só isso mesmo, pode fechar e mandar pra cozinha",
            "Tudo certo, confirmo o pedido",
            "Pode finalizar a compra",
            "Fechou, é isso aí mesmo",
        ],
        "CANCELAR_PEDIDO": [
            "Cancela tudo por favor, vou desistir",
            "Pode limpar o carrinho inteiro",
            "Quero cancelar meu pedido todo",
            "Zera a comanda que eu não vou mais pedir",
        ],
        "CONSULTAR_CARDAPIO": [
            f"Quanto tá custando o {random.choice(cardapio)['nome']}?",
            f"Vocês ainda têm {random.choice(cardapio)['nome']} disponível?",
            "Quais são as opções de bebida que vocês têm?",
            "Tem alguma opção sem açúcar ou vegetariana no cardápio?",
        ],
        "CHAMAR_ATENDIMENTO": [
            "Chama um atendente aqui na mesa por favor",
            "Ô garçom, pode vir aqui me ajudar rapidinho?",
            "Preciso falar com um funcionário",
            "Alguém pode me atender aqui no totem?",
        ],
        "PEDIR_CONTA": [
            "Pode trazer a conta pra gente pagar",
            "Fecha a conta da mesa por favor",
            "Quero pagar, me traz a maquininha",
            "Quanto deu a nossa conta?",
        ],
    }

    pool = exemplos_base + extras.get(nome_intencao, [])
    fala = random.choice(pool)

    itens_consulta = []
    if nome_intencao == "CONSULTAR_CARDAPIO":
        for p in cardapio:
            if p["nome"].lower() in fala.lower():
                itens_consulta.append({"produto_id": p["id"], "nome": p["nome"], "quantidade": 1})
                break

    saida = {
        "intencao": nome_intencao,
        "confianca": round(random.uniform(0.93, 0.99), 2),
        "itens": itens_consulta,
        "itens_invalidos": [],
    }
    return fala, saida


def gerar_exemplo_desconhecido() -> Tuple[str, Dict[str, Any]]:
    fala = random.choice(FALAS_FORA_CONTEXTO_E_DUVIDA)
    saida = {
        "intencao": "DESCONHECIDO",
        "confianca": round(random.uniform(0.85, 0.98), 2),
        "itens": [],
        "itens_invalidos": [],
    }
    return fala, saida


def construir_dataset(
    total_exemplos: int, incluir_cardapio: bool = True, seed: int = 42
) -> List[Dict[str, Any]]:
    random.seed(seed)
    cardapio, intencoes = carregar_dados()
    system_prompt = montar_instrucao_sistema(cardapio, incluir_cardapio=incluir_cardapio)

    dataset = []
    vistos = set()

    tentativas = 0
    max_tentativas = total_exemplos * 5

    while len(dataset) < total_exemplos and tentativas < max_tentativas:
        tentativas += 1
        sorteio = random.random()

        if sorteio < 0.30:
            fala, saida = gerar_exemplo_adicionar_simples(cardapio)
        elif sorteio < 0.50:
            fala, saida = gerar_exemplo_adicionar_multiplo(cardapio)
        elif sorteio < 0.60:
            fala, saida = gerar_exemplo_autocorrecao(cardapio)
        elif sorteio < 0.70:
            fala, saida = gerar_exemplo_pedido_misto_invalido(cardapio)
        elif sorteio < 0.80:
            fala, saida = gerar_exemplo_remover(cardapio)
        elif sorteio < 0.93:
            intencao_escolhida = random.choice(
                [
                    "CONFIRMAR_PEDIDO",
                    "CANCELAR_PEDIDO",
                    "CONSULTAR_CARDAPIO",
                    "CHAMAR_ATENDIMENTO",
                    "PEDIR_CONTA",
                ]
            )
            fala, saida = gerar_exemplo_intencao_fixa(intencoes, cardapio, intencao_escolhida)
        else:
            fala, saida = gerar_exemplo_desconhecido()

        # Se repetiu fala exata e ainda temos margem, adiciona variação leve
        if fala in vistos and random.random() < 0.7:
            fala = f"{fala}!" if not fala.endswith("?") else fala
        vistos.add(fala)

        saida_json_str = json.dumps(saida, ensure_ascii=False)

        registro = {
            "intencao_label": saida["intencao"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'FALA DO CLIENTE:\n"{fala}"\n\nRESPOSTA JSON:'},
                {"role": "assistant", "content": saida_json_str},
            ],
            "instruction": system_prompt,
            "input": fala,
            "output": saida_json_str,
        }
        dataset.append(registro)

    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera dataset sintético JSONL para Fine-Tuning LoRA do NLU (A7)."
    )
    parser.add_argument(
        "--total",
        type=int,
        default=600,
        help="Quantidade total de exemplos a serem gerados (padrão: 600)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Caminho de saída do arquivo .jsonl",
    )
    parser.add_argument(
        "--sem-cardapio-no-prompt",
        action="store_true",
        help="Gera prompts enxutos sem listar o cardápio no system prompt",
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed aleatória para reprodutibilidade")
    args = parser.parse_args()

    incluir_cardapio = not args.sem_cardapio_no_prompt
    dataset = construir_dataset(
        total_exemplos=args.total, incluir_cardapio=incluir_cardapio, seed=args.seed
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    contagem = Counter(item["intencao_label"] for item in dataset)

    print("==================================================================")
    print("   ✅ Dataset para Fine-Tuning (LoRA) Gerado com Sucesso!")
    print("==================================================================")
    print(f"Arquivo salvo em: {out_path}")
    print(f"Total de exemplos: {len(dataset)}")
    print("\nDistribuição por Intenção:")
    for intencao, qtd in sorted(contagem.items(), key=lambda x: -x[1]):
        perc = (qtd / len(dataset)) * 100
        print(f"  - {intencao:<20}: {qtd:>4} exemplos ({perc:.1f}%)")
    print("\nFormatos incluídos em cada linha JSONL:")
    print("  1. ChatML / ShareGPT ('messages' -> system, user, assistant) [Padrão Unsloth/TRL]")
    print("  2. Alpaca ('instruction', 'input', 'output')")
    print("==================================================================")


if __name__ == "__main__":
    main()
