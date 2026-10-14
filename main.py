import json
import glob
from pathlib import Path
from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.classifier import IntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber
from src.modulo_jornada.jornada import SessionManager

def main():
    print("==================================================")
    print("--- Inicializando Módulo A7 (Varejo) - Multi-Mesa ---")
    print("==================================================")
    
    # 1. Instancia Catálogo e NLU
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")
    classifier = IntentClassifier(catalogo_repo=catalogo)
    subscriber = AudioEventSubscriber(classifier)

    # 2. Instancia o Orquestrador de Múltiplas Sessões (Jornada)
    session_manager = SessionManager(catalogo_repo=catalogo)

    # 3. Teste 1: Simulação com múltiplas mesas manuais
    print("\n--- [CENÁRIO 1: Duas mesas pedindo simultaneamente] ---")
    evento_mesa_1 = {
        "payload": {
            "origem": "mic_mesa_01",
            "texto_transcrito": "quero dois x-saladas",
            "confianca_geral": 0.95
        }
    }
    evento_mesa_2 = {
        "payload": {
            "origem": "mic_mesa_02",
            "texto_transcrito": "me vê uma coca cola por favor",
            "confianca_geral": 0.90
        }
    }

    res_nlu_1 = subscriber.on_message_received(evento_mesa_1)
    res_jornada_1 = session_manager.handle_nlu_result(res_nlu_1)
    print(f"\n[MESA 1]: {res_jornada_1['mensagem']}")
    print(json.dumps(res_jornada_1, indent=2, ensure_ascii=False))

    res_nlu_2 = subscriber.on_message_received(evento_mesa_2)
    res_jornada_2 = session_manager.handle_nlu_result(res_nlu_2)
    print(f"\n[MESA 2]: {res_jornada_2['mensagem']}")
    print(json.dumps(res_jornada_2, indent=2, ensure_ascii=False))

    # 4. Teste 2: Consumindo arquivos reais gerados pelo I5 em 'jsons_gerados copy/'
    pasta_jsons = Path("jsons_gerados copy")
    if pasta_jsons.exists():
        arquivos = sorted(list(pasta_jsons.glob("*.json")))
        if arquivos:
            print(f"\n--- [CENÁRIO 2: Processando {len(arquivos)} arquivos reais do I5] ---")
            for arquivo in arquivos:
                print(f"\n-> Processando arquivo: {arquivo.name}")
                with open(arquivo, "r", encoding="utf-8") as f:
                    evento_real = json.load(f)
                
                nlu_out = subscriber.on_message_received(evento_real)
                jornada_out = session_manager.handle_nlu_result(nlu_out)
                print(f"   Origem: {jornada_out.get('origem')} | Estado: {jornada_out.get('estado')}")
                print(f"   Mensagem: {jornada_out.get('mensagem')}")

    # 5. Listagem final de todas as comandas ativas
    print("\n==================================================")
    print("--- [PAINEL DO OPERADOR: Comandas Ativas] ---")
    print("==================================================")
    for comanda in session_manager.listar_sessoes_ativas():
        print(f"Mesa/Totem: {comanda['origem']} | Estado: {comanda['estado']} | Total: R$ {comanda['carrinho']['total']}")
        for item in comanda['carrinho']['itens']:
            print(f"  - {item['quantidade']}x {item['nome']} (R$ {item['subtotal']})")

if __name__ == "__main__":
    main()