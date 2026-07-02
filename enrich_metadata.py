import json
import os
import time
import re
import torch
from typing import List, Dict
from pdfminer.high_level import extract_text
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig

# --- CONFIG ---
USE_BIG_MODEL = True  # Toggle to False if you run OOM or want more speed
HF_TOKEN = os.environ.get("HF_TOKEN", "")  # set via environment, do not hardcode

# Paths
INPUT_FILE = "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_registry.json"
OUTPUT_FILE = "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_enriched.json"
PDF_PATH = "/home/ubuntu/destatis-rag/backend/app/data/diw_ssp1538.pdf"
HF_CACHE_DIR = "/mnt/extra/huggingface"

# Ensure we don't fill the root partition
os.environ["HF_HOME"] = HF_CACHE_DIR
os.makedirs(HF_CACHE_DIR, exist_ok=True)

# Select Model
BIG_MODEL_ID = "meta-llama/Meta-Llama-3.1-70B-Instruct"
SMALL_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct"
MODEL_ID = BIG_MODEL_ID if USE_BIG_MODEL else SMALL_MODEL_ID

BATCH_SIZE = 10 

class LocalLLM:
    def __init__(self, model_id: str):
        print(f"Loading model {model_id} on GPU...")
        
        # Load quantization config for the 70B model
        quant_config = None
        if "70B" in model_id:
            print("Using 4-bit quantization (NF4) for 70B model.")
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_id, token=HF_TOKEN)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            token=HF_TOKEN,
            quantization_config=quant_config,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
        )

    def complete(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": "You are a professional socio-economic researcher specializing in SOEP (German Socio-Economic Panel)."},
            {"role": "user", "content": prompt},
        ]
        
        # Use the tokenizer's chat template
        prompt_with_template = self.tokenizer.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True
        )
        
        outputs = self.pipeline(
            prompt_with_template,
            max_new_tokens=600,
            do_sample=True,
            temperature=0.6,
            top_p=0.9,
            pad_token_id=self.tokenizer.eos_token_id
        )
        
        return outputs[0]["generated_text"][len(prompt_with_template):].strip()

# Global LLM instance initialized inside enrich_metadata
llm = None

def get_pdf_context(var_name: str, pdf_text: str) -> str:
    """Finds occurrences of the variable in the PDF text and returns surrounding context."""
    if not pdf_text: return ""
    
    # Search for variable name (exact word match)
    matches = list(re.finditer(rf"\b{re.escape(var_name)}\b", pdf_text, re.IGNORECASE))
    if not matches: return ""
    
    contexts = []
    # Take first 3 occurrences for context
    for match in matches[:3]:
        start = max(0, match.start() - 400)
        end = min(len(pdf_text), match.end() + 400)
        contexts.append(pdf_text[start:end].replace('\n', ' '))
    
    return "\n---\n".join(contexts)

def generate_enrichment_prompt(var: Dict, context: str) -> str:
    return f"""
Your task is to enrich the metadata for a SOEP variable to make it highly searchable in a RAG system.

RAW METADATA:
- Name: {var['variable_name']}
- Label: {var['label']}
- Dataset: {var['dataset']}
- Value Mappings: {var['value_labels']}
- Stats/Examples: {var['stats_summary']} {var['sample_values']}

CODEBOOK CONTEXT:
{context if context else "No direct match found in codebook. Use the label to infer meaning."}

Output exactly in this format:

Variable: {var['label']} ({var['variable_name']})

Description: [Detailed explanation]

Level: [Individual/Household/Other]

Use cases:
- [Analysis case 1]
- [Analysis case 2]

Related concepts: [Keywords like employment, income, health]

Source: https://paneldata.org/soep-core/datasets/{var['dataset']}/{var['variable_name']}
"""

def enrich_metadata():
    global llm
    
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        return

    print("Loading raw metadata...")
    with open(INPUT_FILE, 'r') as f:
        metadata = json.load(f)

    # Pre-extract PDF text
    pdf_text = ""
    if os.path.exists(PDF_PATH):
        print(f"Reading codebook PDF into memory (approx 10-20 MB text)...")
        try:
            pdf_text = extract_text(PDF_PATH)
            print("PDF context loaded.")
        except Exception as e:
            print(f"Failed to read PDF: {e}")

    enriched_data = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            enriched_data = json.load(f)
        print(f"Resuming from {len(enriched_data)} variables.")

    processed_names = {v['variable_name'] for v in enriched_data}
    remaining = [v for v in metadata if v['variable_name'] not in processed_names]
    
    if not remaining:
        print("All variables processed.")
        return

    if llm is None:
        llm = LocalLLM(MODEL_ID)

    print(f"Processing {len(remaining)} variables with {MODEL_ID}...")
    
    for var in remaining:
        start_time = time.time()
        msg = f"[{len(enriched_data)+1}/{len(metadata)}] Processing {var['variable_name']} ({var['label']})..."
        print(msg, flush=True)
        
        # Log to a persistent file just in case stdout is swallowed
        with open("enrichment_heartbeat.log", "a") as hbl:
            hbl.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
        
        context = get_pdf_context(var['variable_name'], pdf_text)
        prompt = generate_enrichment_prompt(var, context)
        
        try:
            response_text = llm.complete(prompt)
            var['rich_description'] = response_text
            enriched_data.append(var)
            
            elapsed = time.time() - start_time
            print(f"Done in {elapsed:.1f}s", flush=True)
        except Exception as e:
            print(f"Failed {var['variable_name']}: {e}", flush=True)
            continue
        
        if len(enriched_data) % BATCH_SIZE == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(enriched_data, f, indent=2)
            print(f"--- Backup saved: {len(enriched_data)} variables ---", flush=True)

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(enriched_data, f, indent=2)
    print("FINISHED.", flush=True)

if __name__ == "__main__":
    enrich_metadata()
