#!/usr/bin/env bash
# ==============================================================================
# Inicia o Servidor A7 (Backend FastAPI + Frontend Lexie B6 + Consumidor Kafka)
# ==============================================================================

set -e

# Garante que estamos na raiz do projeto A7
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Ativa o ambiente virtual se existir
if [ -d ".venv" ]; then
    PYTHON_EXEC=".venv/bin/python3"
elif [ -d "venv" ]; then
    PYTHON_EXEC="venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

# 2. Habilita o Kafka por padrão
export KAFKA_ENABLED=1

echo "=================================================="
echo "Iniciando Servidor A7 (Varejo & Terminal B6)"
echo "Kafka B2  : ATIVADO (ods.i5.transcript)"
echo "Frontend  : http://localhost:8000/"
echo "Gestor    : http://localhost:8000/gestor"
echo "Métricas  : http://localhost:8000/metricas"
echo "=================================================="

# 3. Executa o servidor via python
exec $PYTHON_EXEC main.py --server --port 8000
