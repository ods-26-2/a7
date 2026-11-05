#!/usr/bin/env python3
import argparse
import json
import time
import urllib.error
import urllib.request


MESAS = {
    "mesa_01": [
        {"produto_id": 1, "quantidade": 2, "variacoes": ["sem cebola"]},
        {"produto_id": 6, "quantidade": 2, "variacoes": ["Zero Açúcar"]},
    ],
    "mesa_02": [
        {"produto_id": 2, "quantidade": 1, "variacoes": ["bacon extra"]},
        {"produto_id": 11, "quantidade": 1, "variacoes": ["molho barbecue"]},
        {"produto_id": 8, "quantidade": 1, "variacoes": ["Zero"]},
    ],
    "mesa_03": [
        {"produto_id": 3, "quantidade": 1, "variacoes": ["sem milho"]},
        {"produto_id": 9, "quantidade": 2, "variacoes": ["sem açúcar"]},
        {"produto_id": 18, "quantidade": 1, "variacoes": ["sorvete de creme"]},
    ],
    "mesa_04": [
        {"produto_id": 4, "quantidade": 2, "variacoes": ["queijo cheddar"]},
        {"produto_id": 10, "quantidade": 2, "variacoes": ["sem gás"]},
    ],
    "mesa_05": [
        {"produto_id": 14, "quantidade": 1, "variacoes": ["molho mostarda e mel"]},
        {"produto_id": 15, "quantidade": 2, "variacoes": ["com chantilly"]},
    ],
}


def request_json(base_url, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8")
        raise RuntimeError(f"{method} {path}: HTTP {error.code} - {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {path}: servidor indisponível - {error.reason}") from error


def main():
    parser = argparse.ArgumentParser(
        description="Cria pedidos diferentes em mesas distintas para testar o painel administrativo."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--delay", type=float, default=0.25, help="Intervalo entre operações")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Limpa todas as mesas antes de popular",
    )
    args = parser.parse_args()

    print(f"[A7] Servidor: {args.base_url}")

    if args.reset:
        for mesa in MESAS:
            request_json(args.base_url, "POST", f"/sessoes/{mesa}/reset")
        print("[A7] Mesas reiniciadas.")

    for mesa, itens in MESAS.items():
        print(f"[A7] Criando pedido em {mesa}...")
        for item in itens:
            request_json(
                args.base_url,
                "POST",
                f"/sessoes/{mesa}/editar",
                {"acao": "adicionar", **item},
            )
            time.sleep(args.delay)

    request_json(args.base_url, "POST", "/sessoes/mesa_01/confirmar")
    request_json(args.base_url, "POST", "/sessoes/mesa_03/confirmar")
    request_json(args.base_url, "POST", "/sessoes/mesa_05/confirmar")

    print("[A7] Estados configurados:")
    print("  - mesa_01: confirmado")
    print("  - mesa_02: em produção com itens no carrinho")
    print("  - mesa_03: confirmado")
    print("  - mesa_04: em produção com itens no carrinho")
    print("  - mesa_05: confirmado")
    print(f"[A7] Admin: {args.base_url}/metricas")
    print(f"[A7] API: {args.base_url}/api/admin/dashboard")


if __name__ == "__main__":
    main()
