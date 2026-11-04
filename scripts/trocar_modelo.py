#!/usr/bin/env python3
"""
Utilitário para visualização, teste de status e troca rápida de modelos SLM no A7 Varejo.
Permite alternar facilmente entre o LLaMA local (via Ollama) e o Ternary Bonsai 2 (via llama-server).

Uso:
  python scripts/trocar_modelo.py                 (Modo interativo com verificação de status)
  python scripts/trocar_modelo.py bonsai2_27b     (Troca direta para o perfil informado)
  python scripts/trocar_modelo.py llama3.2_ollama (Troca direta para o LLaMA via Ollama)
"""

import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

# Garante a raiz do projeto no path
ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config" / "slm_config.yaml"

try:
    import yaml
except ImportError:
    print("[ERRO] Biblioteca PyYAML não encontrada. Instale com: pip install pyyaml")
    sys.exit(1)


def carregar_yaml(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        print(f"[ERRO] Arquivo de configuração não encontrado em: {caminho}")
        sys.exit(1)
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def salvar_yaml(caminho: Path, dados: Dict[str, Any]) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        yaml.safe_dump(dados, f, allow_unicode=True, sort_keys=False)


def verificar_status_servidor(provedor: str, endpoint_url: str) -> bool:
    """Verifica se o servidor do modelo está ativo e responsivo."""
    provedor = provedor.lower()
    endpoint = endpoint_url.rstrip("/")
    if provedor == "ollama":
        url = f"{endpoint}/api/tags"
    else:  # llama_server / openai
        url = f"{endpoint}/health"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            return resp.status in [200, 204]
    except Exception:
        if provedor != "ollama":
            try:
                url_v1 = f"{endpoint}/v1/models"
                req_v1 = urllib.request.Request(url_v1, method="GET")
                with urllib.request.urlopen(req_v1, timeout=1.2) as resp_v1:
                    return resp_v1.status == 200
            except Exception:
                return False
        return False


def obter_dica_inicializacao(perfil_chave: str, provedor: str) -> str:
    """Retorna o comando sugerido para ligar o servidor caso esteja offline."""
    if provedor == "ollama":
        return "Para iniciar: execute 'ollama serve' no terminal."
    elif "bonsai" in perfil_chave:
        return (
            "Para iniciar: abra a pasta Bonsai-demo e execute:\n"
            "   BONSAI_NGL=20 ./scripts/start_llama_server.sh"
        )
    return "Inicie o servidor local correspondente."


def aplicar_troca_modelo(config: Dict[str, Any], novo_perfil: str) -> None:
    perfis = config.get("perfis", {})
    if novo_perfil not in perfis:
        print(f"\n[ERRO] Perfil '{novo_perfil}' não encontrado. Opções válidas: {list(perfis.keys())}")
        sys.exit(1)

    config["modelo_ativo"] = novo_perfil
    # Atualiza o bloco legado 'modelo' para retrocompatibilidade
    config["modelo"] = dict(perfis[novo_perfil])
    salvar_yaml(CONFIG_PATH, config)

    dados_modelo = perfis[novo_perfil]
    print(f"\n[SUCESSO] Modelo ativo alterado para: {novo_perfil}")
    print(f"  -> Nome do Modelo: {dados_modelo.get('nome')}")
    print(f"  -> Provedor: {dados_modelo.get('provedor')}")
    print(f"  -> Endpoint: {dados_modelo.get('endpoint_url')}")
    print(f"  -> Structured Outputs: {dados_modelo.get('structured_outputs')}")


def main() -> None:
    config = carregar_yaml(CONFIG_PATH)
    perfis = config.get("perfis", {})
    ativo_atual = config.get("modelo_ativo", "llama3.2_ollama")

    if not perfis:
        print("[ERRO] Nenhum perfil encontrado na chave 'perfis' de slm_config.yaml.")
        sys.exit(1)

    # Modo argumento direto: python scripts/trocar_modelo.py <nome_perfil>
    if len(sys.argv) > 1:
        alvo = sys.argv[1].strip()
        aplicar_troca_modelo(config, alvo)
        return

    # Modo interativo
    print("==================================================================")
    print("   🔧 Gerenciador e Seletor de Modelos SLM - A7 Varejo")
    print("==================================================================")
    print(f"Arquivo de Configuração: {CONFIG_PATH.relative_to(ROOT_DIR)}\n")

    chaves_ordenadas = list(perfis.keys())
    status_map = {}

    for idx, chave in enumerate(chaves_ordenadas, start=1):
        info = perfis[chave]
        nome = info.get("nome", "desconhecido")
        provedor = info.get("provedor", "ollama")
        url = info.get("endpoint_url", "")
        ativo_badge = " [ATIVO ⭐️]" if chave == ativo_atual else ""

        online = verificar_status_servidor(provedor, url)
        status_map[chave] = online
        status_txt = "ONLINE 🟢" if online else "OFFLINE 🔴"

        print(f"[{idx}] {chave}{ativo_badge}")
        print(f"    Nome: {nome} | Provedor: {provedor}")
        print(f"    Endpoint: {url} ({status_txt})")
        if not online:
            dica = obter_dica_inicializacao(chave, provedor)
            print(f"    ℹ️  {dica}")
        print()

    print("Digite o número do perfil desejado para ativar (ou 'q' para sair): ", end="")
    try:
        escolha = input().strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperação cancelada.")
        return

    if escolha.lower() in ["q", "sair", "exit", ""]:
        print("Nenhuma alteração realizada.")
        return

    try:
        idx_escolhido = int(escolha) - 1
        if 0 <= idx_escolhido < len(chaves_ordenadas):
            selecionado = chaves_ordenadas[idx_escolhido]
            aplicar_troca_modelo(config, selecionado)
        else:
            print("[ERRO] Opção numérica inválida.")
    except ValueError:
        # Se digitou o nome direto
        if escolha in perfis:
            aplicar_troca_modelo(config, escolha)
        else:
            print(f"[ERRO] Opção inválida: '{escolha}'")


if __name__ == "__main__":
    main()

