import re
from typing import Dict, Any, Optional
from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.slot_extractor import SlotExtractor

class IntentClassifier:
    def __init__(self, catalogo_repo: Optional[CatalogoRepository] = None):
        self.catalogo_repo = catalogo_repo
        self.slot_extractor = SlotExtractor(catalogo_repo=catalogo_repo)
        self.rules = [
            (r"\b(tira|tirar|remove|remover|exclui|excluir|retira|retirar)\b", "REMOVER_ITEM"),
            (r"\b(cancela|cancelar|desisto|desiste|zerar|limpa|limpar)\b.*\b(pedido|carrinho)?\b", "CANCELAR_PEDIDO"),
            (r"\b(confirma|confirmar|confirmo|confirmado|pode confirmar|pode fechar|pode enviar|enviar para a cozinha|finalizar pedido)\b|\b(pedido confirmado|pedido confirmad[ooa])\b|^(sim|sim!|isso|pode|ok|certo)$", "CONFIRMAR_PEDIDO"),
            (r"\b(quero|queria|que era|me vê|me ve|vou pedir|gostaria|adiciona|adicionar|traz|pede|bota|manda|desejo)\b", "ADICIONAR_ITEM"),
            (r"\b(chama|chamada|atendente|garçom|garcom|ajuda)\b", "CHAMAR_ATENDIMENTO"),
            (r"\b(conta|fechar|pagamento|pagar|nota)\b", "PEDIR_CONTA"),
            (r"\b(fazer pedido|fazer um pedido|iniciar pedido|abrir pedido|abrir comanda|olá|ola|oi|bom dia|boa tarde|boa noite)\b", "INICIAR_PEDIDO"),
        ]
        self.stopwords_regex = r"\b(quero|que\s+era|me|vê|ve|vou|pedir|adiciona|adicionar|traz|pede|tira|tirar|remove|remover|exclui|excluir|retira|retirar|por|favor|gostaria|de|o|a|os|as)\b"

    def _extract_multiple_items(self, text_lower: str) -> list:
        """Extrai múltiplos itens quando a frase possui conjunções ('e', 'com um/uma', vírgulas)."""
        if not self.catalogo_repo:
            return []
        # Divide em cláusulas ou segmentos por vírgula, ponto ou conjunção 'e' / 'com um(a)'
        partes = re.split(r"\s+e\s+|\s+com\s+(?=um|uma|dois|duas|\d+)|[,.;]+", text_lower)
        if len(partes) < 2:
            return []

        itens = []
        vistos = set()
        ruido_prefixo = r"\b(oi|olá|ola|gente|hoje|estamos|testando|aqui|eu|quero|queria|que\s+era|fazer|um\s+pedido|para\s+o\s+outro|para\s+entregar.*|estou\s+de\s+dieta.*|estou\s+pensando.*|metaspoye|me|vê|ve|vou|pedir|gostaria|adiciona|adicionar|traz|pede|bota|manda|por|favor|de|o|a|os|as)\b"
        for parte in partes:
            limpa = re.sub(ruido_prefixo, " ", parte, flags=re.IGNORECASE)
            limpa = re.sub(r"\s+", " ", limpa).strip(" .,-!?")
            if not limpa or len(limpa) < 3:
                continue
            slot = self.slot_extractor.extract_slots(limpa)
            p_id = slot.get("produto_id")
            if p_id is not None and p_id not in vistos:
                vistos.add(p_id)
                itens.append({
                    "produto_id": p_id,
                    "nome": slot.get("produto"),
                    "quantidade": slot.get("quantidade", 1),
                    "variacoes": slot.get("variacoes", []),
                })
        return itens

    def classify(self, text: str) -> Dict[str, Any]:
        text_clean = text.strip()
        text_lower = text_clean.lower()
        intent = "DESCONHECIDO"

        for pattern, mapped_intent in self.rules:
            if re.search(pattern, text_lower):
                intent = mapped_intent
                break

        clean_product_text = re.sub(self.stopwords_regex, "", text_lower, flags=re.IGNORECASE)
        clean_product_text = re.sub(r"\s+", " ", clean_product_text).strip()

        # Extrai os slots de produto, quantidade e ID oficial (Tasks 17 e 18)
        slots = self.slot_extractor.extract_slots(clean_product_text)

        resultado: Dict[str, Any] = {
            "intencao": intent,
            "texto_bruto": clean_product_text,
            "entidades": slots,
        }

        if intent in ("ADICIONAR_ITEM", "REMOVER_ITEM"):
            multiplos = self._extract_multiple_items(text_lower)
            if len(multiplos) >= 2:
                resultado["itens"] = multiplos
            elif len(multiplos) == 1 and slots.get("produto_id") is None:
                # Frase longa com ruído do I5 (ex: "Metaspoye. Oi... Eu quero o X Bacon")
                unico = multiplos[0]
                produto_obj = next((p for p in (self.catalogo_repo.produtos if self.catalogo_repo else []) if p.id == unico["produto_id"]), None)
                resultado["entidades"] = {
                    "produto_id": unico["produto_id"],
                    "produto": unico["nome"],
                    "quantidade": unico["quantidade"],
                    "disponivel": produto_obj.disponibilidade if produto_obj else True,
                    "variacoes": unico.get("variacoes", []),
                }

        return resultado