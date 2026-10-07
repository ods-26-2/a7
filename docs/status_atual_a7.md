# Status Atual e Funcionalidades do Módulo A7 (Varejo)

Este documento consolida o estado da implementação da aplicação **A7** no contexto da disciplina **ODS 2026/2 - UFSJ (Squad VER-4)**, detalhando o que o sistema compreende a partir da entrada em texto/voz, como o carrinho de compras é manipulado e quais componentes já estão prontos.

---

## 1. Funções de Produção Entendidas a partir do Texto de Entrada

Abaixo está o detalhamento de como o texto recebido da inferência (I5/B3) é interpretado pelo motor de NLU e como ele impacta a máquina de estados do pedido:

### 1.1 O que é entendido do texto e ATUALIZA O CARRINHO hoje

A **única** função que atualmente atualiza o carrinho de compras em memória de ponta a ponta é:

#### `ADICIONAR_ITEM` (Adicionar / Acumular produtos)
* **Expressões e gatilhos aceitos:** Frases contendo termos como *"quero"*, *"me vê"*, *"me ve"*, *"vou pedir"*, *"adiciona"*, *"adicionar"*, *"traz"*, *"pede"*.
* **Extração de parâmetros (Slots):**
  * **Quantidade:** Dígitos numéricos (`"2"`, `"15"`) ou numerais por extenso de 1 a 20 (`"um"`, `"dois"`, ..., `"vinte"`). Padrão = 1 caso não especificado.
  * **Resolução do Produto:** Busca exata ou por similaridade (*Fuzzy Matching*) no cardápio mockado. Tolera erros fonéticos ou plurais simples (*"x-saladas"* $\rightarrow$ *"X-Salada"*, ID 1, R$ 22,90).
* **Comportamento na Jornada e Carrinho:**
  1. **Item novo e disponível:** Adiciona ao carrinho, calcula subtotal (`quantidade * preco_unitario`) e atualiza o total geral.
  2. **Item já existente no carrinho:** Soma à quantidade anterior, recalculando o subtotal daquele item e o total da comanda.
  3. **Item indisponível ou inexistente:** Se o item estiver esgotado no estoque (`disponibilidade == False`) ou não existir no cardápio, a máquina de estados **bloqueia a adição**, transiciona para o estado `PENDING` e emite mensagem clara de pendência para retorno ao cliente, **sem quebrar ou perder o carrinho anterior**.

**Exemplos funcionais:**
* `"quero dois x-saladas"` $\rightarrow$ Adiciona 2x X-Salada (Total: R$ 45,80).
* `"me vê uma coca cola por favor"` $\rightarrow$ Adiciona 1x Coca-Cola Lata 350ml (Total somado).
* `"adiciona mais uma batata frita padrão"` $\rightarrow$ Adiciona 1x Batata Frita Padrão ao carrinho.

---

### 1.2 O que o NLU já entende do texto, mas NÃO altera o carrinho ainda

O classificador já reconhece estas duas intenções textuais, mas a jornada ainda apenas devolve status informando que a ação não está implementada, mantendo o carrinho inalterado:

* **`CHAMAR_ATENDIMENTO`:**
  * Gatilhos: *"garçom"*, *"garcom"*, *"atendente"*, *"ajuda"*, *"chama"*, *"chamada"*.
  * Efeito no carrinho: nenhum (não altera itens).
* **`PEDIR_CONTA`:**
  * Gatilhos: *"conta"*, *"fechar"*, *"pagamento"*, *"pagar"*, *"nota"*.
  * Efeito no carrinho: nenhum (não finaliza nem limpa o carrinho ainda).

---

### 1.3 Operações de carrinho que AINDA NÃO são entendidas pelo texto

Frases com estes objetivos ainda não possuem regras de extração no NLU nem manipulações na máquina de estados:

* ❌ **Remover Item:** *"tira a coca"*, *"remove o x-salada"* (intenção `REMOVER_ITEM` ainda não mapeada).
* ❌ **Cancelar Pedido / Limpar Carrinho:** *"cancela meu pedido"*, *"limpa o carrinho"* (`CANCELAR_PEDIDO` ainda não mapeada).
* ❌ **Confirmar Pedido:** *"está certo"*, *"pode confirmar"* (`CONFIRMAR_PEDIDO` para transição para fechamento/pagamento).
* ❌ **Variações e Modificadores:** *"sem cebola"*, *"com gelo"* (o extrator ainda devolve `variacoes: []`).

---

## 2. Inventário de Classes e Métodos Implementados

A tabela abaixo descreve cada classe e função técnica disponível no código da aplicação A7:

| Módulo | Classe / Função | Tipo | Descrição | Exemplo de Chamada |
| :--- | :--- | :--- | :--- | :--- |
| **`modulo_nlu`** | [`AudioEventSubscriber.on_message_received`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_nlu/subscriber.py) | Método | Ingestão de mensagens B3/I5. Aplica filtro de confiança (< 0.5 gera `INDETERMINADO`) e encaminha para o classificador. | `subscriber.on_message_received({"texto": "quero dois x-saladas", "confianca": 0.95})` |
| **`modulo_nlu`** | [`IntentClassifier.classify`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_nlu/classifier.py) | Método | Classificação por Regex das intenções e higienização de stopwords antes de chamar o `SlotExtractor`. | `classifier.classify("quero duas x-saladas")` |
| **`modulo_nlu`** | [`SlotExtractor.extract_slots`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_nlu/slot_extractor.py) | Método | Converte texto bruto em slots estruturados: `produto_id`, `produto`, `quantidade`, `disponivel`, `variacoes`. | `slot_extractor.extract_slots("dois x-saladas")` |
| **`modulo_catalogo`** | [`CatalogoRepository.buscar_produto`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_catalogo/repository.py) | Método | Busca textual rápida por substring (ILIKE) no cardápio mockado. | `repo.buscar_produto("coca")` |
| **`modulo_catalogo`** | [`CatalogoRepository.buscar_produto_com_fuzzy`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_catalogo/repository.py) | Método | Busca tolerante a erros fonéticos ou de digitação/transcrição via `difflib.get_close_matches`. | `repo.buscar_produto_com_fuzzy("x saladas")` |
| **`modulo_catalogo`** | [`Produto.from_dict`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_catalogo/models.py) | ClassMethod | Desserializa dicionário JSON em instância do Dataclass `Produto`. | `Produto.from_dict(item_json)` |
| **`modulo_jornada`** | [`Cart.add_item`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_jornada/jornada.py) | Método | Insere novo item ou acumula a quantidade de item já existente, recalculando totais. | `cart.add_item(CartItem(1, "X-Salada", 2, 22.90))` |
| **`modulo_jornada`** | [`Cart.to_dict`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_jornada/jornada.py) | Método | Serializa a lista de itens, subtotais e o total geral do carrinho em formato dicionário/JSON. | `cart.to_dict()` |
| **`modulo_jornada`** | [`SessionManager.handle_nlu_result`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_jornada/jornada.py) | Método | Máquina de estados da sessão: valida payload NLU, bloqueia sob ambiguidade/indisponibilidade (RF07) e atualiza carrinho. | `session.handle_nlu_result(payload_nlu)` |
| **`modulo_jornada`** | [`SessionManager.state`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_jornada/jornada.py) | Atributo | Estado corrente da sessão (`SessionState.ACTIVE`, `PENDING` ou `COMPLETED`). | `session.state` |
| **`modulo_jornada`** | [`SessionManager.pending_reason`](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_jornada/jornada.py) | Atributo | Mensagem detalhando a causa do travamento/pendência (ex.: confiança baixa ou item fora de estoque). | `session.pending_reason` |
| **`main`** | [`main`](file:///home/mateus/Documentos/UFSJ/ODS/a7/main.py) | Função | Script executável de demonstração ponta a ponta: NLU + Catálogo + Jornada + Tratamento de ambiguidade. | `python main.py` |

---

## 3. Funcionalidades Operacionais Disponíveis para Uso

| Funcionalidade | Componente Responsável | Entrada | Saída / Efeito |
| :--- | :--- | :--- | :--- |
| **Iniciar Sessão de Pedido** | `SessionManager()` | Instanciação do objeto | Sessão iniciada com carrinho vazio e estado `ACTIVE`. |
| **Adicionar / Acumular Item** | `SessionManager.handle_nlu_result()` | Payload NLU com intenção `ADICIONAR_ITEM` e `disponivel: true` | Item registrado, total atualizado, estado `ACTIVE`. |
| **Tratamento de Indisponibilidade** | `SessionManager.handle_nlu_result()` | Payload NLU com `disponivel: false` ou `produto_id: null` | Estado muda para `PENDING`, carrinho mantido intacto, mensagem explicativa retornada. |
| **Tratamento de Baixa Confiança (RF07)** | `AudioEventSubscriber` + `SessionManager` | Evento com `confianca < 0.5` | Intenção `INDETERMINADO`, estado muda para `PENDING`, carrinho bloqueado. |
| **Consulta ao Cardápio** | `CatalogoRepository` | String de produto (ex.: *"coca"*, *"x salada"*) | Objeto `Produto` correspondente ou `None`. |
| **Consulta de Estado do Carrinho** | `session.cart.to_dict()` | Nenhuma | Dicionário com itens, quantidades, valores unitários, subtotais e total. |

---

## 4. Alinhamento com Requisitos da Disciplina ODS (Squad VER-4)

| Requisito / Diretriz | Descrição nos Requisitos | Situação Atual no Código |
| :--- | :--- | :--- |
| **RF02 (Intenções e Slots)** | Mapear sinais de voz em intenções e slots (produto, quantidade). | **Parcial:** `ADICIONAR_ITEM` 100% funcional com slots; faltam `REMOVER_ITEM`, `CONFIRMAR` e variações dinâmicas. |
| **RF03 (Consulta de Catálogo)** | Validar slots extraídos contra catálogo/cardápio de produtos ativo. | **Concluído:** `CatalogoRepository` valida dados via JSON em disco com busca exata e fuzzy. |
| **RF04 (Gestão de Sessão)** | Manter estado da sessão do cliente (carrinho, totalização). | **Concluído para adição:** Carrinho em memória calcula subtotais e totais no `SessionManager`. |
| **RF07 (Dúvida Explícita / Ambiguidade)** | Confiança baixa ou item inválido não executa ação silenciosa; marca como incerto/pendente. | **Concluído:** Filtro de corte (< 0.5) e bloqueio por estoque direcionam sessão para `PENDING`. |
| **RF08 (Não-Cobrança por Gesto Isolado)** | Cobrança/fechamento não pode ser disparada apenas por gesto corporal. | **Respeitado:** Intenção `PEDIR_CONTA` ainda não executa cobrança automática. |
| **RNF01 (Hardware Jetson)** | Execução 100% em CPU leve, preservando GPU para P2/I4/I5. | **Concluído:** Executado puramente em Python padrão (regex, difflib, dataclasses), sem uso de GPU. |
| **RNF02 (Latência < 200 ms)** | Resposta da regra de negócio inferior a 200 ms. | **Concluído:** Suíte completa de testes executa em ~30 ms no ambiente local. |

---

## 5. Como Executar e Validar

No diretório do projeto `a7`:

```bash
# Ativar o ambiente virtual
source .venv/bin/activate

# Executar a demonstração ponta a ponta
python main.py

# Executar a suíte de testes automatizados
pytest tests/
```

