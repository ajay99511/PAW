"""
ARQ Worker Configuration

Async Redis Queue (ARQ) worker for background task execution.
Provides:
- Job persistence (survives restarts)
- Retry with exponential backoff
- Priority queues
- Job monitoring

Usage:
    arq packages.automation.arq_worker.WorkerSettings
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from arq import cron
from arq.worker import Worker

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Job Definitions
# ─────────────────────────────────────────────────────────────────────

async def run_daily_briefing(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Proactive agent that generates morning summary.
    
    Runs daily at 8:00 AM.
    """
    job_id = ctx["job_id"]
    logger.info(f"Starting daily briefing (job_id={job_id})")
    
    try:
        from packages.agents.crew import run_crew
        
        # Use isolated session (token-efficient)
        result = await run_crew(
            user_message=(
                "Generate a morning briefing of recent activity. "
                "Check for pending background tasks, verify system health, "
                "and summarize overnight updates. "
                f"Briefing date: {datetime.now().strftime('%Y-%m-%d')}."
            ),
            user_id="default",
            model="local",
        )
        
        logger.info(f"Daily briefing completed: {result.get('response', '')[:100]}...")
        
        return {
            "status": "completed",
            "result": result.get("response", ""),
            "completed_at": datetime.now().isoformat(),
        }
    
    except Exception as exc:
        logger.error(f"Daily briefing failed: {exc}")
        raise


async def run_hourly_snapshot(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Export Qdrant snapshot for backup.
    
    Runs every hour.
    """
    job_id = ctx["job_id"]
    logger.info(f"Starting hourly snapshot (job_id={job_id})")
    
    try:
        from packages.memory.qdrant_store import export_snapshot
        
        await export_snapshot()
        
        logger.info("Hourly snapshot completed")
        
        return {
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
        }
    
    except Exception as exc:
        logger.error(f"Hourly snapshot failed: {exc}")
        raise


async def run_memory_consolidation(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Consolidate memories for user.
    
    Runs every 20 conversation turns (configured in memory service).
    """
    job_id = ctx["job_id"]
    logger.info(f"Starting memory consolidation (job_id={job_id})")
    
    try:
        from packages.memory.consolidation import consolidate_memories
        
        await consolidate_memories(user_id="default", model="local")
        
        logger.info("Memory consolidation completed")
        
        return {
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
        }
    
    except Exception as exc:
        logger.error(f"Memory consolidation failed: {exc}")
        raise


async def run_workspace_audit(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Generate workspace audit summary.
    
    Runs weekly on Monday at 9:00 AM.
    """
    job_id = ctx["job_id"]
    logger.info(f"Starting workspace audit (job_id={job_id})")
    
    try:
        from packages.agents.workspace import list_workspace_configs
        
        configs = list_workspace_configs()
        
        summary = f"Audited {len(configs)} workspaces:\n"
        for config in configs:
            summary += f"- {config.project_id}: {config.root}\n"
        
        logger.info(f"Workspace audit completed: {summary[:200]}...")
        
        return {
            "status": "completed",
            "result": summary,
            "workspace_count": len(configs),
            "completed_at": datetime.now().isoformat(),
        }
    
    except Exception as exc:
        logger.error(f"Workspace audit failed: {exc}")
        raise


# ─────────────────────────────────────────────────────────────────────
# Worker Configuration
# ─────────────────────────────────────────────────────────────────────

class WorkerSettings:
    """ARQ worker configuration."""
    
    # Functions that can be executed
    functions = [
        run_daily_briefing,
        run_hourly_snapshot,
        run_memory_consolidation,
        run_workspace_audit,
    ]
    
    # Cron jobs (scheduled tasks)
    cron_jobs = [
        cron(
            run_daily_briefing,
            hour=8,
            minute=0,
        ),
        cron(
            run_hourly_snapshot,
            minute=0,
        ),
        cron(
            run_workspace_audit,
            hour=9,
            minute=0,
            weekday="mon",
        ),
    ]
    
    # Redis settings
    redis_settings = {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    }
    
    # Worker settings
    max_jobs = 10  # Max concurrent jobs
    job_timeout = 300  # 5 minutes default timeout
    retry_delay = 60  # 1 minute before first retry
    retry_delay_steps = [60, 120, 300, 900, 3600]  # Exponential backoff
    max_tries = 5  # Maximum retry attempts
    
    # Logging
    log_results = True
    log_jobs = True
    
    # Health check
    health_check_interval = 10  # seconds


# ─────────────────────────────────────────────────────────────────────
# Job Management Helpers
# ─────────────────────────────────────────────────────────────────────

async def enqueue_job(
    job_name: str,
    **kwargs: Any,
) -> str:
    """
    Enqueue a job manually.
    
    Args:
        job_name: Name of job function
        **kwargs: Arguments to pass to job
    
    Returns:
        Job ID
    """
    from arq import create_pool
    from arq.connections import RedisSettings
    
    redis = await create_pool(RedisSettings(host="localhost", port=6379))
    
    job = await redis.enqueue_job(job_name, **kwargs)
    
    logger.info(f"Enqueued job: {job_name} (job_id={job.job_id})")
    
    return job.job_id


async def get_job_status(job_id: str) -> dict[str, Any]:
    """
    Get status of a job.
    
    Args:
        job_id: Job identifier
    
    Returns:
        Job status dict
    """
    from arq import create_pool
    from arq.connections import RedisSettings
    
    redis = await create_pool(RedisSettings(host="localhost", port=6379))
    
    # Try to get job info
    info = await redis.read_job_result(job_id)
    
    if info:
        return {
            "job_id": job_id,
            "status": "completed",
            "result": info,
        }
    
    return {
        "job_id": job_id,
        "status": "unknown",
    }


async def list_jobs() -> list[dict[str, Any]]:
    """
    List all recent jobs.
    
    Returns:
        List of job info dicts
    """
    from arq import create_pool
    from arq.connections import RedisSettings
    
    redis = await create_pool(RedisSettings(host="localhost", port=6379))
    
    # Get all job keys
    keys = await redis.redis.keys("arq:job:*")
    
    jobs = []
    for key in keys[:100]:  # Limit to 100 most recent
        job_id = key.decode().replace("arq:job:", "")
        status = await get_job_status(job_id)
        jobs.append(status)
    
    return jobs


# ─────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "run":
            # Run worker
            print("Starting ARQ worker...")
            print("Press Ctrl+C to stop")
            
            # Worker will run indefinitely
            import asyncio
            from arq.worker import run_worker
            
            asyncio.run(run_worker(WorkerSettings))
        
        elif command == "enqueue":
            # Enqueue a job manually
            if len(sys.argv) < 3:
                print("Usage: python arq_worker.py enqueue <job_name>")
                sys.exit(1)
            
            job_name = sys.argv[2]
            job_id = asyncio.run(enqueue_job(job_name))
            print(f"Enqueued job: {job_name} (job_id={job_id})")
        
        else:
            print(f"Unknown command: {command}")
            print("Usage: python arq_worker.py [run|enqueue]")
            sys.exit(1)
    else:
        print("ARQ Worker Configuration")
        print("========================")
        print()
        print("To run the worker:")
        print("  arq packages.automation.arq_worker.WorkerSettings")
        print()
        print("Or:")
        print("  python arq_worker.py run")
        print()
        print("To enqueue a job manually:")
        print("  python arq_worker.py enqueue <job_name>")
        print()
        print("Available jobs:")
        print("  - run_daily_briefing (8:00 AM daily)")
        print("  - run_hourly_snapshot (every hour)")
        print("  - run_workspace_audit (9:00 AM Monday)")
        print("  - run_memory_consolidation (on-demand)")
