"""Check that every external dependency this application needs is actually reachable.

Run from the backend directory:

    uv run python scripts/verify_environment.py

Each check reports PASS, FAIL or SKIP. SKIP means the credential for that service is not
configured yet, which is a normal state early on — the script is meant to be useful before
everything is wired up, not only afterwards. The exit code is non-zero only when something
is configured and broken, so an unconfigured machine does not look like a failing one.
"""

from __future__ import annotations

import asyncio
import platform
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.configuration.settings import Settings

REQUIRED_PYTHON = (3, 12)
REQUIRED_EXTENSIONS = ("vector", "rum", "pg_cron", "pg_trgm")


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105 - a verification outcome, not a credential
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARN = "WARN"


@dataclass(frozen=True)
class Result:
    name: str
    status: Status
    detail: str


def _colour(status: Status) -> str:
    if not sys.stdout.isatty():
        return ""
    return {
        Status.PASS: "\033[32m",
        Status.FAIL: "\033[31m",
        Status.SKIP: "\033[90m",
        Status.WARN: "\033[33m",
    }[status]


def _render(results: list[Result], width: int) -> None:
    reset = "\033[0m" if sys.stdout.isatty() else ""
    for r in results:
        print(f"    {r.name:<{width}} {_colour(r.status)}{r.status:<6}{reset} {r.detail}")


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
async def check_python() -> list[Result]:
    actual = sys.version_info[:2]
    ok = actual == REQUIRED_PYTHON
    return [
        Result(
            "python",
            Status.PASS if ok else Status.FAIL,
            f"{platform.python_version()}"
            + ("" if ok else f" — expected {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"),
        )
    ]


async def check_torch(settings: Settings) -> list[Result]:
    try:
        import torch
    except ImportError:
        return [Result("torch / cuda", Status.SKIP, "ml group not installed")]

    if not torch.cuda.is_available():
        detail = "no CUDA device visible to torch"
        # Only a failure if something is actually configured to use the GPU.
        wants_gpu = settings.embedding.device == "cuda" or settings.reranker.device == "cuda"
        return [Result("torch / cuda", Status.FAIL if wants_gpu else Status.WARN, detail)]

    props = torch.cuda.get_device_properties(0)
    vram = props.total_memory / 1024**3
    try:
        x = torch.randn(512, 512, device="cuda")
        _ = (x @ x.T).sum().item()
        del x
        torch.cuda.empty_cache()
    except Exception as exc:
        return [Result("torch / cuda", Status.FAIL, f"device present but compute failed: {exc}")]

    return [
        Result(
            "torch / cuda",
            Status.PASS,
            f"{torch.__version__} · {torch.cuda.get_device_name(0)} · "
            f"{vram:.2f} GiB · sm_{props.major}{props.minor}",
        )
    ]


async def check_paddle(settings: Settings) -> list[Result]:
    try:
        import paddle
    except ImportError:
        return [Result("paddle", Status.SKIP, "ml group not installed")]

    compiled_with_cuda = paddle.device.is_compiled_with_cuda()
    expected_cpu = settings.ocr.device == "cpu"

    # A GPU build when the configuration says CPU is not fatal, but it is worth saying:
    # it means a larger install than necessary and a risk of contending for VRAM.
    if expected_cpu and compiled_with_cuda:
        status, note = Status.WARN, "GPU build installed but OCR is configured for CPU"
    elif not expected_cpu and not compiled_with_cuda:
        status, note = Status.FAIL, "CPU build installed but OCR is configured for GPU"
    else:
        status, note = Status.PASS, f"{paddle.device.get_device()}"

    try:
        import paddleocr

        version = f"paddle {paddle.__version__} · paddleocr {paddleocr.__version__}"
    except ImportError:
        return [Result("paddle", Status.FAIL, "paddlepaddle present but paddleocr missing")]

    return [Result("paddle / ocr", status, f"{version} · {note}")]


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
async def check_ollama(settings: Settings) -> list[Result]:
    import httpx

    base = settings.model.ollama_base_url
    wanted = {
        settings.model.default_text_model,
        settings.model.default_vision_model,
        settings.model.query_rewrite_model,
        settings.model.faithfulness_model,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base}/api/tags")
            response.raise_for_status()
            payload = response.json()
    except httpx.ConnectError:
        return [
            Result(
                "ollama",
                Status.FAIL,
                f"nothing listening at {base} — install Ollama and start it, "
                "or point MODEL_OLLAMA_BASE_URL elsewhere",
            )
        ]
    except Exception as exc:
        return [Result("ollama", Status.FAIL, f"{base} — {type(exc).__name__}: {exc}")]

    installed = {m["name"] for m in payload.get("models", [])}
    # Ollama reports "gemma3:4b"; a bare "gemma3" in configuration means the latest tag.
    normalised = {name.split(":")[0] for name in installed}
    missing = sorted(m for m in wanted if m not in installed and m.split(":")[0] not in normalised)

    results = [Result("ollama", Status.PASS, f"reachable at {base} · {len(installed)} model(s)")]
    if missing:
        results.append(
            Result(
                "  configured models",
                Status.FAIL,
                f"not pulled: {', '.join(missing)} — run: ollama pull {missing[0]}",
            )
        )
    else:
        results.append(
            Result("  configured models", Status.PASS, f"present: {', '.join(sorted(wanted))}")
        )
    return results


def _psycopg_dsn(url: str) -> str:
    """SQLAlchemy URLs carry a driver suffix that libpq does not understand."""
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgres+psycopg://", "postgresql://"
    )


async def check_database(settings: Settings) -> list[Result]:
    dsn = settings.database.url.get_secret_value()
    if not dsn:
        return [Result("postgres", Status.SKIP, "DATABASE_URL not set")]

    try:
        import psycopg
    except ImportError:
        return [Result("postgres", Status.FAIL, "psycopg not installed")]

    started = time.perf_counter()
    try:
        async with (
            await psycopg.AsyncConnection.connect(_psycopg_dsn(dsn), connect_timeout=10) as conn,
            conn.cursor() as cur,
        ):
            await cur.execute("SELECT version()")
            row = await cur.fetchone()
            version = (row[0] if row else "unknown").split(" on ")[0]

            await cur.execute(
                "SELECT name, installed_version FROM pg_available_extensions "
                "WHERE name = ANY(%s) ORDER BY name",
                (list(REQUIRED_EXTENSIONS),),
            )
            available = dict(await cur.fetchall())
    except Exception as exc:
        return [Result("postgres", Status.FAIL, f"{type(exc).__name__}: {exc}")]

    elapsed = (time.perf_counter() - started) * 1000
    results = [Result("postgres", Status.PASS, f"{version} · connected in {elapsed:.0f} ms")]

    for name in REQUIRED_EXTENSIONS:
        if name not in available:
            results.append(Result(f"  ext {name}", Status.FAIL, "not available on this server"))
        elif available[name] is None:
            results.append(
                Result(
                    f"  ext {name}",
                    Status.WARN,
                    "available, not yet installed — migrations do this",
                )
            )
        else:
            results.append(Result(f"  ext {name}", Status.PASS, f"installed {available[name]}"))

    return results


async def check_storage(settings: Settings) -> list[Result]:
    storage = settings.storage
    if not storage.account_id or not storage.access_key_id.get_secret_value():
        return [Result("r2 storage", Status.SKIP, "STORAGE_ACCOUNT_ID / credentials not set")]

    try:
        import aioboto3
        import httpx
    except ImportError:
        return [Result("r2 storage", Status.FAIL, "aioboto3 not installed")]

    key = f"{storage.page_render_prefix}/_verify/{uuid.uuid4().hex}.txt"
    body = b"environment verification"

    session = aioboto3.Session()
    try:
        async with session.client(
            "s3",
            endpoint_url=storage.endpoint_url,
            aws_access_key_id=storage.access_key_id.get_secret_value(),
            aws_secret_access_key=storage.secret_access_key.get_secret_value(),
            region_name=storage.region,
        ) as s3:
            await s3.put_object(Bucket=storage.bucket, Key=key, Body=body)

            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": storage.bucket, "Key": key},
                ExpiresIn=storage.signed_url_ttl_seconds,
            )
            async with httpx.AsyncClient(timeout=15.0) as client:
                fetched = await client.get(url)
            fetched.raise_for_status()
            round_tripped = fetched.content == body

            await s3.delete_object(Bucket=storage.bucket, Key=key)
    except Exception as exc:
        return [Result("r2 storage", Status.FAIL, f"{type(exc).__name__}: {exc}")]

    if not round_tripped:
        return [Result("r2 storage", Status.FAIL, "signed URL returned unexpected content")]

    return [
        Result(
            "r2 storage",
            Status.PASS,
            f"bucket {storage.bucket!r} · put, signed get and delete succeeded",
        )
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
SECTIONS: dict[str, list[Callable[[Settings], Awaitable[list[Result]]]]] = {
    "runtime": [lambda _: check_python(), check_torch, check_paddle],
    "services": [check_ollama, check_database, check_storage],
}


async def main() -> int:
    try:
        settings = Settings()
    except Exception as exc:
        print(f"\nConfiguration is invalid, so nothing else can be checked:\n\n{exc}\n")
        return 1

    print()
    print("Environment verification")
    print("=" * 78)

    by_section: dict[str, list[Result]] = {}
    for section, checks in SECTIONS.items():
        gathered = await asyncio.gather(*(check(settings) for check in checks))
        by_section[section] = [r for group in gathered for r in group]

    all_results = [r for group in by_section.values() for r in group]
    width = max(len(r.name) for r in all_results) + 2

    for section, section_results in by_section.items():
        print(f"  {section}")
        _render(section_results, width)

    print("=" * 78)
    counts = {s: sum(1 for r in all_results if r.status is s) for s in Status}
    summary = " · ".join(
        f"{counts[s]} {s.value.lower()}" for s in Status if counts[s] or s is Status.FAIL
    )
    print(f"  {summary}")

    if counts[Status.SKIP]:
        print("\n  Skipped checks are unconfigured, not broken. Fill in backend/.env to run them.")
    print()

    return 1 if counts[Status.FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
