# Relatório de Desenvolvimento: Pipeline NLU, Structured Outputs e Fine-Tuning LoRA (A7 Varejo)

**Data:** 04 de Novembro de 2026  
**Disciplina:** Oficina de Desenvolvimento de Software (ODS) - UFSJ  
**Squad:** VER-4 (Varejo & Voz)  
**Componente:** A7 - Gerenciador de Pedidos por Voz e Gestos (`ods-a7-voice-order-management`)  
**Responsáveis:** Mateus de Oliveira Brito, Rafael Andrade Blom Gurgel, Ester Maria de Souza  

---

## 📋 Sumário Executivo

Após o recebimento do código integrado via `git pull` (commit `7a53179`), realizamos uma série de melhorias arquiteturais e de aprendizado de máquina no **Componente A7**. O objetivo principal foi transformar a inferência de linguagem natural (NLU) em um componente determinístico, resiliente a ruídos do Whisper (I5) e com latência compatível com hardware de borda (Jetson Orin/Nano e laptops com 4 GB de VRAM).

Este documento detalha todas as etapas executadas cronologicamente, desde a implementação de **Structured Outputs com JSON Schema Estrito**, passando pela arquitetura **Multi-Provedor**, até o ciclo completo de **Fine-Tuning QLoRA com Unsloth** e **calibração de inferência**.

---

## 1. Etapa 1: Structured Outputs com JSON Schema Estrito (Grammar-based Decoding)

### Contexto & Problema
Inicialmente, o modelo de linguagem (SLM) operava com prompts abertos ou retornava JSONs como texto livre. Isso abria brechas para quebras de contrato de dados, alucinações de chaves, tipos incompatíveis ou respostas com markdown (`json ... `) que falhavam no parser.

### Soluções Implementadas
1. **Geração Dinâmica de JSON Schema ([slm_classifier.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_nlu/slm_classifier.py)):**
   - Criado o método `_gerar_json_schema()`, que lê dinamicamente o arquivo [intencoes_catalogo.json](file:///home/mateus/Documentos/UFSJ/ODS/a7/data/intencoes_catalogo.json) e constrói em tempo de execução um esquema estrito:
     - `intencao`: Enum restrito às intenções canônicas cadastradas (`ADICIONAR_ITEM`, `REMOVER_ITEM`, `CONFIRMAR_PEDIDO`, `CANCELAR_PEDIDO`, `CONSULTAR_CARDAPIO`, `CHAMAR_ATENDIMENTO`, `PEDIR_CONTA`, `DESCONHECIDO`).
     - `confianca`: Número de ponto flutuante restrito ao intervalo `[0.0, 1.0]`.
     - `itens`: Lista de objetos estritos contendo `produto_id` (inteiro), `nome` (string), `quantidade` (inteiro de 1 a 20) e `variacoes` (lista de strings).
     - `itens_invalidos`: Lista de strings contendo produtos pedidos que não existem no cardápio.
2. **Integração com Mecanismos de Gramática (GBNF):**
   - Envio do schema no campo `"format": <schema_dict>` da API `/api/generate` e `/api/chat` do Ollama.
   - Suporte a fallback automático para `"format": "json"` caso uma versão legada do Ollama rejeite o schema com HTTP 400.
   - Envio no campo `"json_schema": <schema_dict>` para o `llama-server` (PrismML/Bonsai 2).
3. **Higienização e Validação Robusta:**
   - Criação de `_validar_e_sanitizar_resposta()`, garantindo clamping numérico e higienização de strings contra nulos.
4. **Suíte de Testes Unitários:**
   - Criação de [test_structured_outputs.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/tests/test_structured_outputs.py) com 6 testes específicos cobrindo geração do schema, payloads REST, sanitização e fallbacks.

---

## 2. Etapa 2: Arquitetura Multi-Provedor de Modelos (Ollama vs. PrismML Bonsai 2)

### Contexto & Problema
O projeto previa a avaliação de modelos compactos de ponta, incluindo o **Ternary Bonsai 2 27B** (modelo ternário de 1.58 bits por peso da PrismML). Era necessário permitir alternância fluida entre o Ollama local e o `llama-server` do Bonsai, respeitando o hardware local (GPU RTX 3050 Laptop com 4 GB VRAM e 7.5 GB RAM).

### Soluções Implementadas
1. **Configuração Declarativa em Perfis ([slm_config.yaml](file:///home/mateus/Documentos/UFSJ/ODS/a7/config/slm_config.yaml)):**
   - Estruturação da chave `perfis`:
     - `llama3.2_ollama`: Perfil base com Llama 3.2 1B via Ollama.
     - `bonsai2_27b`: Perfil do modelo ternário via `llama-server` na porta 8080.
     - `llama3.2_finetuned`: Perfil do modelo calibrado via LoRA (`llama3.2-varejo`).
2. **Compatibilização do Bonsai 2 para 4 GB de VRAM:**
   - O setup do Bonsai baixou o modelo `Ternary-Bonsai-2-27B-PQ2_0.gguf` (6.8 GB) e o projetor de visão `mmproj` (601 MB), causando `cudaMalloc failed: out of memory`.
   - Adicionada detecção automática do runtime CUDA do Ollama (`/usr/local/lib/ollama/cuda_v12`) nos scripts de inicialização.
   - Adicionada flag `BONSAI_NO_VISION=1` e limitação de camadas para GPU `BONSAI_NGL=10` em `start_llama_server.sh`, permitindo rodar o modelo híbrido (GPU + RAM) sem crash de CUDA.
3. **Ferramenta de Troca Rápida de Perfil:**
   - Criação do script [trocar_modelo.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/scripts/trocar_modelo.py) que testa o status de conectividade dos servidores e atualiza o YAML.
   - Adição do argumento CLI `--modelo` / `-m` em [main.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/main.py).

---

## 3. Etapa 3: Geração do Dataset Sintético para Fine-Tuning LoRA

### Contexto & Problema
Modelos genéricos de 1B parâmetros têm dificuldade para lidar com degradações fonéticas do reconhecimento de voz em português (Whisper no I5), autocorreções do cliente na mesma fala, e a regra de ouro do varejo (**Regra RF07** do projeto: dúvida explícita nunca pode ser assumida silenciosamente).

### Soluções Implementadas
1. **Script de Geração Sintética ([gerar_dataset_lora.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/scripts/gerar_dataset_lora.py)):**
   - Construção procedural de 600 exemplos de treino a partir de [cardapio_mock.json](file:///home/mateus/Documentos/UFSJ/ODS/a7/data/cardapio_mock.json) e [intencoes_catalogo.json](file:///home/mateus/Documentos/UFSJ/ODS/a7/data/intencoes_catalogo.json).
2. **Casos Cobertos no Dataset ([dataset_lora_nlu.jsonl](file:///home/mateus/Documentos/UFSJ/ODS/a7/data/dataset_lora_nlu.jsonl)):**
   - **Pedidos simples e múltiplos:** quantificadores cardinais ("1", "2") e numerais por extenso ("dois", "duas").
   - **Variações de produtos:** "sem cebola", "zero açúcar", "com bacon extra", etc.
   - **Erros fonéticos do Whisper:** "xizbeito", "chi-salada", "patata frita", "coca lata".
   - **Ruídos de conversação:** "Metaspoye... oi queria pedir...", "então o trânsito tava horrível...".
   - **Autocorreções na mesma fala:** "quero um x-salada, não pera, bota um x-bacon".
   - **Pedidos mistos:** produtos válidos combinados com itens inexistentes (populando `itens_invalidos` com "sushi de salmão", "chopp gelado", etc.).
   - **Dúvidas e falas fora de contexto:** "onde fica o banheiro?", "não sei se peço um x-tudo... deixa eu perguntar pro meu amigo" mapeando estritamente para `DESCONHECIDO`.
3. **Formatos Dual Exportados:**
   - Formato **ChatML/ShareGPT** (`messages: [system, user, assistant]`) para Unsloth/TRL.
   - Formato **Alpaca** (`instruction, input, output`) para compatibilidade universal.

---

## 4. Etapa 4: Treinamento QLoRA com Unsloth no Google Colab

### Contexto & Treinamento
Para manter o modelo extremamente leve e rápido em hardware de borda (Jetson), utilizamos o framework **Unsloth** para executar um fine-tuning QLoRA (4-bit) no modelo `unsloth/Llama-3.2-1B-Instruct-bnb-4bit`.

1. **Pipeline de Treino ([treinar_lora_unsloth.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/scripts/treinar_lora_unsloth.py)):**
   - Resolução de compatibilidade no Colab (`unsloth-zoo 2026.11.1` com `trl>=0.18.2,<=1.15.0` usando `SFTConfig`).
   - Configuração de LoRA: Rank = 16, Alpha = 16, Dropout = 0, nos módulos `q, k, v, o, gate, up, down`.
   - Gradient Checkpointing Unsloth ativado para otimização de VRAM.
2. **Métricas de Treino (GPU Tesla T4):**
   - Épocas: 3 (225 passos totais, batch size efetivo = 8).
   - Tempo de treino: **6 minutos e 24 segundos**.
   - Queda da Loss: de **2.180** no passo 10 para **0.051** no passo 220 (convergência ideal).
3. **Merge e Quantização GGUF:**
   - Fusão dos adaptadores LoRA com o modelo base em 16-bit.
   - Conversão e quantização automática para formato `Q4_K_M` via `llama.cpp`.
   - Arquivo final gerado: `Llama-3.2-1B-Instruct.Q4_K_M.gguf` (~800 MB).

---

## 5. Etapa 5: Diagnóstico, Calibração de Hiperparâmetros e Testes Finais

### O Desafio Inicial: Alucinações de Amostragem
Ao baixar o modelo quantizado e registrá-lo no Ollama local, a primeira execução do [main.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/main.py) apresentou algumas substituições estranhas (como *Onion Rings* sendo sugerido para falas como "patata frita" ou "brownie").

### Causa Raiz Identificada
1. **Temperatura Alta no Modelfile:**
   O Unsloth incluiu por padrão `PARAMETER temperature 1.5` e `PARAMETER min_p 0.1` no `Modelfile`. Uma temperatura de 1.5 induz amostragem estocástica de alta entropia (escrita criativa), gerando alucinações de IDs improváveis em tarefas de classificação determinística.
2. **Discrepância de Chat Template:**
   No Colab o modelo aprendeu a estrutura com o cardápio no bloco `<|start_header_id|>system<|end_header_id|>` e a fala no bloco `<|start_header_id|>user<|end_header_id|>`. Na primeira tentativa local, o código estava enviando um bloco de texto monolítico para `/api/generate`.

### Ajustes de Calibração Realizados
1. **Atualização do [Modelfile](file:///home/mateus/Documentos/UFSJ/ODS/a7/models/nlu_varejo_gguf/Modelfile):**
   - Configurado com `PARAMETER temperature 0.0` (decodificação puramente gulosa/determinística).
   - Removido `min_p 0.1` e simplificado o Chat Template para Llama 3.
   - Modelo recriado no Ollama: `ollama create llama3.2-varejo -f Modelfile`.
2. **Alinhamento do Prompt em [slm_classifier.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/src/modulo_nlu/slm_classifier.py):**
   - Configurado o payload do Ollama para enviar `system` e `prompt` de forma estritamente idêntica à distribuição de dados vista no treino:
     - `system`: Descrição de NLU + listagem ID/Nome do cardápio oficial.
     - `user`: `FALA DO CLIENTE: "<texto>"\n\nRESPOSTA JSON:`.
3. **Preservação da Fidelidade ao Treino:**
   - Verificou-se experimentalmente que adicionar regras textuais complexas extras no system prompt descalibrava a distribuição aprendida pelos pesos LoRA (causando falso-positivo de `DESCONHECIDO` e `PEDIR_CONTA`). A alteração foi desfeita, mantendo a simplicidade e fidelidade original do treino.

---

## 6. Resultados Validados nos Testes de Estresse

A execução final com o perfil `llama3.2_finetuned` em [main.py](file:///home/mateus/Documentos/UFSJ/ODS/a7/main.py) demonstrou os seguintes resultados práticos:

| Cenário de Teste | Entrada do Usuário / Áudio I5 | Resultado NLU Obtido | Status |
| :--- | :--- | :--- | :---: |
| **Cenário 1 (Básico)** | *"quero dois x-saladas"* | `ADICIONAR_ITEM` (Conf: 0.99) -> 2x X-Salada | ✅ Perfeito |
| **Cenário 1 (Básico)** | *"me vê uma coca cola por favor"* | `ADICIONAR_ITEM` (Conf: 0.96) -> 1x Coca-Cola Lata 350ml | ✅ Perfeito |
| **Cenário 2 (Áudio Real I5)** | *"patata frita de 30 reais... estou de dieta"* | `Batata Frita Padrão` reconhecida perfeitamente | ✅ Perfeito |
| **Cenário 2 (Áudio Real I5)** | *"Oi gente... batata frita com um x-beico e uma coca-cola..."* | `1x Batata Frita Padrão`, `1x X-Bacon`, `1x Coca-Cola Garrafa 600ml` | ✅ Perfeito |
| **Cenário 2 (Áudio Real I5)** | *"Metaspoye. Oi... Estou pensando. Eu quero o X, o X Bacon."* | Ignorou ruído e extraiu `1x X-Bacon` | ✅ Perfeito |
| **Cenário 2 (Áudio Real I5)** | *"Que era um milkshake."* | `ADICIONAR_ITEM` -> `1x Milkshake de Chocolate 400ml` | ✅ Perfeito |
| **Cenário 3 (Gírias & Fonética)** | *"chi-bacon bem passado com uma batatinha frita e um suco de laranja natural"* | **3 itens extraídos perfeitamente**: `X-Bacon`, `Batata Frita Padrão`, `Suco Natural de Laranja 500ml` | ✅ Perfeito |
| **Cenário 3 (Gírias & Fonética)** | *"xis salada sem picles e um brownie com sorvete bem caprichado"* | **2 itens extraídos perfeitamente**: `X-Salada`, `Brownie com Sorvete` | ✅ Perfeito |
| **Cenário 4 (Itens Inválidos)** | *"X-Salada, Coca-Cola... porção de sushi de salmão e um chopp gelado"* | Válidos: `X-Salada`, `Coca-Cola`. Inválidos isolados: `['sushi de salmão', 'chopp gelado']` | ✅ Perfeito |

---

## 7. Próximos Passos Recomendados

1. **Adicionar arquivos grandes no `.gitignore`:**
   - Garantir que `a7/models/*.gguf` e `a7/Bonsai-demo/` não sejam comitados acidentalmente no repositório Git.
2. **Empacotamento Container Docker (P3 / RNF04):**
   - Criar o `Dockerfile` leve da Camada 4 (A7) montando o modelo local e o servidor FastAPI.
3. **Integração Real do Barramento Kafka:**
   - Conectar o consumidor do A7 aos eventos reais publicados pelo pipeline do I5 via tópicos Kafka já padronizados.

