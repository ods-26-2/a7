import json
from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber

def main():
    print("==================================================")
    print("--- Inicializando Módulo A7 (Varejo) ---")
    print("==================================================")
    
    # 1. Instancia o Catálogo (Task 16)
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")

    # 2. Instancia o NLU injetando o catálogo para resolução de IDs (Tasks 17 e 18)
    classifier = IntentClassifier(catalogo_repo=catalogo)
    subscriber = AudioEventSubscriber(classifier)

    # 3. Instancia o gerenciador de sessão (Jornada)
    from src.modulo_jornada.jornada import SessionManager
    session = SessionManager()

    # 4. Teste do Critério de Aceite da Task 18 ("quero dois x-saladas")
    evento_teste_18 = {
        "texto": "quero dois x-saladas",
        "confianca": 0.95
    }

    print(f"\n[ENTRADA SIMULADA (I5/B3)]: {evento_teste_18}")
    resultado_nlu = subscriber.on_message_received(evento_teste_18)

    print("\n[SAÍDA DO MOTOR NLU]:")
    print(json.dumps(resultado_nlu, indent=4, ensure_ascii=False))

    # 5. Processa o resultado pelo gerenciador de jornada
    resultado_jornada = session.handle_nlu_result(resultado_nlu)
    print("\n[ESTADO DA SESSÃO]:")
    print(json.dumps(resultado_jornada, indent=4, ensure_ascii=False))

    # 6. Exemplo de outro evento com baixa confiança (ambiguidade)
    evento_amb = {"texto": "blah blah", "confianca": 0.3}
    r2 = session.handle_nlu_result(subscriber.on_message_received(evento_amb))
    print("\n[EVENTO COM BAIXA CONFIANÇA]:")
    print(json.dumps(r2, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    main()