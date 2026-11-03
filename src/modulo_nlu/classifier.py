import re
from typing import Dict, Any, Optional
from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.slot_extractor import SlotExtractor

class IntentClassifier:
    def __init__(self, catalogo_repo: Optional[CatalogoRepository] = None):
        self.slot_extractor = SlotExtractor(catalogo_repo=catalogo_repo)
        self.rules = [
            (r"\b(tira|tirar|remove|remover|exclui|excluir|retira|retirar)\b", "REMOVER_ITEM"),
            (r"\b(cancela|cancelar|desisto|desiste|zerar|limpa|limpar)\b.*\b(pedido|carrinho)?\b", "CANCELAR_PEDIDO"),
            (r"\b(confirma|confirmar|confirmo|confirmado|pode confirmar|pode fechar)\b|\b(pedido confirmado|pedido confirmad[ooa])\b", "CONFIRMAR_PEDIDO"),
            (r"\b(quero|que era|me vê|me ve|vou pedir|adiciona|adicionar|traz|pede)\b", "ADICIONAR_ITEM"),
            (r"\b(chama|chamada|atendente|garçom|garcom|ajuda)\b", "CHAMAR_ATENDIMENTO"),
            (r"\b(conta|fechar|pagamento|pagar|nota)\b", "PEDIR_CONTA")
        ]
        self.stopwords_regex = r"\b(quero|que\s+era|me|vê|ve|vou|pedir|adiciona|adicionar|traz|pede|tira|tirar|remove|remover|exclui|excluir|retira|retirar|por|favor|gostaria|de|o|a|os|as)\b"

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

        return {
            "intencao": intent,
            "texto_bruto": clean_product_text,
            "entidades": slots
        }