#!/usr/bin/env python3
"""
Script de simulação/integração do Componente I5 enviando transcrições de voz
em tempo real para o Backend A7 (`POST /eventos/voz`), atualizando a interface
visual Lexie (UI/UX B6) via WebSocket (`/ws/sessao`) sem nenhum clique na tela.
"""

import argparse
import datetime
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def montar_envelope_i5(origem: str, texto: str, confianca: float = 0.95) -> dict:
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "message_type": "event",
        "schema": "ods.varejo.transcricao",
        "schema_version": "1.0",
        "producer": "I5",
        "published_at": agora,
        "payload": {
            "origem": origem,
            "timestamp_inicio": agora,
            "timestamp_fim": agora,
            "texto_transcrito": texto,
            "confianca_geral": confianca,
            "duvida_explicita": confianca < 0.5,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Simula o envio de transcrições de voz do I5 para a interface Lexie (A7)."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="URL base do servidor A7 (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--origem",
        default="mesa_05",
        help="Origem da sessão/comanda (default: mesa_05)",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=3.0,
        help="Segundos de pausa entre cada fala da jornada (default: 3.0s)",
    )
    parser.add_argument(
        "--texto",
        default=None,
        help="Envia uma única transcrição avulsa em vez do roteiro completo",
    )
    parser.add_argument(
        "--confianca",
        type=float,
        default=0.95,
        help="Confiança do áudio para envio avulso (default: 0.95)",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    if args.texto:
        env = montar_envelope_i5(args.origem, args.texto, args.confianca)
        res = post_json(f"{base_url}/eventos/voz", env)
        print(f"[I5 -> A7] Enviado: {args.texto!r} (conf={args.confianca})")
        print(f"[Resposta A7] Estado={res.get('estado')} | Mensagem={res.get('mensagem')}")
        return

    roteiro = [
        ("1. Abertura de pedido por voz", "Fazer pedido", 0.98),
        ("2. Adição de múltiplos itens", "Gostaria de dois X-Bacon e um suco de laranja.", 0.96),
        ("3. Adição de item com variação", "Quero um X-Salada sem cebola", 0.94),
        ("4. Dúvida explícita do I5 (Confiança < 0.5 -> Alerta PENDING)", "ruído de fundo incompreensível", 0.31),
        ("5. Item indisponível no estoque (-> Alerta PENDING)", "Quero um Vegetariano Futuro", 0.92),
        ("6. Retomada normal após alerta", "Me vê uma Coca-Cola lata", 0.95),
        ("7. Fechamento / Confirmação por voz", "Confirmar pedido", 0.98),
    ]

    print(f"=== Iniciando jornada de voz I5 -> Lexie A7 ({base_url}) ===")
    post_json(f"{base_url}/sessoes/{args.origem}/reset", {})
    time.sleep(1.0)

    for etapa, fala, conf in roteiro:
        print(f"\n-> {etapa}")
        print(f"   Voz transcrita pelo I5: \"{fala}\" (confiança: {conf})")
        env = montar_envelope_i5(args.origem, fala, conf)
        try:
            res = post_json(f"{base_url}/eventos/voz", env)
            print(f"   Estado na Interface: {res.get('estado')} | Lexie: {res.get('mensagem')}")
        except urllib.error.URLError as exc:
            print(f"   [ERRO] Servidor A7 não está rodando em {base_url}: {exc}")
            return
        time.sleep(args.intervalo)

    print("\n=== Jornada concluída! ===")


if __name__ == "__main__":
    main()

