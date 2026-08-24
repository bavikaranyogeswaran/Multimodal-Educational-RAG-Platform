"""Step 7.6 / 7.7 end-to-end runner.

Authenticates against Supabase, uploads a PDF, waits for the worker to
ingest it, then sends a set of test queries through the full retrieval and
generation pipeline. Run with:

    uv run python scripts/run_step_7_7.py <path_to_pdf>

The API server and worker must be running separately:
    Terminal 1: uv run uvicorn app.main:app --reload
    Terminal 2: uv run python -m app.worker
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx

from app.configuration.settings import get_settings

API_BASE = "http://127.0.0.1:8000"
TEST_EMAIL = "tutor.rag.test@gmail.com"
TEST_PASSWORD = "TutorRAG_test_2026!"

TEST_QUERIES = [
    "What is Azure Machine Learning and what problems does it solve?",
    "How do you train a regression model in Azure ML?",
    "What Python libraries are used in this book?",
    "What is the difference between training and scoring in Azure ML?",
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def get_jwt(settings) -> str:
    """Sign in to Supabase; sign up first if account does not exist yet."""
    auth_base = f"{settings.supabase.url}/auth/v1"
    headers = {
        "apikey": settings.supabase.anon_key.get_secret_value(),
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # Try sign-in first (idempotent if account already exists)
        r = await client.post(
            f"{auth_base}/token?grant_type=password",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            headers=headers,
        )
        if r.status_code == 200:
            token = r.json().get("access_token")
            if token:
                print(f"  signed in as {TEST_EMAIL}")
                return token

        # Sign up
        r = await client.post(
            f"{auth_base}/signup",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            headers=headers,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Sign-up failed {r.status_code}: {r.text}")
        data = r.json()
        token = data.get("access_token")
        if token:
            print(f"  signed up and signed in as {TEST_EMAIL}")
            return token
        # Email confirmation may be required — common in production Supabase projects
        raise RuntimeError(
            "Supabase returned no access_token. Enable 'Disable email confirmations' "
            "in the Supabase dashboard → Authentication → Settings, then retry."
        )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run(pdf_path: Path) -> None:
    settings = get_settings()

    print("\n=== Step 7.6 — Full ingestion ===\n")

    # 1. Auth
    print("[1/7] Authenticating...")
    jwt = await get_jwt(settings)
    auth_headers = {"Authorization": f"Bearer {jwt}"}

    async with httpx.AsyncClient(base_url=API_BASE, headers=auth_headers, timeout=60) as api:
        # Smoke-check the API is up
        try:
            r = await api.get("/health", timeout=5)
            r.raise_for_status()
        except Exception as exc:
            print(f"\nAPI not reachable at {API_BASE}/health: {exc}")
            print("Start it with:  uv run uvicorn app.main:app --reload")
            sys.exit(1)

        # 2. Create Knowledge Base
        print("[2/7] Creating knowledge base...")
        r = await api.post(
            "/api/v1/knowledge-bases",
            json={
                "name": f"Step 7.7 — {pdf_path.name}",
                "description": "End-to-end test for step 7.7",
                "subject": "Data Science",
                "learning_goal": "Understand concepts from the document",
                "preferred_language": "en",
                "graph_enabled": False,
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Create KB failed {r.status_code}: {r.text}")
        kb = r.json()
        kb_id = kb["id"]
        print(f"  KB: {kb_id}")

        # 3. Upload PDF
        print(f"[3/7] Uploading {pdf_path.name} ({pdf_path.stat().st_size / 1e6:.1f} MB)...")
        with pdf_path.open("rb") as fh:
            r = await api.post(
                f"/api/v1/knowledge-bases/{kb_id}/documents",
                files={"file": (pdf_path.name, fh, "application/pdf")},
                headers={**auth_headers},  # no Content-Type; httpx sets multipart
                timeout=120,
            )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Upload failed {r.status_code}: {r.text}")
        doc = r.json()
        doc_id = doc["document_id"]
        print(f"  document: {doc_id}  pages: {doc.get('page_count')}  status: {doc.get('status')}")

        # 4. Wait for ingestion
        print("[4/7] Waiting for ingestion (start worker if not running)...")
        print("  Tip: uv run python -m app.worker")
        t0 = time.monotonic()
        deadline = t0 + 1800  # 30 min max (OCR + figure captioning on 60+ pages)
        poll_interval = 15
        last_status = ""
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            r = await api.get(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/status")
            if r.status_code == 200:
                status = r.json().get("status", "?")
                if status != last_status:
                    elapsed = int(time.monotonic() - t0)
                    print(f"  [{elapsed:3d}s] {status}")
                    last_status = status
                if status == "COMPLETED":
                    break
                if status == "FAILED":
                    detail = r.json()
                    raise RuntimeError(f"Ingestion FAILED: {detail}")
            poll_interval = min(poll_interval + 2, 15)
        else:
            raise RuntimeError("Ingestion timed out after 10 minutes")

        elapsed = int(time.monotonic() - t0)
        print(f"  ingestion complete in {elapsed}s")

        # 5. Check chunk count
        print("[5/7] Verifying index...")
        r = await api.get(f"/api/v1/knowledge-bases/{kb_id}/documents")
        docs = r.json()
        print(f"  {len(docs)} document(s) in KB, status={docs[0]['status']}")

        # 6. Create conversation
        print("[6/7] Creating conversation...")
        r = await api.post(
            f"/api/v1/knowledge-bases/{kb_id}/conversations",
            json={"title": "Step 7.7 test queries", "active_document_id": doc_id},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Create conversation failed {r.status_code}: {r.text}")
        conv = r.json()
        conv_id = conv["id"]
        print(f"  conversation: {conv_id}")

        # 7. Send queries
        print("\n=== Step 7.7 — End-to-end queries ===\n")
        for i, query in enumerate(TEST_QUERIES, 1):
            print(f"Q{i}: {query}")
            t_q = time.monotonic()
            full_response = ""
            try:
                async with api.stream(
                    "POST",
                    f"/api/v1/knowledge-bases/{kb_id}/conversations/{conv_id}/stream",
                    json={"query": query},
                    timeout=120,
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_text():
                        full_response += chunk
            except Exception as exc:
                print(f"  ERROR: {exc}\n")
                continue

            latency = int((time.monotonic() - t_q) * 1000)
            # Show a trimmed response
            preview = full_response[:500].replace("\n", " ").strip()
            if len(full_response) > 500:
                preview += "…"
            print(f"  ({latency} ms) {preview}\n")

    print("=== 7.7 complete ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/run_step_7_7.py <path_to_pdf>")
        sys.exit(1)
    pdf = Path(sys.argv[1])
    if not pdf.exists():
        print(f"File not found: {pdf}")
        sys.exit(1)
    asyncio.run(run(pdf))
