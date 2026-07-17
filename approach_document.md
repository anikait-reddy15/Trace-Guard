# Architectural Approach & Decision Log

## 1. System Architecture: The Hybrid Database Strategy
TraceGuard relies on a dual-database architecture to satisfy the competing requirements of rigid structural versioning and flexible, schema-less LLM outputs.

* **SQLite (Relational):** Used to maintain the Document Tree and Selections. By parsing manuals into an AST (Abstract Syntax Tree) of hierarchical Nodes, we establish strict foreign-key relationships. This ensures that a QA `Selection` is mathematically pinned to an exact structural node, preventing dangling references if the underlying document is modified.
* **MongoDB (NoSQL):** Used to store the generated test cases and temporal state snapshots. LLM outputs, even when strictly typed, are inherently dynamic in length and structure. MongoDB allows us to cache these documents alongside a dictionary of the source node's cryptographic hashes at the exact time of generation.

## 2. Decision Log Responses

### Handling Duplicate Submissions (Idempotency)
**Design Choice:** Generating test cases consumes API tokens and introduces latency. We implemented an idempotency policy in the `/generations/` endpoint. 
**Implementation:** Before triggering the LLM, the system checks MongoDB for an existing document linked to the requested `selection_id`. If a record exists, the API intercepts the request and returns the cached JSON immediately. Users must explicitly pass a `force_regenerate=True` boolean in the payload to bypass the cache, saving time and compute resources while ensuring predictable behavior.

### Handling Malformed or Incomplete Output
**Design Choice:** In medical software QA, "usually correct" JSON is unacceptable. The system cannot fail silently or attempt to parse hallucinated structures.
**Implementation:** The LLM Engine utilizes the `instructor` library layered over the Gemini 3.5 Flash model. 
1. We enforce a strict Pydantic schema (`QAGenerationResult`).
2. If the LLM hallucinates (e.g., returning 2 test cases instead of the mandated 3-5, or returning a string instead of a list), Pydantic raises a `ValidationError`. 
3. `instructor` intercepts this error, passes the validation stack trace back to the LLM automatically, and prompts it to fix its mistake (`max_retries=3`). 
4. If it fails after 3 attempts, the system throws a custom `LLMGenerationError`, halting the API and returning a `422 Unprocessable Entity` to the client. This guarantees that malformed data never enters the database.

### The Staleness Audit: Strategy and Limitations
**Design Choice:** To evaluate if a test case is outdated against a new V2 manual, we prioritized strict regulatory compliance over semantic guessing. 
**Implementation:** At the moment of generation, the system saves the `content_hash` of each selected node in MongoDB. The `/staleness` endpoint queries the live SQLite database for the newest version of the document, searches for the exact hierarchical counterpart (by heading and level), and compares the hashes. 

**Limitations of this approach:**
1. **Cosmetic Sensitivity:** Because it relies on cryptographic hashing, a single typo correction (e.g., changing "Ensure" to "Make sure") will alter the hash. The system will flag the node as `MODIFIED` and the test as `STALE`, even if the underlying engineering requirement did not change. 
2. **Structural Renaming:** If the V2 document renames a section heading (e.g., from "Cuff Limits" to "Cuff Pressure Limits"), the path-matching algorithm fails to find the counterpart. It will flag the original node as `DELETED` and the test as `STALE`. 

While this creates false positives for staleness, it is the safest design for medical QA. An automated system should flag any textual alteration and force a human QA engineer to formally approve cosmetic updates, ensuring zero regulatory blind spots.