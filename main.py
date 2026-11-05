import argparse
import glob
import json
from pathlib import Path
from src.modulo_catalogo.repository import CatalogoRepository
from src.modulo_nlu.slm_classifier import SLMIntentClassifier
from src.modulo_nlu.subscriber import AudioEventSubscriber
from src.modulo_jornada.jornada import SessionManager

def main():
    parser = argparse.ArgumentParser(description="Módulo A7 (Varejo) - Execução, Kafka B2 e Testes SLM")
    parser.add_argument(
        "--modelo", "--model", "-m",
        dest="modelo",
        default=None,
        help="Perfil do modelo SLM a ser utilizado (ex: llama3.2_ollama, bonsai2_27b, llama3.2_finetuned)"
    )
    parser.add_argument(
        "--kafka",
        action="store_true",
        help="Inicia o consumidor Kafka em tempo real escutando o tópico ods.i5.transcript (I5 -> A7)"
    )
    parser.add_argument(
        "--kafka-broker",
        default=None,
        help="Endereço do broker Kafka (sobrescreve config/slm_config.yaml)"
    )
    parser.add_argument(
        "--kafka-topic",
        default=None,
        help="Tópico Kafka a ser escutado (padrão: ods.i5.transcript)"
    )
    parser.add_argument(
        "--kafka-group",
        default=None,
        help="Consumer Group ID do A7 no Kafka (padrão: a7-varejo-nlu)"
    )
    parser.add_argument(
        "--offset",
        choices=["latest", "earliest"],
        default="latest",
        help="Posição de início de leitura no Kafka: 'latest' (apenas novas mensagens) ou 'earliest' (desde o início do tópico)"
    )
    args = parser.parse_args()

    print("==================================================")
    print("--- Inicializando Módulo A7 (Varejo) ---")
    print("==================================================")
    
    # 1. Instancia Catálogo e NLU com SLM (configurado via YAML declarativo)
    catalogo = CatalogoRepository(json_path="data/cardapio_mock.json")
    classifier = SLMIntentClassifier(
        config_path="config/slm_config.yaml",
        catalogo_repo=catalogo,
        perfil=args.modelo
    )
    print(f"-> Perfil Ativo: {classifier.perfil_ativo} (Modelo: {classifier.model_name} | Provedor: {classifier.provedor})")
    subscriber = AudioEventSubscriber(classifier)

    # 2. Instancia o Orquestrador de Múltiplas Sessões (Jornada)
    session_manager = SessionManager(catalogo_repo=catalogo)

    # 3. Modo KAFKA B2: escuta contínua em tempo real do I5 (ods.i5.transcript)
    if args.kafka:
        from src.modulo_nlu.kafka_consumer import TranscriptKafkaConsumer

        consumer = TranscriptKafkaConsumer.from_config(
            subscriber=subscriber,
            session_manager=session_manager,
            config_path="config/slm_config.yaml",
            bootstrap_servers=args.kafka_broker,
            topic=args.kafka_topic,
            group_id=args.kafka_group,
            auto_offset_reset=args.offset,
        )
        print("==================================================")
        print("   [A7 - Kafka B2] Escutando Eventos do I5")
        print(f"   Broker  : {consumer.bootstrap_servers}")
        print(f"   Tópico  : {consumer.topic}")
        print(f"   Group ID: {consumer.group_id}")
        print("   (Pressione Ctrl+C para encerrar)")
        print("==================================================\n")

        def _exibir_evento_kafka(dados: dict) -> None:
            env = dados["envelope"]
            nlu_res = dados["nlu"]
            jor_res = dados["jornada"]
            origem = jor_res.get("origem", "default")
            txt = nlu_res.get("texto_transcrito", "")
            print(f"\n[{origem.upper()}] (msg_id={env.get('message_id')[:8]}...) Texto: \"{txt}\"")
            print(f"  -> NLU: Intenção={nlu_res.get('intencao')} | Confiança Áudio={nlu_res.get('confianca')} | Método={nlu_res.get('metodo')}")
            if nlu_res.get("itens"):
                print(f"  -> Itens Extraídos: {nlu_res.get('itens')}")
            if nlu_res.get("itens_invalidos"):
                print(f"  -> Itens Inválidos: {nlu_res.get('itens_invalidos')}")
            print(f"  -> Jornada [{jor_res.get('estado')}]: {jor_res.get('mensagem')}")
            carrinho = jor_res.get("carrinho")
            if carrinho and carrinho.get("itens"):
                print(f"  -> Total Comanda ({origem}): R$ {carrinho.get('total'):.2f}")

        consumer.listen_forever(on_event=_exibir_evento_kafka)
        return

    # --------------------------------------------------------------------------
    # CENÁRIO 1: Duas mesas pedindo simultaneamente (Fluxo Básico)
    # --------------------------------------------------------------------------
    print("\n--- [CENÁRIO 1: Duas mesas pedindo simultaneamente (Fluxo Básico)] ---")
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

    for idx, ev in enumerate([evento_mesa_1, evento_mesa_2], start=1):
        txt = ev["payload"]["texto_transcrito"]
        origem = ev["payload"]["origem"]
        print(f"\n[{origem.upper()}] Texto Transcrito: \"{txt}\"")
        res_nlu = subscriber.on_message_received(ev)
        res_jornada = session_manager.handle_nlu_result(res_nlu)
        print(f"  -> NLU: Intenção={res_nlu['intencao']} (Confiança: {res_nlu['confianca_nlu']}) | Método={res_nlu.get('metodo')}")
        print(f"  -> Jornada: {res_jornada['mensagem']}")

    # --------------------------------------------------------------------------
    # CENÁRIO 2: Consumindo arquivos reais gerados pelo I5 em 'jsons_gerados copy/'
    # --------------------------------------------------------------------------
    pasta_jsons = Path("jsons_gerados copy")
    if pasta_jsons.exists():
        arquivos = sorted(list(pasta_jsons.glob("*.json")))
        if arquivos:
            print(f"\n--- [CENÁRIO 2: Processando {len(arquivos)} arquivos reais gravados pelo I5] ---")
            for arquivo in arquivos:
                print(f"\n-> Arquivo: {arquivo.name}")
                with open(arquivo, "r", encoding="utf-8") as f:
                    evento_real = json.load(f)
                
                nlu_out = subscriber.on_message_received(evento_real)
                jornada_out = session_manager.handle_nlu_result(nlu_out)
                print(f"   Transcrição: \"{nlu_out.get('texto_bruto')}\"")
                print(f"   NLU: Intenção={nlu_out.get('intencao')} | Itens={nlu_out.get('itens')}")
                print(f"   Origem: {jornada_out.get('origem')} | Estado: {jornada_out.get('estado')}")
                print(f"   Ação Jornada: {jornada_out.get('mensagem')}")

    # --------------------------------------------------------------------------
    # CENÁRIO 3: Transcrições Foneticamente Degradadas, Gírias e Ruído de Fala
    # --------------------------------------------------------------------------
    print("\n--- [CENÁRIO 3: Transcrições Foneticamente Degradadas, Gírias e Ruído de Fala] ---")
    eventos_cenario_3 = [
        {
            "payload": {
                "origem": "mic_mesa_03",
                "texto_transcrito": "hum deixa eu ver... me vê um chi-bacon bem passado com uma batatinha frita e um suco de laranja natural",
                "confianca_geral": 0.88
            }
        },
        {
            "payload": {
                "origem": "mic_mesa_04",
                "texto_transcrito": "ô garçom, bota aí um xis salada sem picles e um brownie com sorvete bem caprichado",
                "confianca_geral": 0.92
            }
        }
    ]

    for ev in eventos_cenario_3:
        txt = ev["payload"]["texto_transcrito"]
        origem = ev["payload"]["origem"]
        print(f"\n[{origem.upper()}] Texto Transcrito: \"{txt}\"")
        res_nlu = subscriber.on_message_received(ev)
        res_jornada = session_manager.handle_nlu_result(res_nlu)
        print(f"  -> NLU: Intenção={res_nlu['intencao']} (Confiança: {res_nlu['confianca_nlu']}) | Método={res_nlu.get('metodo')}")
        print(f"  -> Itens Reconhecidos: {res_nlu.get('itens')}")
        print(f"  -> Ação Jornada: {res_jornada['mensagem']}")

    # --------------------------------------------------------------------------
    # CENÁRIO 4: Pedidos Mistos (Itens Válidos + Produtos Inexistentes no Cardápio)
    # --------------------------------------------------------------------------
    print("\n--- [CENÁRIO 4: Pedidos Mistos (Itens Válidos + Produtos Inexistentes no Cardápio)] ---")
    eventos_cenario_4 = [
        {
            "payload": {
                "origem": "mic_totem_01",
                "texto_transcrito": "Eu quero um X-Salada e uma Coca-Cola, e também me traz uma porção de sushi de salmão e um chopp gelado",
                "confianca_geral": 0.91
            }
        },
        {
            "payload": {
                "origem": "mic_totem_02",
                "texto_transcrito": "Me vê duas coxinhas de frango com catupiry e um pastel de queijo frito",
                "confianca_geral": 0.89
            }
        }
    ]

    for ev in eventos_cenario_4:
        txt = ev["payload"]["texto_transcrito"]
        origem = ev["payload"]["origem"]
        print(f"\n[{origem.upper()}] Texto Transcrito: \"{txt}\"")
        res_nlu = subscriber.on_message_received(ev)
        res_jornada = session_manager.handle_nlu_result(res_nlu)
        print(f"  -> NLU: Intenção={res_nlu['intencao']} (Confiança: {res_nlu['confianca_nlu']}) | Método={res_nlu.get('metodo')}")
        print(f"  -> Itens Válidos: {res_nlu.get('itens')}")
        print(f"  -> Itens Inválidos/Inexistentes: {res_nlu.get('itens_invalidos')}")
        print(f"  -> Estado da Sessão: {res_jornada['estado']}")
        print(f"  -> Ação Jornada: {res_jornada['mensagem']}")

    # --------------------------------------------------------------------------
    # CENÁRIO 5: Falas Fora de Contexto e Dúvida/Hesitação Crítica (Regra RF07)
    # --------------------------------------------------------------------------
    print("\n--- [CENÁRIO 5: Falas Fora de Contexto e Dúvida/Hesitação Crítica (Regra RF07)] ---")
    eventos_cenario_5 = [
        {
            "payload": {
                "origem": "mic_balcao_01",
                "texto_transcrito": "amigo, onde que fica o banheiro aqui do shopping?",
                "confianca_geral": 0.94
            }
        },
        {
            "payload": {
                "origem": "mic_balcao_02",
                "texto_transcrito": "não sei se peço um x-tudo ou se cancelo tudo... espera aí, deixa eu perguntar pro meu amigo antes",
                "confianca_geral": 0.85
            }
        }
    ]

    for ev in eventos_cenario_5:
        txt = ev["payload"]["texto_transcrito"]
        origem = ev["payload"]["origem"]
        print(f"\n[{origem.upper()}] Texto Transcrito: \"{txt}\"")
        res_nlu = subscriber.on_message_received(ev)
        res_jornada = session_manager.handle_nlu_result(res_nlu)
        print(f"  -> NLU: Intenção={res_nlu['intencao']} (Confiança: {res_nlu['confianca_nlu']}) | Método={res_nlu.get('metodo')}")
        print(f"  -> Itens: {res_nlu.get('itens')}")
        print(f"  -> Estado da Sessão: {res_jornada['estado']}")
        print(f"  -> Ação Jornada: {res_jornada['mensagem']}")

    # --------------------------------------------------------------------------
    # RESUMO FINAL: Comandas Ativas de todas as origens
    # --------------------------------------------------------------------------
    print("\n==================================================")
    print("--- [PAINEL DO OPERADOR: Comandas Ativas ao Final dos Testes] ---")
    print("==================================================")
    for comanda in session_manager.listar_sessoes_ativas():
        print(f"Mesa/Totem: {comanda['origem']} | Estado: {comanda['estado']} | Total: R$ {comanda['carrinho']['total']}")
        for item in comanda['carrinho']['itens']:
            print(f"  - {item['quantidade']}x {item['nome']} (R$ {item['subtotal']})")

if __name__ == "__main__":
    main()