import os
import torch
import warnings
from datasets import load_dataset
from unsloth import FastLanguageModel
from transformers import TrainingArguments
from trl import SFTTrainer

# =====================================================================
# 1. HARDWARE & VRAM OPTIMIZATION SETTINGS
# =====================================================================
# Prevents memory fragmentation on your 8GB RTX 4060
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
warnings.filterwarnings("ignore")

# Resolve absolute paths dynamically
CURRENT_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_SCRIPT_DIR)
DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "training", "dataset.jsonl")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "models", "finetuned", "sirim_specialist_lora")

MAX_SEQ_LENGTH = 1024 
DATA_SEED = 3407

# =====================================================================
# 2. LOAD UNSTRUCTED LLA-3 BASE MODEL (4-BIT QUANTIZED)
# =====================================================================
print("📥 Loading base Llama 3 model in 4-bit configuration...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/llama-3-8b-Instruct-bnb-4bit", # Best baseline fit for 8GB VRAM
    max_seq_length=MAX_SEQ_LENGTH,
    load_in_4bit=True,
    device_map={"": 0} # Explicitly lock to GPU 0
)

# Apply Low-Rank Adaptation (LoRA) Target Matrices
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth", # Crucial for 8GB cards to save memory
    random_state=DATA_SEED,
)

# =====================================================================
# 3. PROMPT TEMPLATE MAPPER (Dual-Model Alignment)
# =====================================================================
EOS_TOKEN = tokenizer.eos_token

def process_training_row(row):
    """
    Transforms the JSONL entries into the exact prompt sequence 
    expected by the Model 1 -> Model 2 pipeline structure.
    """
    system_instruction = "Analyze this software requirement against the matched framework standard rule."
    
    # Mirroring the Model 1 + Model 2 combined input structure
    user_input = f"Req: {row['bad_requirement']}\nRule: {row['document_reference']}"
    
    # Forcing clean generation headers for easy UI column separation
    assistant_output = f"### Analysis\n{row['analysis']}\n\n### Suggested Rewrite\n{row['suggested_rewrite']}"
    
    # Formatted explicitly in Llama-3 instruction structure
    formatted_text = (
        f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_instruction}<|eot_id|>"
        f"<|start_header_id|>user<|end_header_id|>\n{user_input}<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n{assistant_output}{EOS_TOKEN}"
    )
    return {"text": formatted_text}

print("📦 Loading and processing dataset.jsonl...")
if not os.path.exists(DATASET_PATH):
    raise FileNotFoundError(f"Missing training dataset target at: {DATASET_PATH}. Run data_generator.py first!")

dataset = load_dataset("json", data_files=DATASET_PATH, split="train")
dataset = dataset.map(process_training_row, batched=False)

# =====================================================================
# 4. TRAINING ARGUMENTS (RTX 4060 VRAM Safeguarded)
# =====================================================================
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=MAX_SEQ_LENGTH,
    dataset_num_proc=2,
    packing=False, 
    args=TrainingArguments(
        per_device_train_batch_size=1,      # Drop from 2 to 1 (Safest baseline for 8GB)
        gradient_accumulation_steps=8,      # Increase from 4 to 8 (Keeps global batch size at 8)
        warmup_steps=5,
        max_steps=60,                       
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(), 
        logging_steps=1,
        optim="adamw_8bit",                 
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=DATA_SEED,
        output_dir="outputs",
    ),
)

# =====================================================================
# 5. EXECUTE AND SAVE ADAPTER WEIGHTS
# =====================================================================
print("🚀 Starting local model training lifecycle...")
trainer_stats = trainer.train()

print(f"💾 Saving fine-tuned local LoRA modules to: {OUTPUT_DIR}")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

print("✅ Fine-tuning pipeline complete! Model 2 is fully ready for local deployment.")