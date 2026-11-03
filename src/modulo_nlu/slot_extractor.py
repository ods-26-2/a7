# Lidar com extração de slots (quantidade, produto e ID oficial) do texto limpo do NLU

import re
from typing import Dict, Any, Optional
from src.modulo_catalogo.repository import CatalogoRepository

class SlotExtractor:
    def __init__(self, catalogo_repo: Optional[CatalogoRepository] = None):
        self.catalogo_repo = catalogo_repo
        # Mapeamento de números por extenso simples
        self.numeros_extenso = {
            "um": 1, "uma": 1,
            "dois": 2, "duas": 2,
            "três": 3, "tres": 3,
            "quatro": 4, "cinco": 5,
            "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
            "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
            "quinze": 15, "dezesseis": 16, "dezesois": 16,
            "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20
        }

    def extract_slots(self, texto_bruto: str) -> Dict[str, Any]:
        """
        Extrai quantidade, nome limpo e ID oficial do produto no catálogo (Task 18).
        """
        texto = texto_bruto.strip().lower()
        quantidade = 1  # Quantidade padrão se não informada
        
        # 1. Tenta extrair quantidade numérica (ex: "2 x-saladas")
        match_num = re.search(r"\b(\d+)\b", texto)
        if match_num:
            quantidade = int(match_num.group(1))
            texto = re.sub(r"\b\d+\b", "", texto).strip()
        else:
            # 2. Tenta extrair quantidade por extenso (ex: "dois x-saladas")
            for palavra, valor in self.numeros_extenso.items():
                if re.search(rf"\b{palavra}\b", texto):
                    quantidade = valor
                    texto = re.sub(rf"\b{palavra}\b", "", texto).strip()
                    break

        # 3. Trata plural básico do produto (ex: "x-saladas" -> "x-salada")
        produto_limpo = texto.strip()
        if produto_limpo.endswith("s") and not produto_limpo.endswith("is"):
            produto_limpo = produto_limpo[:-1]

        # 4. Resolução de Entidade / Match com ID oficial do Catálogo (Task 18)
        produto_id = None
        produto_nome_oficial = produto_limpo
        disponivel = False

        variacoes = []
        if self.catalogo_repo and produto_limpo:
            produto_mapeado = None
            for produto in self.catalogo_repo.produtos:
                if produto.nome.lower() in produto_limpo:
                    produto_mapeado = produto
                    break
            if produto_mapeado is None:
                produto_mapeado = self.catalogo_repo.buscar_produto_com_fuzzy(produto_limpo)
            if produto_mapeado:
                produto_id = produto_mapeado.id
                produto_nome_oficial = produto_mapeado.nome
                disponivel = produto_mapeado.disponibilidade
                for variacao in produto_mapeado.variacoes:
                    if variacao.lower() in produto_limpo:
                        variacoes.append(variacao)

        return {
            "produto_id": produto_id,
            "produto": produto_nome_oficial,
            "quantidade": quantidade,
            "disponivel": disponivel,
            "variacoes": variacoes
        }