# TraceGuard QA Engine

## Overview

TraceGuard is a backend API designed for Medical Device Quality
Assurance. It parses hierarchical document structures (such as PDF
manuals), allows QA engineers to pin test scopes to specific sections,
uses Large Language Models (LLMs) to generate structured test cases, and
performs deterministic staleness audits when new versions of the manual
are uploaded.

## Core Features

-   **Hierarchical Document Ingestion:** Parses documents into an
    Abstract Syntax Tree (AST) of nodes based on structural levels
    (headings, subheadings, body text).
-   **Immutable Version Pinning:** Selections are permanently bound to
    exact node IDs corresponding to a specific version of a document.
-   **Structured LLM Generation:** Enforces rigid JSON schema outputs
    for test cases using the `instructor` library, complete with
    self-correction retry loops.
-   **Cryptographic Staleness Auditing:** Cross-references the exact
    state of a document at generation time against future document
    uploads to detect drift, modification, or deletion.

## Technology Stack

  Component             Technology
  --------------------- --------------------------------------------------
  Framework             FastAPI
  Relational Database   SQLite (`aiosqlite`, `SQLAlchemy`)
  NoSQL Database        MongoDB
  LLM Engine            Google Gemini 3.5 Flash (`instructor`, `openai`)
  Data Validation       Pydantic V2

## Setup & Installation

### 1. Clone and Create a Virtual Environment

``` bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install Dependencies

``` bash
pip install fastapi uvicorn motor aiosqlite sqlalchemy httpx pydantic-settings python-multipart python-dotenv pymupdf instructor openai
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

``` env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 4. Database Requirements

Ensure MongoDB is running locally on port **27017**, or update the
`mongodb_url` in `app/config.py` with your MongoDB Atlas connection
string.

### 5. Start the Server

``` bash
uvicorn app.main:app --reload
```

## Testing the API

Run the end-to-end test suite:

``` bash
python tests/test_e2e.py
```

------------------------------------------------------------------------

# Architectural Approach & Decision Log

## 1. System Architecture: Hybrid Database Strategy

TraceGuard uses a dual-database architecture to balance strict
structural versioning with flexible LLM-generated outputs.

### SQLite (Relational)

-   Stores the document tree and user selections.
-   Parses manuals into an AST of hierarchical nodes.
-   Maintains strict foreign-key relationships.
-   Ensures every QA selection is permanently pinned to an exact
    document node.

### MongoDB (NoSQL)

-   Stores generated test cases.
-   Stores cached LLM responses.
-   Stores temporal snapshots of document node hashes.
-   Enables efficient regeneration avoidance and staleness auditing.

------------------------------------------------------------------------

## 2. Decision Log

### Handling Duplicate Submissions (Idempotency)

**Design Choice**

Generating test cases consumes API tokens and increases latency, so
duplicate requests should reuse existing results whenever possible.

**Implementation**

-   Before invoking the LLM, the `/generations/` endpoint checks MongoDB
    for an existing generation associated with the requested
    `selection_id`.
-   If found, the cached JSON response is returned immediately.
-   Clients may bypass the cache by setting:

``` json
{
  "force_regenerate": true
}
```

This minimizes API cost while ensuring deterministic behavior.

------------------------------------------------------------------------

### Handling Malformed or Incomplete LLM Output

**Design Choice**

Medical device QA requires guaranteed structured outputs. Invalid JSON
or incomplete responses are never accepted.

**Implementation**

1.  The LLM output must conform to the `QAGenerationResult` Pydantic
    schema.
2.  Invalid responses trigger a `ValidationError`.
3.  The `instructor` library automatically returns the validation error
    to Gemini and retries generation (up to **3 retries**).
4.  If validation still fails, the application raises a custom
    `LLMGenerationError`.
5.  The API returns:

``` http
422 Unprocessable Entity
```

Malformed data is never written to the database.

------------------------------------------------------------------------

### Staleness Audit Strategy

**Design Choice**

For regulatory compliance, TraceGuard uses deterministic hash comparison
instead of semantic similarity.

**Implementation**

At generation time:

-   The `content_hash` of every selected node is stored in MongoDB.

During a staleness audit:

1.  The latest document version is loaded from SQLite.
2.  The corresponding node is located using its heading and hierarchy
    level.
3.  The stored hash is compared with the current hash.
4.  Any mismatch marks the associated test cases as **STALE**.

------------------------------------------------------------------------

## Limitations

### 1. Cosmetic Changes

Because cryptographic hashes are used, even minor edits such as:

> Ensure → Make sure

produce different hashes.

Result:

-   Node status: **MODIFIED**
-   Test status: **STALE**

Even though the engineering requirement remains unchanged.

### 2. Section Renaming

Example:

    Cuff Limits

renamed to

    Cuff Pressure Limits

The hierarchy lookup fails to locate the original section.

Result:

-   Original node marked as **DELETED**
-   Associated test cases marked as **STALE**

------------------------------------------------------------------------

## Rationale

Although this approach may produce false positives, it is intentionally
conservative.

For medical device quality assurance, reviewing an unchanged test case
is significantly safer than incorrectly assuming a modified requirement
is still valid.
