# ods-a7-voice-order-management

- SCRUM-16 (Catalogo):
  - Criada data class Produto (id, nome, preco, variacoes, disponibilidade).
  - Criado CatalogoRepository com carregamento de mock JSON (cardapio_mock.json).
  - Implementada busca textual basica (ILIKE/substring).

- SCRUM-17 (NLU-1 Ingestao e Intencao):
  - Criado AudioEventSubscriber para receber payload do barramento B3/I5.
  - Implementado filtro de confianca de audio (< 0.5 descarta/indetermina).
  - Criado IntentClassifier com parser Regex para acoes (ADICIONAR_ITEM, CHAMAR_ATENDIMENTO, PEDIR_CONTA).
  - Adicionada higienizacao de stopwords/verbos de ligacao no texto bruto.

Para executar a demonstração visual individual das operações:
`python scripts/teste_card_operacoes.py`

- API FastAPI do terminal de operação & Interface Visual Lexie (UI/UX B6):
  - Interface de balcão/totem 100% orientada a voz e resposta em texto servida em `http://localhost:8000/` (`web/index.html`, `web/styles.css`, `web/app.js`).
  - Endpoints REST de cardápio, carrinho, confirmação (`/sessoes/{origem}/confirmar`), edição (`/sessoes/{origem}/editar`), listagem/reset/cancelamento de sessões e ingestão de eventos do I5 (`/eventos/voz`, `/api/i5/reproduzir`).
  - WebSocket em `/ws/sessao` para atualizar o DOM reativamente em tempo real e monitorar automaticamente novos arquivos JSON gerados pelo I5.
  - Execução local: `uvicorn src.modulo_backend.api:app --reload`.
  - Simulação de transcrições do I5 em tempo real: `python3 scripts/simular_i5_balcao.py` (ou atalhos de teclado `1` a `9` e `D`/`F2` na interface).

- SCRUM-18 (NLU-2 Extração de Slots e NER):
  - Criado SlotExtractor com suporte a conversao de numerais (digitos e extenso ate 20).
  - Adicionada trava de seguranca de quantidade maxima por item (limite 20).
  - Implementado algoritmo de similaridade textual (Fuzzy Matching/get_close_matches) no CatalogoRepository.
  - Integrada resolucao de entidade vinculando o produto_id oficial e disponibilidade do item nos slots retornado.

- Testes & Integracao:
  - Adicionados testes unitarios e de integracao em tests/test_catalogo.py e tests/test_nlu.py.
  - Atualizado requirements.txt e ajustada configuracao de sys.path para o pytest.