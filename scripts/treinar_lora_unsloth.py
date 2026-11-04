#!/usr/bin/env python3
"""
Script de Fine-Tuning QLoRA (4-bit) para o Motor NLU do A7 Varejo usando Unsloth.
Treina o modelo Llama-3.2-1B-Instruct (ou Qwen2.5-1.5B-Instruct) com o dataset
`data/dataset_lora_nlu.jsonl` e exporta automaticamente para formato GGUF (Q4_K_M),
pronto para ser importado no Ollama.

Pode ser executado:
  1. No Google Colab (GPU T4 gratuita) - leva ~6 minutos.
  2. Localmente em GPU NVIDIA com >= 4GB VRAM (ex: RTX 3050 Laptop).

Instalação das dependências (no Google Colab):
  !pip install -U unsloth "trl>=0.18.2,<=1.15.0,!=0.19.0" peft accelerate bitsandbytes datasets
"""

import argparse
from pathlib import Path


def treinar(
    dataset_path: str = "data/dataset_lora_nlu.jsonl",
    base_model: str = "unsloth/Llama-3.2-1B-Instruct-bnb-4bit",
    output_dir: str = "models/nlu_varejo_lora",
    epochs: int = 3,
    batch_size: int = 2,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 1024,
    export_gguf: bool = True,
) -> None:
    try:
        # Unsloth DEVE ser importado antes de trl, transformers e peft
        import unsloth
        from unsloth import FastLanguageModel, is_bfloat16_supported
        from unsloth.chat_templates import get_chat_template
        import torch
        from datasets import load_dataset
        from trl import SFTTrainer, SFTConfig
    except ImportError as e:
        print("[ERRO] Bibliotecas de treino ausentes ou incompatíveis:", e)
        print("\nExecute no Google Colab:")
        print('  !pip install -U unsloth "trl>=0.18.2,<=1.15.0,!=0.19.0" peft accelerate bitsandbytes datasets')
        return

    print(f"==> 1. Carregando modelo base em 4-bit: {base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        dtype=None,
        load_in_4bit=True,
    )

    tokenizer = get_chat_template(
        tokenizer,
        chat_template="llama-3.1",
    )

    print("==> 2. Configurando adaptadores LoRA (Rank=16)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",  # Reduz uso de VRAM em 60% (ideal p/ 4GB VRAM)
        random_state=42,
    )

    print(f"==> 3. Carregando dataset: {dataset_path}")
    dataset = load_dataset("json", data_files=dataset_path, split="train")

    def formatar_prompts(exemplos):
        convos = exemplos["messages"]
        textos = [
            tokenizer.apply_chat_template(
                convo, tokenize=False, add_generation_prompt=False
            )
            for convo in convos
        ]
        return {"text": textos}

    dataset = dataset.map(formatar_prompts, batched=True)

    print(f"==> 4. Iniciando treinamento ({epochs} épocas, {len(dataset)} exemplos)...")
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=max_seq_length,
            dataset_num_proc=2,
            packing=False,
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=10,
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            fp16=not is_bfloat16_supported(),
            bf16=is_bfloat16_supported(),
            logging_steps=10,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=42,
            output_dir=output_dir,
            report_to="none",
        ),
    )

    trainer_stats = trainer.train()
    print(f"\n[OK] Treino concluído em {trainer_stats.metrics['train_runtime']:.1f} segundos!")

    # Salva os pesos LoRA leves (~30 MB)
    lora_path = f"{output_dir}_adapter"
    model.save_pretrained(lora_path)
    tokenizer.save_pretrained(lora_path)
    print(f"[OK] Adaptador LoRA salvo em: {lora_path}")

    # Exporta para GGUF quantizado pronto para o Ollama
    if export_gguf:
        gguf_dir = f"{output_dir}_gguf"
        print(f"==> 5. Convertendo e quantizando para GGUF (q4_k_m) em '{gguf_dir}'...")
        model.save_pretrained_gguf(
            gguf_dir,
            tokenizer,
            quantization_method="q4_k_m",
        )
        print("==================================================================")
        print("   🎉 Modelo GGUF exportado com sucesso!")
        print("==================================================================")
        print("Para registrar no seu Ollama local, execute:")
        print(f"  ollama create llama3.2-varejo -f {gguf_dir}/Modelfile")
        print("==================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Treinamento QLoRA para o NLU A7 Varejo")
    parser.add_argument("--dataset", default="data/dataset_lora_nlu.jsonl", help="Caminho do dataset JSONL")
    parser.add_argument("--epochs", type=int, default=3, help="Número de épocas de treino")
    parser.add_argument("--batch-size", type=int, default=2, help="Batch size por GPU (2 cabe em 4GB VRAM)")
    parser.add_argument("--no-gguf", action="store_true", help="Apenas salva o LoRA sem converter para GGUF")
    args = parser.parse_args()

    treinar(
        dataset_path=args.dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        export_gguf=not args.no_gguf,
    )

