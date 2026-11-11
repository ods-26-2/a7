# ODS A7 — Gerenciador de Pedidos por Voz e Gestos para Varejo
> **Oficina de Desenvolvimento de Software (ODS 2026/2) — UFSJ**  
> **Squad:** VER-4 (Varejo)  
> **Liderança:** Mateus de Oliveira Brito  
> **Equipe:** Mateus de Oliveira Brito, Ester Maria de Souza, Rafael Andrade Blom Gurgel  
> **Componente:** `ods-a7-voice-order-management` (Camada 4 — Aplicação)

---

## 1. Visão Geral

O componente **A7** é a aplicação de varejo responsável por gerenciar toda a jornada de pedidos do cliente por voz em totens e balcões de autoatendimento. Ele integra a inteligência das camadas inferiores com o catálogo de produtos e a regra de negócio do estabelecimento.

O sistema é dividido em 4 módulos arquiteturais:
* **Módulo 1 — NLU & Fusão Multimodal:** Ingestão de transcrições de voz (I5), classificação de intenções, extração de slots/quantidades e tratamento de ambiguidade.
* **Módulo 2 — Catálogo & Cardápio:** Base de produtos local com busca aproximada (*fuzzy matching*) e validação de disponibilidade e variações.
* **Módulo 3 — Gestor de Jornada e Pedido:** Máquina de estados da sessão do cliente (carrinho, modificadores, cálculo de totais, cancelamento e publicação de métricas para S5).
* **Módulo 4 — Backend FastAPI & Frontend B6 (Lexie):** API REST e WebSocket de baixa latência conectando o terminal de atendimento do cliente (`/`), painel de controle do operador/gestor (`/gestor`) e métricas operacionais (`/metricas`).

---

## 2. Pré-requisitos na Jetson

No terminal da Jetson (Ubuntu 20.04 / 22.04 LTS — JetPack 5.x / 6.x), instale as dependências de sistema necessárias:

```bash
sudo apt-get update && sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    librdkafka-dev \
    build-essential
```

> [!NOTE]
> O pacote `librdkafka-dev` e `build-essential` são essenciais na arquitetura ARM64 (aarch64) da Jetson para permitir que o cliente Kafka (`confluent-kafka`) se comunique com alto desempenho e sem bloqueios de I/O.

---

## 4. Instalação Passo a Passo

### Passo 1: Clonar o Repositório
No terminal da Jetson, clone o repositório do projeto:

```bash
git clone git@github.com:ods-26-2/ods-a7-voice-order-management.git
# ou via HTTPS:
# git clone https://github.com/ods-26-2/ods-a7-voice-order-management.git

cd ods-a7-voice-order-management
```

*(Se estiver utilizando a estrutura unificada de repositórios do squad, entre na pasta do A7 com `cd ODS/a7`).*

### Passo 2: Criar e Ativar o Ambiente Virtual
Isole o ambiente de execução Python (RNF04):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Passo 3: Instalar as Dependências Python
Atualize o gerenciador de pacotes e instale as bibliotecas requeridas:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Configuração do Kafka (`config/slm_config.yaml`)

O arquivo [`config/slm_config.yaml`](config/slm_config.yaml) centraliza a conectividade e regras de NLU.

Abra o arquivo para ajustar o IP do broker Kafka da sua bancada/laboratório:

```yaml
kafka:
  habilitado: true
  bootstrap_servers: 34.66.235.91:9093     # Altere para o IP do seu Kafka (ex: 172.18.X.X:9092)
  topic_input: ods.i5.transcript           # Tópico onde o I5 publica as transcrições
  group_id: a7-varejo-nlu
  auto_offset_reset: latest
  poll_timeout_s: 1.0
  enable_auto_commit: true
  s5:
    habilitado: true
    bootstrap_servers: 34.66.235.91:9093   # Broker do barramento S5
    topic_input: ods.s5.event.metrics
    group_id: a7-admin-s5
    auto_offset_reset: earliest
```

### Modos de Execução do Kafka:
1. **Modo Integrado (Padrão):** O A7 consome eventos do I5 via Kafka em tempo real (`KAFKA_ENABLED=1`).
2. **Modo Standalone / Offline (Sem Kafka):** Caso queira testar apenas a interface e a lógica de pedidos sem o barramento Kafka ativo, basta desativar na variável de ambiente:
   ```bash
   KAFKA_ENABLED=0 ./start_server.sh
   ```

---

## 6. Configuração do LLaMA e Fine-Tuning de NLU (SLM Local)

O A7 utiliza um **Small Language Model (SLM)** local para entender as intenções do cliente com tolerância a erros fonéticos do Whisper, variações de gírias e autocorreções, retornando dados estruturados via JSON Schema (*Structured Outputs*).

O sistema suporta 4 perfis declarativos:
* **`llama3.2_finetuned` (Recomendado / Padrão):** Llama-3.2 1B com ajuste fino (LoRA) para comandos de varejo e produtos do cardápio (baixa latência e consumo de apenas ~1.3 GB de RAM).
* **`llama3.2_ollama`:** Llama-3.2 1B base oficial do Ollama com *few-shot prompting*.
* **`bonsai2_27b`:** Ternary Bonsai 2 27B via `llama-server` (llama.cpp).
* **`regex_fast`:** Motor de fallback determinístico instantâneo (< 2 ms) caso o servidor de IA esteja desligado.

---

### 6.1. Instalação do Ollama (Linux / Jetson)

Caso ainda não possua o Ollama instalado no sistema:

```bash
# 1. Instalar o Ollama nativo
curl -fsSL https://ollama.com/install.sh | sh

# 2. Iniciar o serviço em background (se não iniciado automaticamente pelo systemd)
ollama serve &
```

---

### 6.2. Usar o LLaMA 3.2 Fine-Tuned já Pronto (`llama3.2-varejo`)

O repositório já inclui o modelo quantizado em GGUF 4-bit (`Llama-3.2-1B-Instruct.Q4_K_M.gguf`) e o `Modelfile` prontos para uso em `models/nlu_varejo_gguf/`.

Para registrar o modelo treinado no seu Ollama local:

```bash
cd models/nlu_varejo_gguf
ollama create llama3.2-varejo -f Modelfile
cd ../..
```

**Validar o modelo registrado:**
```bash
ollama run llama3.2-varejo "Quero dois x-bacon e um suco de laranja"
```
*O modelo responderá diretamente com o JSON estruturado contendo intenção, itens e confiança.*

---

### 6.3. Usar o LLaMA 3.2 1B Base Oficial (Sem Fine-Tuning)

Se preferir usar o modelo base sem adaptadores:

```bash
ollama pull llama3.2:1b
```

---

### 6.4. Como Treinar um Novo Fine-Tuning do Zero (Pipeline LoRA / Unsloth)

Se você alterar os produtos de [`data/cardapio_mock.json`](data/cardapio_mock.json) ou as intenções e quiser retreinar o modelo:

#### Passo A: Gerar o Dataset Sintético de Varejo
O script gera centenas de diálogos sintéticos variados (erros de pronúncia do Whisper, hesitações, gírias e pedidos combinados):

```bash
python3 scripts/gerar_dataset_lora.py --total 800 --output data/dataset_lora_nlu.jsonl
```

#### Passo B: Treinar com QLoRA 4-bit via Unsloth
O treinamento pode ser executado localmente (GPU com >= 4 GB VRAM) ou gratuitamente no Google Colab (GPU T4 — leva ~6 minutos):

```bash
python3 scripts/treinar_lora_unsloth.py \
    --dataset data/dataset_lora_nlu.jsonl \
    --base-model unsloth/Llama-3.2-1B-Instruct-bnb-4bit \
    --epochs 3
```
*O script salva os adaptadores LoRA e exporta automaticamente o modelo quantizado `Llama-3.2-1B-Instruct.Q4_K_M.gguf`.*

#### Passo C: Importar o Novo GGUF no Ollama
Substitua o arquivo em `models/nlu_varejo_gguf/` e recrie o modelo:
```bash
ollama create llama3.2-varejo -f models/nlu_varejo_gguf/Modelfile
```

---

### 6.5. Alternar o Modelo Ativo no A7

Você pode trocar de modelo a qualquer momento de 3 formas:

1. **Via Script Interativo (com teste de status de cada servidor):**
   ```bash
   python3 scripts/trocar_modelo.py
   ```
2. **Direto na Linha de Comando ao Iniciar o Servidor:**
   ```bash
   python3 main.py --server --modelo llama3.2_finetuned
   # ou
   python3 main.py --server --modelo llama3.2_ollama
   # ou
   python3 main.py --server --modelo bonsai2_27b
   ```
3. **No arquivo [`config/slm_config.yaml`](config/slm_config.yaml):**
   Altere a primeira linha:
   ```yaml
   modelo_ativo: llama3.2_finetuned   # ou llama3.2_ollama, bonsai2_27b
   ```

---

## 7. Como Executar a Aplicação

Para iniciar o servidor FastAPI, WebSocket e os consumidores em background, execute o script de inicialização:

```bash
chmod +x start_server.sh
./start_server.sh
```

*(Alternativamente, você pode executar diretamente: `python3 main.py --server --port 8000`).*

### Interfaces Disponíveis no Navegador:

Uma vez iniciado, você pode acessar as interfaces localmente na Jetson ou de qualquer computador na mesma rede (`http://<ip-da-jetson>:8000`):

| Rota | Descrição |
| :--- | :--- |
| **`http://localhost:8000/`** | **Terminal de Autoatendimento B6 (Lexie):** Interface do cliente orientada por voz, balões de conversa, status em tempo real (*Ouvindo / Pensando*), carrinho dinâmico e Central de Ajuda & Cardápio. |
| **`http://localhost:8000/gestor`** | **Painel do Gestor de Mesas:** Visão em tempo real de todas as mesas/terminais em atendimento, status de produção, valores e itens. |
| **`http://localhost:8000/metricas`** | **Painel de Métricas S5:** Relatório operacional com gráficos de pedidos por horário, dias de pico e volume consolidado via Kafka. |
| **`http://localhost:8000/docs`** | **Swagger UI:** Documentação OpenAPI interativa de todos os endpoints REST da aplicação. |

---

## 8. Verificação, Testes e Simulação

### 8.1. Executar os Testes Automatizados
O projeto conta com suíte de testes unitários e de integração cobrindo catálogo, NLU, jornada e mensageria:

```bash
PYTHONPATH=. pytest
```
*Resultado esperado: 30 testes aprovados (`30 passed`).*

### 8.2. Checagem de Saúde do Servidor
Verifique se a API está respondendo:

```bash
curl -s http://localhost:8000/health | jq .
```
*Resposta esperada: `{"status": "ok", "modelo_ativo": "regex_fast", ...}`.*

### 8.3. Simulação de Eventos do I5 (Voz)
Para simular a chegada de comandos de voz sem precisar do pipeline completo de áudio:

```bash
# Simulação rápida via script:
python3 scripts/simular_i5_balcao.py
```
*Ou utilize os atalhos de simulação na interface web (teclas `1` a `9` e `D`).*

### 8.4. Simulação de Métricas do S5
Para alimentar o painel de métricas operacionais com dados fictícios de 7 dias via Kafka:

```bash
python3 scripts/simular_s5_metricas.py --days 7
```

---

## 9. Estrutura de Diretórios

```text
a7/
├── config/
│   └── slm_config.yaml           # Configurações declarativas de NLU, limiares e Kafka
├── data/
│   └── cardapio_mock.json        # Base de dados local de produtos, preços e variações
├── scripts/
│   ├── simular_i5_balcao.py      # Simulador de pedidos de voz locais
│   └── simular_s5_metricas.py    # Publicador de métricas mockadas do S5 no Kafka
├── src/
│   ├── modulo_backend/           # API FastAPI, WebSockets e rotas de estado
│   ├── modulo_catalogo/          # Repositório de produtos e busca aproximada (Fuzzy)
│   ├── modulo_jornada/           # Máquina de estados do carrinho e sessões de atendimento
│   ├── modulo_nlu/               # Classificador de intenções, extrator de slots e consumidor Kafka
│   └── modulo_s5/                # Consumidor de métricas operacionais S5 e agregação
├── tests/                        # Testes unitários e de integração com pytest
├── web/                          # Frontend responsivo (B6 Lexie, Gestor e Métricas)
│   ├── index.html                # Interface de atendimento ao cliente
│   ├── gestor.html               # Painel operacional de mesas do gestor
│   ├── admin.html                # Painel de métricas consolidadas S5
│   ├── styles.css                # Estilização com tema escuro sóbrio (sem neons)
│   └── app.js                    # Lógica reativa com WebSocket e animações de status
├── main.py                       # Ponto de entrada CLI e servidor
├── requirements.txt              # Dependências Python homologadas
└── start_server.sh               # Script de execução rápida para a Jetson
```
