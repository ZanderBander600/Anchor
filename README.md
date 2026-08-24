# Mini-Anchor

Mini-Anchor is a proof-of-concept real estate acquisition analysis application.

## POC Objective

Build an end-to-end workflow that:

1. Reads nine core acquisition inputs from Excel.
2. Validates and standardizes the inputs.
3. Runs a deterministic Python acquisition engine.
4. Produces verified investment returns and debt metrics.
5. Exposes the engine through a web application.
6. Adds Azure-assisted document extraction.
7. Adds OpenAI-based investment interpretation.

## Core Rule

AI may extract, normalize, summarize, and interpret information.

AI does not calculate authoritative financial outputs.

All core financial calculations are performed by the deterministic Mini-Anchor Python engine.

## Development Order

1. Financial specification
2. Excel ingestion
3. Deterministic engine
4. Financial QA
5. Results contract
6. FastAPI
7. UI/UX
8. Azure Document Intelligence
9. OpenAI analysis
10. POC hardening