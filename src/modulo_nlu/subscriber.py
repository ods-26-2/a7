# src/modulo_nlu/subscriber.py
"""Simulação/Ingestão do evento do barramento (B3/I5)."""

import json
from typing import Dict, Any
from src.modulo_nlu.classifier import IntentClassifier

class AudioEventSubscriber:
    """
    Ingestão do Barramento (B3) recebendo eventos de transcrição do I5.
    Suporta tanto o formato simplificado:
        {"texto": str, "confianca": float, "origem": Optional[str]}
    quanto o envelope formal do I5:
        {
          "message_type": "event",
          "schema": "ods.varejo.transcricao",
          "producer": "I5",
          "payload": {
            "origem": "mic_totem_1",
            "texto_transcrito": "...",
            "confianca_geral": 0.85, ...
          }
        }
    """
    def __init__(self, classifier: IntentClassifier):
        self.classifier = classifier

    def on_message_received(self, event_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza o contrato do envelope B3/I5 e processa o texto.
        Garante que 'origem' seja propagada para a camada de jornada.
        """
        # Extrai o payload interno caso venha empacotado no envelope formal B3/I5
        payload = event_payload.get("payload", event_payload)

        # Suporta tanto 'texto_transcrito' (envelope oficial I5) quanto 'texto' (mock simplificado)
        texto_transcrito = payload.get("texto_transcrito") or payload.get("texto", "")
        
        # Suporta tanto 'confianca_geral' (oficial I5) quanto 'confianca' (mock simplificado)
        confianca = payload.get("confianca_geral")
        if confianca is None:
            confianca = payload.get("confianca", 0.0)

        # Origem (ex: 'mic_balcao_1', 'mic_mesa_02', 'mic_totem_streaming')
        origem = payload.get("origem", "default")

        # Regra de corte para baixas confianças de áudio (I5 / RF07)
        if confianca < 0.5:
            return {
                "origem": origem,
                "intencao": "INDETERMINADO",
                "texto_bruto": texto_transcrito,
                "confianca": confianca,
                "erro": "Confiança do áudio muito baixa"
            }

        # Processa e classifica a intenção via NLU
        resultado = self.classifier.classify(texto_transcrito)
        resultado["origem"] = origem
        resultado["confianca"] = confianca

        return resultado