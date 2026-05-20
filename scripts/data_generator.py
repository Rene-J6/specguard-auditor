import os
import json
from typing import List
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

# ==========================================
# 1. DEFINE DATA SCHEMA (YOUR 4 COMPONENTS)
# ==========================================
class SyntheticRequirementRow(BaseModel):
    bad_requirement: str = Field(
        description="A realistic, poorly written software requirement that a human analyst might write."
    )
    document_reference: str = Field(
        description="The specific standard document violated (Industry4WRD, ISO 9001:2008, ISO/IEC 25010, ISO/IEC/IEEE 29148, or Malaysia Economy Digital Blueprint) along with the specific sub-clause/characteristic broken."
    )
    analysis: str = Field(
        description="A professional engineering evaluation explaining why the input violates that specific standard or framework."
    )
    suggested_rewrite: str = Field(
        description="The final, perfected, compliant version of the requirement that fully satisfies the standard."
    )

class SyntheticDataset(BaseModel):
    rows: List[SyntheticRequirementRow]

# ==========================================
# 2. INITIALIZE GEMINI WITH STRUCTURED OUTPUT
# ==========================================
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0.7,
    max_retries=2
) 
structured_llm = llm.with_structured_output(SyntheticDataset)

# ==========================================
# 3. CONSTRUCT THE SYSTEM PROMPT
# ==========================================
system_prompt = """
You are an expert AI data engineer specialized in Software Requirements Engineering and compliance auditing. 
Your goal is to generate high-quality synthetic training rows to train an auditor model. 

For each row, you MUST generate exactly 4 components:
1. Bad Requirement: Realistic but flawed requirement text.
2. Document Reference: Must map directly to one of these 5 frameworks:
   - Industry4WRD (National Policy on Industry 4.0 - focusing on interoperability, digitization, smart manufacturing data)
   - ISO 9001:2008 Quality management systems (focusing on process control, customer requirements, traceability)
   - ISO/IEC 25010:2011 (System and software quality models: Functional suitability, Performance efficiency, Compatibility, Usability, Reliability, Security, Maintainability, Portability)
   - ISO/IEC/IEEE 29148 (Requirements engineering standards: Characteristics of good requirements like Unambiguous, Complete, Consistent, Verifiable, Modifiable, Traceable)
   - Malaysia Economy Digital Blueprint (MyDIGITAL - focusing on local digital transformation, cloud-first strategies, cybersecurity, e-commerce integration)
3. Analysis: Professional explanation of the violation.
4. Suggested Rewrite: A clear, compliant, high-quality engineering requirement using standard phrasing (e.g., 'The system shall...').

Ensure diverse requirements covering web apps, IoT/Industry 4.0 smart factory setups, and enterprise digital solutions relevant to the Malaysian economic framework context.
"""

user_prompt = "Generate {batch_size} distinct synthetic training examples following the strict schema definitions."

prompt_template = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("user", user_prompt)
])

# ==========================================
# 4. EXECUTION AND APPEND-ONLY JSONL ROUTING
# ==========================================
def generate_requirement_dataset(batch_size: int = 5):
    print(f"Generating {batch_size} synthetic data rows using Gemini...")
    
    chain = prompt_template | structured_llm
    
    try:
        response = chain.invoke({"batch_size": batch_size})
        dataset_dicts = [row.model_dump() for row in response.rows]
        
        # Dynamically resolve paths: scripts/ -> project_root -> data/training/
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_script_dir)
        target_dir = os.path.join(project_root, "data", "training")
        
        # Ensure the directory exists
        os.makedirs(target_dir, exist_ok=True)
        
        # Targets your existing dataset.jsonl file
        filename = os.path.join(target_dir, "dataset.jsonl")
        
        # Using "a" mode (Append) so it adds lines to the bottom of the file
        with open(filename, "a", encoding="utf-8") as f:
            for row in dataset_dicts:
                f.write(json.dumps(row) + "\n")
            
        print(f"\n[SUCCESS] Successfully appended {len(dataset_dicts)} new rows to: {filename}")
        return dataset_dicts

    except Exception as e:
        print(f"[ERROR] Generation failed: {e}")
        return []

# ==========================================
# 5. RUN THE SCRIPT
# ==========================================
if __name__ == "__main__":
    # Adjust this batch size whenever you run the script to generate more records
    data = generate_requirement_dataset(batch_size=100)