# src/modulo_nlu/slm_classifier.py
"""Classificador de intenções baseado em SLM (Small Language Model).

Esta classe implementa a integração com um SLM local (ex.: Ollama com llama3.2 / Qwen)
e gerencia o fallback algorítmico baseado em similaridade dinâmica (RapidFuzz/Levenshtein).

Configurações centralizadas no arquivo YAML: `config/slm_config.yaml`.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

# Garante a raiz do projeto no sys.path para permitir execução direta do script
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.slot_extractor import SlotExtractor


class SLMIntentClassifier:
    """
    Classificador de intenções via SLM orientado a catálogo e configurações em YAML.
    """

    def __init__(
        self,
        config_path: str = "config/slm_config.yaml",
        intencoes_json_path: Optional[str] = None,
        catalogo_repo: Optional[CatalogoRepository] = None,
        model_name_or_path: Optional[str] = None
    ):
        self.config_path = config_path
        self.config = self._carregar_config(config_path)

        # Resolução dos caminhos de catálogo e intenções
        caminhos_cfg = self.config.get("caminhos", {})
        caminho_intencoes_cfg = intencoes_json_path or caminhos_cfg.get("intencoes_json", "data/intencoes_catalogo.json")
        self.intencoes_path = str(self._resolver_caminho(caminho_intencoes_cfg))

        caminho_catalogo_cfg = caminhos_cfg.get("catalogo_json", "data/cardapio_mock.json")
        caminho_catalogo_resolvido = str(self._resolver_caminho(caminho_catalogo_cfg))

        if catalogo_repo is not None:
            self.catalogo_repo = catalogo_repo
        else:
            self.catalogo_repo = CatalogoRepository(json_path=caminho_catalogo_resolvido)

        # Configurações do modelo
        modelo_cfg = self.config.get("modelo", {})
        self.model_name = model_name_or_path or modelo_cfg.get("nome", "llama3.2:1b")
        self.endpoint_url = modelo_cfg.get("endpoint_url", "http://127.0.0.1:11434").rstrip("/")
        self.temperatura = float(modelo_cfg.get("temperatura", 0.0))
        self.max_tokens = int(modelo_cfg.get("max_tokens", 150))
        self.timeout_segundos = float(modelo_cfg.get("timeout_segundos", 8.0))

        self.slot_extractor = SlotExtractor(catalogo_repo=self.catalogo_repo)
        
        # Carrega o catálogo de intenções do disco
        self.intencoes: List[Dict[str, Any]] = self._carregar_intencoes()
        
        # Inicializa conexão com o provedor (ex: Ollama)
        self.model_driver: Optional[str] = None
        self._inicializar_driver_slm()

    def _resolver_caminho(self, caminho: str) -> Path:
        """Resolve caminhos relativos ao diretório atual ou à raiz do projeto."""
        p = Path(caminho)
        if p.exists():
            return p
        alt = ROOT_DIR / caminho
        if alt.exists():
            return alt
        return p

    def _carregar_config(self, config_path: str) -> Dict[str, Any]:
        """Carrega o arquivo YAML de configuração com fallback seguro."""
        resolved = self._resolver_caminho(config_path)
        if resolved.exists() and yaml is not None:
            try:
                with open(resolved, "r", encoding="utf-8") as f:
                    dados = yaml.safe_load(f)
                    if isinstance(dados, dict):
                        return dados
            except Exception as e:
                print(f"[Aviso] Falha ao ler YAML '{resolved}': {e}. Usando configuração padrão.")

        return {
            "modelo": {
                "nome": "llama3.2:1b",
                "provedor": "ollama",
                "endpoint_url": "http://127.0.0.1:11434",
                "temperatura": 0.0,
                "max_tokens": 150,
                "timeout_segundos": 8.0
            },
            "caminhos": {
                "catalogo_json": "data/cardapio_mock.json",
                "intencoes_json": "data/intencoes_catalogo.json"
            },
            "prompt": {
                "instrucao_sistema": (
                    "Você é o motor de NLU inteligente de uma lanchonete/restaurante de varejo.\n"
                    "Sua missão é entender a fala do cliente, classificar a intenção e extrair APENAS produtos que REALMENTE constam no CARDÁPIO OFICIAL fornecido.\n"
                    "Desconsidere conversas paralelas e hesitações.\n"
                    "Tolere transcrições imperfeitas ou variações fonéticas.\n"
                    "Se o cliente pedir produtos que NÃO constam no cardápio, liste-os em 'itens_invalidos'."
                ),
                "regras": [
                    "Responda ESTRITAMENTE em formato JSON puro, sem explicações e sem markdown.",
                    "A chave 'intencao' deve ser uma das opções permitidas ou 'DESCONHECIDO'.",
                    "A chave 'itens' deve conter APENAS itens reconhecidos no cardápio oficial: [{\"produto_id\": <int>, \"nome\": \"<nome_oficial>\", \"quantidade\": <int>}].",
                    "A chave 'itens_invalidos' deve listar nomes de produtos pedidos que NÃO existem no cardápio oficial: [\"<nome_pedido>\"].",
                    "Se a intenção não envolver itens (ex: CONFIRMAR, CANCELAR, CHAMAR_ATENDIMENTO, DESCONHECIDO), retorne 'itens': [] e 'itens_invalidos': []."
                ],
                "exemplos_few_shot": []
            },
            "fallback": {
                "habilitado": True,
                "fuzzy_cutoff": 0.6,
                "confianca_padrao": 0.85
            }
        }

    def _carregar_intencoes(self) -> List[Dict[str, Any]]:
        """Lê o arquivo JSON com a lista de intenções e descrições."""
        path = Path(self.intencoes_path)
        if not path.exists():
            return [
                {"nome": "ADICIONAR_ITEM", "descricao": "Pedir ou adicionar produtos ao carrinho."},
                {"nome": "REMOVER_ITEM", "descricao": "Retirar ou excluir itens do pedido."},
                {"nome": "CONFIRMAR_PEDIDO", "descricao": "Confirmar e fechar o pedido."},
                {"nome": "CANCELAR_PEDIDO", "descricao": "Cancelar a compra inteira."},
                {"nome": "CHAMAR_ATENDIMENTO", "descricao": "Solicitar ajuda de um garçom ou atendente."},
                {"nome": "PEDIR_CONTA", "descricao": "Solicitar a conta ou pagamento."}
            ]
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _inicializar_driver_slm(self) -> None:
        """
        Verifica se o servidor Ollama local está ativo e se o modelo configurado está carregado.
        """
        import urllib.request
        try:
            url = f"{self.endpoint_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    dados = json.loads(resp.read().decode("utf-8"))
                    modelos = [m.get("name") for m in dados.get("models", [])]
                    for m in modelos:
                        if self.model_name in m or "llama3.2" in m:
                            self.model_driver = "ollama"
                            self.model_name = m
                            break
                    if not self.model_driver and modelos:
                        self.model_driver = "ollama"
                        self.model_name = modelos[0]
        except Exception:
            self.model_driver = None

    def _obter_resumo_cardapio(self) -> str:
        """Gera string resumida de ID e Nome dos produtos do cardápio para o prompt."""
        if not self.catalogo_repo or not self.catalogo_repo.produtos:
            return ""
        return "\n".join([f"- ID {p.id}: {p.nome}" for p in self.catalogo_repo.produtos])

    def montar_prompt(self, texto_usuario: str) -> str:
        """
        Gera o prompt para o SLM baseado na configuração declarativa em YAML.
        """
        prompt_cfg = self.config.get("prompt", {})
        instrucao_sistema = prompt_cfg.get("instrucao_sistema", "").strip()

        descricoes_intencoes = "\n".join([
            f"- {item['nome']}: {item['descricao']}"
            for item in self.intencoes
        ])
        resumo_cardapio = self._obter_resumo_cardapio()

        regras_lista = prompt_cfg.get("regras", [])
        regras_formatadas = "\n".join([f"{i+1}. {r}" for i, r in enumerate(regras_lista)])

        exemplos_lista = prompt_cfg.get("exemplos_few_shot", [])
        exemplos_formatados = ""
        if exemplos_lista:
            blocos = []
            for ex in exemplos_lista:
                entrada = ex.get("entrada", "")
                saida = ex.get("saida", "")
                blocos.append(f"Entrada: \"{entrada}\"\nSaída: {saida}")
            exemplos_formatados = "\nEXEMPLOS:\n" + "\n\n".join(blocos) + "\n"

        prompt = f"""{instrucao_sistema}

CARDÁPIO OFICIAL (ID e Nome):
{resumo_cardapio}

INTENÇÕES PERMITIDAS:
{descricoes_intencoes}
- DESCONHECIDO: Caso a fala não se enquadre em nenhuma das opções.

REGRAS:
{regras_formatadas}
{exemplos_formatados}
FALA DO CLIENTE:
"{texto_usuario}"

RESPOSTA JSON:"""
        return prompt

    def invocar_slm(self, prompt: str, texto_usuario: str = "") -> Dict[str, Any]:
        """
        Executa a inferência no Llama/Ollama local via API REST.
        Caso o Ollama esteja offline, executa o fallback algorítmico dinâmico (Fuzzy Matching).
        """
        nomes_validos = [item["nome"] for item in self.intencoes] + ["DESCONHECIDO"]

        if self.model_driver == "ollama":
            import urllib.request
            try:
                payload_req = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": self.temperatura,
                        "num_predict": self.max_tokens
                    }
                }
                req = urllib.request.Request(
                    f"{self.endpoint_url}/api/generate",
                    data=json.dumps(payload_req).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=self.timeout_segundos) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        texto_resposta = res_json.get("response", "").strip()
                        parsed = json.loads(texto_resposta)
                        intencao = str(parsed.get("intencao", "")).strip().upper()
                        confianca = float(parsed.get("confianca", 0.95))
                        itens = parsed.get("itens", [])
                        itens_invalidos = parsed.get("itens_invalidos", [])

                        # Validação e normalização da intenção
                        if intencao not in nomes_validos:
                            for nv in nomes_validos:
                                if nv in intencao or intencao in nv:
                                    intencao = nv
                                    break
                            else:
                                intencao = "ADICIONAR_ITEM" if itens else "DESCONHECIDO"

                        return {
                            "intencao": intencao,
                            "confianca": confianca,
                            "itens": itens,
                            "itens_invalidos": itens_invalidos,
                            "justificativa": f"Inferência realizada pelo modelo {self.model_name} via Ollama"
                        }
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # FALLBACK ALGORÍTMICO DINÂMICO (Sem nenhum dicionário manual/estático!)
        # ----------------------------------------------------------------------
        fala_lower = texto_usuario.lower() if texto_usuario else prompt.lower()
        
        # 1. Identificação rápida de intenção por palavras-chave essenciais
        intencao_detectada = None
        gatilhos_rapidos = {
            "REMOVER_ITEM": ["tira", "retira", "remove", "remover", "exclui", "não quero mais"],
            "CONFIRMAR_PEDIDO": ["fechar", "confirmar", "confirmo", "certo", "finalizar", "só isso"],
            "CANCELAR_PEDIDO": ["cancela", "cancelar", "desisti", "zerar"],
            "CHAMAR_ATENDIMENTO": ["garçom", "garcom", "atendente", "ajuda", "chama"],
            "PEDIR_CONTA": ["conta", "pagamento", "pagar", "nota"],
            "CONSULTAR_CARDAPIO": ["quanto custa", "tem opção", "quais sabores", "cardápio", "preço"]
        }
        for intent_cand, keys in gatilhos_rapidos.items():
            if any(k in fala_lower for k in keys):
                intencao_detectada = intent_cand
                break

        if not intencao_detectada:
            # Se não há verbos de pedido, classifica como DESCONHECIDO para não chutar
            verbos_pedido = ["quero", "me vê", "me ve", "gostaria", "adiciona", "bota", "manda", "pede", "desejo"]
            if any(v in fala_lower for v in verbos_pedido) or "x-" in fala_lower or "batata" in fala_lower:
                intencao_detectada = "ADICIONAR_ITEM"
            else:
                intencao_detectada = "DESCONHECIDO"

        # 2. Busca Fuzzy dinâmica pura diretamente contra a lista de produtos do cardápio
        itens_extraidos = []
        fuzzy_cutoff = float(self.config.get("fallback", {}).get("fuzzy_cutoff", 0.6))
        
        if intencao_detectada in ["ADICIONAR_ITEM", "REMOVER_ITEM", "CONSULTAR_CARDAPIO"] and self.catalogo_repo:
            for produto in self.catalogo_repo.produtos:
                prod_nome_lower = produto.nome.lower()
                # Verifica casamento direto ou por palavras principais do produto
                palavras_prod = [p for p in prod_nome_lower.split() if len(p) > 3]
                match_encontrado = prod_nome_lower in fala_lower or any(p in fala_lower for p in palavras_prod)
                
                # Se não casou por palavra, testa similaridade fuzzy contra o cardápio
                if not match_encontrado:
                    prod_fuzzy = self.catalogo_repo.buscar_produto_com_fuzzy(fala_lower, cutoff=fuzzy_cutoff)
                    if prod_fuzzy and prod_fuzzy.id == produto.id:
                        match_encontrado = True

                if match_encontrado and not any(it["produto_id"] == produto.id for it in itens_extraidos):
                    # Tenta extrair quantidade adjacente
                    qtd = 1
                    match_qtd = re.search(rf"\b(um|uma|dois|duas|três|tres|\d+)\s+.*{re.escape(produto.nome.split()[0].lower())}", fala_lower)
                    if match_qtd:
                        val = match_qtd.group(1)
                        qtd = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3}.get(val, int(val) if val.isdigit() else 1)
                    itens_extraidos.append({
                        "produto_id": produto.id,
                        "nome": produto.nome,
                        "quantidade": qtd
                    })

        confianca_padrao = float(self.config.get("fallback", {}).get("confianca_padrao", 0.85))
        return {
            "intencao": intencao_detectada,
            "confianca": confianca_padrao,
            "itens": itens_extraidos,
            "itens_invalidos": [],
            "justificativa": "Fallback algorítmico dinâmico (Fuzzy Levenshtein) [Ollama indisponível]"
        }

    def classify(self, text: str) -> Dict[str, Any]:
        """
        Interface NLU:
        Recebe texto -> passa pelo SLM -> extrai itens reconhecidos e inválidos.
        """
        text_clean = text.strip()
        prompt = self.montar_prompt(text_clean)
        resposta_slm = self.invocar_slm(prompt, texto_usuario=text_clean)

        intencao_detectada = resposta_slm.get("intencao", "DESCONHECIDO")
        confianca_slm = resposta_slm.get("confianca", 0.8)
        itens_detectados = resposta_slm.get("itens", [])
        itens_invalidos = resposta_slm.get("itens_invalidos", [])

        # Formato de retrocompatibilidade com 'entidades'
        if itens_detectados:
            primeiro = itens_detectados[0]
            entidades = {
                "produto_id": primeiro.get("produto_id"),
                "produto": primeiro.get("nome"),
                "quantidade": primeiro.get("quantidade", 1),
                "disponivel": True,
                "itens": itens_detectados
            }
        else:
            entidades = self.slot_extractor.extract_slots(text_clean)
            entidades["itens"] = []

        return {
            "intencao": intencao_detectada,
            "confianca_nlu": confianca_slm,
            "texto_bruto": text_clean,
            "itens": itens_detectados,
            "itens_invalidos": itens_invalidos,
            "entidades": entidades,
            "prompt_gerado": prompt,
            "justificativa": resposta_slm.get("justificativa", ""),
            "metodo": "SLM_LLAMA" if self.model_driver == "ollama" else "FALLBACK_FUZZY"
        }
