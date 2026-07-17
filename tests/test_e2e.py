import httpx
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

def print_step(title):
    print(f"\n{'='*50}\n🚀 STEP: {title}\n{'='*50}")

def handle_error(r, step_name):
    """Stops the script and prints the exact error if an API call fails."""
    if r.status_code >= 400:
        print(f"\n❌ ERROR in {step_name} (HTTP {r.status_code}):")
        try:
            print(json.dumps(r.json(), indent=2))
        except:
            print(r.text)
        sys.exit(1)

def run_test():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        
        # --- 1. HEALTH CHECK ---
        print_step("Health Check")
        r = client.get("/health")
        handle_error(r, "Health Check")
        print(f"Status: {r.status_code} | {r.json()}")

        # --- 2. INGEST V1 DOCUMENT ---
        print_step("Ingesting V1 Document")
        with open("data/ct200_manual.pdf", "rb") as f:
            files = {"file": ("ct200_manual.pdf", f, "application/pdf")}
            data = {"version_name": "v1.0"}
            r = client.post("/documents/ingest", data=data, files=files)
        
        handle_error(r, "Ingesting V1 Document")
        doc_v1 = r.json()
        print(f"Ingested Document ID: {doc_v1.get('id')}")
        
        target_node = None
        for node in doc_v1.get('nodes', []):
            if len(node['children']) > 0:
                target_node = node['children'][0]
                break
        if not target_node and len(doc_v1.get('nodes', [])) > 0:
            target_node = doc_v1['nodes'][0]
            
        print(f"Selected Target Node for QA: {target_node['id']} - {target_node['heading']}")

        # --- 3. CREATE SELECTION (PINNING) ---
        print_step("Creating Version-Pinned Selection")
        sel_payload = {
            "name": "Initial V1 QA Scope",
            "node_ids": [target_node['id']]
        }
        r = client.post("/selections/", json=sel_payload)
        handle_error(r, "Creating Selection")
        selection = r.json()
        selection_id = selection['id']
        print(f"Created Selection ID: {selection_id}")

        # --- 4. GENERATE QA TEST CASES VIA LLM ---
        print_step("Triggering LLM QA Generation (This takes a few seconds...)")
        r = client.post("/generations/", json={"selection_id": selection_id, "force_regenerate": False})
        handle_error(r, "LLM Generation")
        generation = r.json()
        
        print("\n🤖 LLM Generated Test Cases:")
        for idx, tc in enumerate(generation.get('test_cases', []), 1):
            print(f"\n  Test {idx}: {tc['title']}")
            print(f"  Pass Criteria: {tc['pass_criteria']}")

        # --- 5. CHECK STALENESS BEFORE V2 (Should be FRESH) ---
        print_step("Checking Staleness (Pre-V2 Update)")
        r = client.get(f"/generations/{selection_id}/staleness")
        handle_error(r, "Staleness Check (Pre-V2)")
        print(json.dumps(r.json(), indent=2))

        # --- 6. INGEST V2 DOCUMENT (TRIGGERING DIFF ENGINE) ---
        print_step("Ingesting V2 Document (Triggering Diff Engine)")
        with open("data/ct200_manual_v2.pdf", "rb") as f:
            files = {"file": ("ct200_manual_v2.pdf", f, "application/pdf")}
            data = {"new_version_name": "v2.0"}
            r = client.post(f"/documents/{doc_v1['id']}/reingest", data=data, files=files)

        # --- 7. CHECK STALENESS AFTER V2 (The Audit) ---
        print_step("Checking Staleness (Post-V2 Update)")
        r = client.get(f"/generations/{selection_id}/staleness")
        handle_error(r, "Staleness Check (Post-V2)")
        staleness_result = r.json()
        
        print(f"\nOVERALL STATUS: {staleness_result.get('overall_status')}")
        for audit in staleness_result.get('node_audits', []):
            print(f"Node {audit['original_node_id']} -> {audit['status']} (Stale: {audit['is_stale']})")
            print(f"Reason: {audit['reason']}")

if __name__ == "__main__":
    run_test()