import os
import pandas as pd

def initialize():
    folders = [
        "app",
        "data/knowledge_base",
        "data/logs",
        "data/training",
        "data/temp",  # For OCR image processing
        "models/finetuned",
        "scripts"
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
    
    seed_path = "data/training/seed_data.xlsx"
    if not os.path.exists(seed_path):
        data = {
            "Bad Requirement": ["The system must be fast.", "The sensor sends data."],
            "Standard Violation": ["Ambiguity: 'fast' is not measurable.", "Incomplete: Missing frequency."],
            "Perfect Rewrite": ["The system shall process requests < 200ms.", "The sensor shall transmit data every 10s via MQTT."]
        }
        pd.DataFrame(data).to_excel(seed_path, index=False)
    print("✅ Project structure with OCR temp folders ready.")

if __name__ == "__main__":
    initialize()