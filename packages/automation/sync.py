import logging
from pathlib import Path

import httpx
from qdrant_client import AsyncQdrantClient

from packages.shared.config import settings

logger = logging.getLogger(__name__)


async def create_qdrant_snapshot() -> dict:
    """Generate snapshots for all Qdrant collections and download locally."""
    result = {
        "status": "error",
        "message": "Snapshot export failed",
        "exported": [],
        "failed": [],
    }

    try:
        url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
        client = AsyncQdrantClient(url=url)

        try:
            res = await client.get_collections()
            collections = [c.name for c in res.collections]
        except Exception as exc:
            logger.warning("Could not list collections: %s", exc)
            result["error"] = f"Could not list collections: {exc}"
            return result

        if not collections:
            result["status"] = "skipped"
            result["message"] = "No collections found to snapshot"
            return result

        snapshot_dir = Path(settings.data_dir) / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        for collection in collections:
            try:
                logger.info("Creating snapshot for collection: %s", collection)
                snapshot_info = await client.create_snapshot(collection_name=collection)
                snapshot_name = snapshot_info.name

                snapshot_path = snapshot_dir / f"{collection}_{snapshot_name}"
                download_url = f"{url}/collections/{collection}/snapshots/{snapshot_name}"

                async with httpx.AsyncClient() as http_client:
                    async with http_client.stream("GET", download_url) as response:
                        response.raise_for_status()
                        with snapshot_path.open("wb") as handle:
                            async for chunk in response.aiter_bytes():
                                handle.write(chunk)

                logger.info("Successfully exported snapshot to %s", snapshot_path)
                result["exported"].append(str(snapshot_path))

            except Exception as exc:
                logger.error("Failed to snapshot collection %s: %s", collection, exc)
                result["failed"].append({"collection": collection, "error": str(exc)})

        if result["exported"] and result["failed"]:
            result["status"] = "partial"
            result["message"] = "Snapshots exported with partial failures"
        elif result["exported"]:
            result["status"] = "success"
            result["message"] = "Snapshots exported successfully"
        else:
            result["status"] = "error"
            result["message"] = "Failed to export snapshots"

        return result

    except Exception as exc:
        logger.error("Snapshotting background job failed: %s", exc)
        result["error"] = str(exc)
        return result


async def restore_latest_snapshots():
    """
    Check sync directory for newer snapshots and restore if needed.
    """
    snapshot_dir = Path(settings.data_dir) / "snapshots"
    if not snapshot_dir.exists():
        return

    tracker_file = snapshot_dir / ".last_restore_time"
    last_restore = 0.0
    if tracker_file.exists():
        try:
            last_restore = float(tracker_file.read_text().strip())
        except Exception:
            last_restore = 0.0

    url = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
    snapshots = list(snapshot_dir.glob("*.snapshot"))
    if not snapshots:
        return

    latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

    if latest_snapshot.stat().st_mtime <= last_restore + 60:
        return

    logger.info("Detected newer P2P snapshot: %s. Restoring to Qdrant...", latest_snapshot.name)

    collection_name = "personal_memories"
    for prefix in [settings.mem0_collection, settings.podcast_qdrant_collection, settings.qdrant_collection]:
        if latest_snapshot.name.startswith(prefix):
            collection_name = prefix
            break

    try:
        upload_url = f"{url}/collections/{collection_name}/snapshots/upload?priority=snapshot"

        async with httpx.AsyncClient(timeout=300.0) as http_client:
            with latest_snapshot.open("rb") as handle:
                files = {"snapshot": (latest_snapshot.name, handle, "application/octet-stream")}
                response = await http_client.post(upload_url, files=files)
                response.raise_for_status()

        logger.info("Successfully restored snapshot %s into %s", latest_snapshot.name, collection_name)
        tracker_file.write_text(str(latest_snapshot.stat().st_mtime))

    except Exception as exc:
        logger.error("Failed to restore snapshot %s: %s", latest_snapshot.name, exc)
