# Classe que lê o JSON e faz a busca textual/fuzzy

import json
import os
from difflib import get_close_matches
from typing import Optional, List
from src.modulo_catalogo.models import Produto

class CatalogoRepository:
    def __init__(self, json_path: str = "data/cardapio_mock.json"):
        self.json_path = json_path
        self.produtos: List[Produto] = []
        self._carregar_dados()

    def _carregar_dados(self):
        """Lê o arquivo JSON mockado do disco."""
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(f"Arquivo de catálogo não encontrado: {self.json_path}")
            
        with open(self.json_path, "r", encoding="utf-8") as f:
            dados = json.load(f)
            self.produtos = [Produto.from_dict(item) for item in dados]

    def buscar_produto(self, nome_busca: str) -> Optional[Produto]:
        """
        Simula consulta textual rápida por substring (estilo ILIKE).
        Retorna o primeiro produto que contiver o termo pesquisado (insensível a maiúsculas/minúsculas).
        """
        termo_limpo = nome_busca.strip().lower()
        if not termo_limpo:
            return None
            
        for produto in self.produtos:
            if termo_limpo in produto.nome.lower():
                return produto
                
        return None

    def buscar_produto_com_fuzzy(self, nome_busca: str, cutoff: float = 0.5) -> Optional[Produto]:
        """
        Atende à Task 18: Busca o produto aceitando pequenos erros de transcrição (Fuzzy Matching).
        """
        termo_limpo = nome_busca.strip().lower()
        if not termo_limpo:
            return None

        # 1. Tenta a busca por substring simples primeiro
        produto_exato = self.buscar_produto(termo_limpo)
        if produto_exato:
            return produto_exato

        # 2. Se não encontrou, aplica similaridade textual (difflib)
        mapa_nomes = {p.nome.lower(): p for p in self.produtos}
        matches = get_close_matches(termo_limpo, list(mapa_nomes.keys()), n=1, cutoff=cutoff)

        if matches:
            return mapa_nomes[matches[0]]

        # 3. Aliases fonéticos comuns do Whisper (I5) e nomes simplificados sem volume
        aliases_foneticos = {
            "suco laranja": "suco natural de laranja 500ml",
            "suco de laranja": "suco natural de laranja 500ml",
            "suco natural laranja": "suco natural de laranja 500ml",
            "x-beico": "x-bacon",
            "x beico": "x-bacon",
            "xizbeito": "x-bacon",
            "chi-bacon": "x-bacon",
            "chi bacon": "x-bacon",
            "xis bacon": "x-bacon",
            "xis salada": "x-salada",
            "chi-salada": "x-salada",
            "patata frita": "batata frita padrão",
            "batatinha frita": "batata frita padrão",
            "coca-cola": "coca-cola lata 350ml",
            "coca cola": "coca-cola lata 350ml",
            "milkshake": "milkshake de chocolate 400ml",
        }
        for chave_alias, nome_alvo in aliases_foneticos.items():
            if chave_alias in termo_limpo and nome_alvo in mapa_nomes:
                return mapa_nomes[nome_alvo]

        return None