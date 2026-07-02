import json
import os
import time
import re
import torch
from typing import Dict
from pdfminer.high_level import extract_text
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, BitsAndBytesConfig

# -----------------------------
# CONFIG
# -----------------------------

USE_BIG_MODEL = False  # Set to True only if you really want 70B
HF_TOKEN = os.environ.get("HF_TOKEN", "")  # set via environment, do not hardcode

#INPUT_FILE = "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_registry.json"
OUTPUT_FILE = "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_enriched_small.json"
PDF_PATH = "/home/ubuntu/destatis-rag/backend/app/data/diw_ssp1538.pdf"

HF_CACHE_DIR = "/mnt/extra/huggingface"
os.environ["HF_HOME"] = HF_CACHE_DIR
os.makedirs(HF_CACHE_DIR, exist_ok=True)

BIG_MODEL_ID = "meta-llama/Meta-Llama-3.1-70B-Instruct"
SMALL_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct"
MODEL_ID = BIG_MODEL_ID if USE_BIG_MODEL else SMALL_MODEL_ID

BATCH_SIZE = 5  # save every N variables
MAX_VARIABLES = 100  # LIMIT FOR PROTOTYPE

# -----------------------------
# LLM CLASS
# -----------------------------

class LocalLLM:
    def __init__(self, model_id: str):
        print(f"Loading model {model_id} on GPU...")

        quant_config = None
        if "70B" in model_id:
            print("Using 4-bit quantization for 70B model.")
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
            tokenizer=self.tokenizer
        )

    def complete(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": "You are a professional socio-economic researcher specializing in SOEP."},
            {"role": "user", "content": prompt},
        ]

        prompt_with_template = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        outputs = self.pipeline(
            prompt_with_template,
            max_new_tokens=500,
            do_sample=True,
            temperature=0.6,
            top_p=0.9,
            pad_token_id=self.tokenizer.eos_token_id
        )

        return outputs[0]["generated_text"][len(prompt_with_template):].strip()


llm = None

# -----------------------------
# PDF CONTEXT
# -----------------------------

def get_pdf_context(var_name: str, pdf_text: str) -> str:
    if not pdf_text:
        return ""

    matches = list(re.finditer(rf"\b{re.escape(var_name)}\b", pdf_text, re.IGNORECASE))
    if not matches:
        return ""

    contexts = []
    for match in matches[:3]:
        start = max(0, match.start() - 400)
        end = min(len(pdf_text), match.end() + 400)
        contexts.append(pdf_text[start:end].replace('\n', ' '))

    return "\n---\n".join(contexts)

# -----------------------------
# PROMPT
# -----------------------------

def generate_enrichment_prompt(var: Dict, context: str) -> str:
    return f"""
Your task is to enrich metadata for a SOEP variable to make it highly searchable in a research assistant system.

RAW METADATA:
Name: {var.get('variable_name', '')}
Label: {var.get('label', '')}
Dataset: {var.get('dataset', '')}
Value Mappings: {var.get('value_labels', '')}
Stats: {var.get('stats_summary', '')} {var.get('sample_values', '')}

CODEBOOK CONTEXT:
{context if context else "No direct match found. Infer meaning from label and values."}

Return structured output:

Variable: {var.get('label', '')} ({var.get('variable_name', '')})

Description:
[Clear explanation of what this variable measures]

Level:
[Individual / Household / Other]

Use cases:
- [Example research use]
- [Example research use]

Related concepts:
[keywords like employment, income, education]

Source:
https://paneldata.org/soep-core/datasets/{var.get('dataset','')}/{var.get('variable_name','')}
"""

# -----------------------------
# MAIN PIPELINE
# -----------------------------

def enrich_metadata():
    global llm

    if not os.path.exists(INPUT_FILE):
        print("Input file not found.")
        return

    print("Loading metadata...")
    with open(INPUT_FILE, 'r') as f:
        metadata = json.load(f)

    # Load PDF
    pdf_text = ""
    if os.path.exists(PDF_PATH):
        print("Loading PDF...")
        try:
            pdf_text = extract_text(PDF_PATH)
        except Exception as e:
            print(f"PDF failed: {e}")

    enriched_data = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            enriched_data = json.load(f)
        print(f"Resuming from {len(enriched_data)} variables")

    processed_names = {v['variable_name'] for v in enriched_data}
    remaining = [v for v in metadata if v['variable_name'] not in processed_names]

    # LIMIT FOR TESTING
    remaining = remaining[:MAX_VARIABLES]

    if not remaining:
        print("Nothing to process.")
        return

    if llm is None:
        llm = LocalLLM(MODEL_ID)

    print(f"Processing {len(remaining)} variables...")

    for var in remaining:
        start_time = time.time()

        msg = f"[{len(enriched_data)+1}] {var['variable_name']} ({var.get('label','')})"
        print(msg, flush=True)

        with open("enrichment_heartbeat.log", "a") as hb:
            hb.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")

        try:
            context = get_pdf_context(var['variable_name'], pdf_text)
            prompt = generate_enrichment_prompt(var, context)

            response = llm.complete(prompt)

            print("Preview:", response[:200].replace("\n", " "), flush=True)

            var["rich_description"] = response
            var["model_used"] = MODEL_ID

            enriched_data.append(var)

            elapsed = time.time() - start_time
            print(f"Done in {elapsed:.1f}s", flush=True)

        except Exception as e:
            print(f"Error on {var['variable_name']}: {e}", flush=True)
            continue

        if len(enriched_data) % BATCH_SIZE == 0:
            with open(OUTPUT_FILE, 'w') as f:
                json.dump(enriched_data, f, indent=2)
            print(f"Saved checkpoint ({len(enriched_data)})", flush=True)

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(enriched_data, f, indent=2)

    print("FINISHED")

# -----------------------------
# RUN
# -----------------------------

if __name__ == "__main__":
    enrich_metadata()