from unsloth import FastLanguageModel
import torch

# 1. Load the Model and the LoRA adapters you just trained
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "models/finetuned/sirim_specialist_lora", # Path to your saved model
    max_seq_length = 1024,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model) # 2x faster inference

# 2. Test Input
prompt = """### Instruction:
Audit the software requirement against Malaysian Smart Manufacturing (SIRIM) standards.

### Requirement:
The industrial robotic arm must be fast and easy to control by the factory workers.

### Audit Result:
"""

inputs = tokenizer([prompt], return_tensors = "pt").to("cuda")
outputs = model.generate(**inputs, max_new_tokens = 256)
print(tokenizer.decode(outputs[0]))