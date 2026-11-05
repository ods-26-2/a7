# src/modulo_nlu/subscriber.py
"""Simulação/Ingestão do evento do barramento (B2/B3/I5)."""

from typing import Any, Dict, Union
from src.modulo_nlu.classifier import IntentClassifier


class AudioEventSubscriber:
    """
    Ingestão do Barramento (B2/B3) recebendo eventos de transcrição do I5.
    Suporta tanto o formato simplificado:
        {"texto": str, "confianca": float, "origem": Optional[str]}
    quanto o envelope formal do I5 (ods.i5.transcript / ods.varejo.transcricao):
        {
          "message_id": "<uuid4>",
          "message_type": "event",
          "schema": "ods.i5.transcript",
          "schema_version": "1.0",
          "producer": "I5",
          "occurred_at": "2026-11-05T00:00:00Z",
          "payload": {
            "origem": "mic_totem_1",
            "texto_transcrito": "...",
            "confianca_geral": 0.85,
            "uncertain": false,
            "duvida_explicita": false
          }
        }
    """

    def __init__(self, classifier: Union[IntentClassifier, Any]):
        self.classifier = classifier

    def on_message_received(self, event_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza o contrato do envelope B2/B3/I5 e processa o texto.
        Garante que 'origem', 'message_id' e 'uncertain' sejam propagados para a camada de jornada.
        """
        # Extrai o payload interno caso venha empacotado no envelope formal B2/B3/I5
        payload = event_payload.get("payload", event_payload)
        message_id = event_payload.get("message_id") or payload.get("message_id")
        occurred_at = event_payload.get("occurred_at") or payload.get("timestamp_inicio")

        # Suporta tanto 'texto_transcrito' (envelope oficial I5) quanto 'texto' (mock simplificado)
        texto_transcrito = payload.get("texto_transcrito") or payload.get("texto", "")

        # Suporta tanto 'confianca_geral' / 'confidence' (oficial I5) quanto 'confianca' (mock simplificado)
        confianca = payload.get("confianca_geral")
        if confianca is None:
            confianca = payload.get("confidence")
        if confianca is None:
            confianca = payload.get("confianca", 0.0)

        # Origem (ex: 'mic_balcao_1', 'mic_mesa_02', 'mic_totem_streaming')
        origem = payload.get("origem", "default")
        uncertain = bool(payload.get("uncertain", False))
        duvida_explicita = bool(payload.get("duvida_explicita", False)) or uncertain

        # Regra de corte para baixas confianças de áudio ou incerteza sinalizada (I5 / RF07)
        if confianca < 0.5 or duvida_explicita:
            res_indeterminado: Dict[str, Any] = {
                "origem": origem,
                "intencao": "INDETERMINADO",
                "texto_bruto": texto_transcrito,
                "texto_transcrito": texto_transcrito,
                "confianca": confianca,
                "uncertain": True,
                "duvida_explicita": True,
                "erro": "Confiança do áudio muito baixa ou sinalizada como incerta (uncertain=True)",
            }
            if message_id:
                res_indeterminado["message_id"] = message_id
            if occurred_at:
                res_indeterminado["occurred_at"] = occurred_at
            return res_indeterminado

        # Processa e classifica a intenção via NLU
        resultado = self.classifier.classify(texto_transcrito)
        resultado["origem"] = origem
        resultado["confianca"] = confianca
        resultado["texto_transcrito"] = texto_transcrito
        resultado["uncertain"] = False
        if message_id:
            resultado["message_id"] = message_id
        if occurred_at:
            resultado["occurred_at"] = occurred_at

        return resultado