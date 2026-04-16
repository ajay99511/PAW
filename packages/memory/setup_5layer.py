"""
5-Layer Memory System Setup Script

Initializes the 5-layer memory system:
1. Creates directory structure
2. Creates bootstrap template files
3. Validates configuration
4. Runs health checks

Usage:
    python -m packages.memory.setup_5layer
"""

import asyncio
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def create_directory_structure() -> dict[str, Path]:
    """Create the 5-layer memory directory structure."""
    base_dir = Path.home() / ".personalassist"
    
    directories = {
        "base": base_dir,
        "sessions": base_dir / "sessions",
        "memory": base_dir / "memory",
        "workspaces": base_dir / "workspaces",
        "logs": base_dir / "logs",
        "sandboxes": base_dir / "sandboxes",
        "archive": base_dir / "sessions" / "archive",
    }
    
    logger.info(f"Creating directory structure under {base_dir}")
    
    for name, path in directories.items():
        path.mkdir(parents=True, exist_ok=True)
        logger.info(f"  ✓ Created {name}: {path}")
    
    return directories


async def create_bootstrap_files() -> dict[str, Path]:
    """Create bootstrap template files."""
    from packages.memory.bootstrap import create_bootstrap_templates
    
    logger.info("Creating bootstrap template files...")
    
    templates = create_bootstrap_templates(overwrite=False)
    
    for filename, path in templates.items():
        logger.info(f"  {'✓ Created' if path.exists() else '⚠ Exists'}: {filename}")
    
    return templates


async def validate_qdrant_connection() -> bool:
    """Validate Qdrant connection."""
    from packages.memory.qdrant_store import health_check
    
    logger.info("Checking Qdrant connection...")
    
    try:
        result = await health_check()
        logger.info(f"  ✓ Qdrant connected, collections: {result}")
        return True
    except Exception as exc:
        logger.error(f"  ✗ Qdrant connection failed: {exc}")
        return False


async def validate_mem0_connection() -> bool:
    """Validate local memory connection."""
    from packages.memory.mem0_client import mem0_get_all
    
    logger.info("Checking local memory connection...")
    
    try:
        # Try to list memories from the local memory layer.
        memories = mem0_get_all(user_id="default")
        logger.info(f"  ✓ Local memory connected, {len(memories)} memories found")
        return True
    except Exception as exc:
        logger.error(f"  ✗ Local memory connection failed: {exc}")
        return False


async def test_secret_redaction() -> bool:
    """Test secret redaction middleware."""
    from packages.shared.redaction import SecretRedactor
    
    logger.info("Testing secret redaction...")
    
    redactor = SecretRedactor()
    
    test_cases = [
        ("API key: sk-abc123def456ghi789jkl012mno345", "[REDACTED_OPENAI_API_KEY]"),
        ("Password: mysecret123", "Password=[REDACTED]"),
        ("AWS key: AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_ACCESS_KEY]"),
    ]
    
    all_passed = True
    for input_text, expected_pattern in test_cases:
        redacted, count = redactor.redact(input_text)
        if count > 0:
            logger.info(f"  ✓ Redacted: {input_text[:30]}... → {count} secrets")
        else:
            logger.warning(f"  ✗ Failed to redact: {input_text[:30]}...")
            all_passed = False
    
    return all_passed


async def test_bootstrap_loading() -> bool:
    """Test bootstrap file loading."""
    from packages.memory.bootstrap import load_bootstrap_files, get_bootstrap_summary
    
    logger.info("Testing bootstrap file loading...")
    
    try:
        # Load bootstrap files
        context = await load_bootstrap_files(agent_type="main")
        
        if context:
            logger.info(f"  ✓ Loaded bootstrap context ({len(context)} chars)")
            
            # Get summary
            summary = await get_bootstrap_summary()
            logger.info(f"  ✓ Summary: {summary['total_files']} files, {summary['total_chars']} chars")
            return True
        else:
            logger.warning("  ⚠ No bootstrap files loaded (templates may need editing)")
            return True  # Not a failure, just no content yet
    
    except Exception as exc:
        logger.error(f"  ✗ Bootstrap loading failed: {exc}")
        return False


async def run_health_checks() -> dict:
    """Run comprehensive health checks."""
    logger.info("\n" + "="*60)
    logger.info("5-LAYER MEMORY SYSTEM - HEALTH CHECK")
    logger.info("="*60 + "\n")
    
    results = {
        "directories": False,
        "bootstrap": False,
        "qdrant": False,
        "mem0": False,
        "redaction": False,
        "bootstrap_load": False,
    }
    
    # Create directories
    try:
        create_directory_structure()
        results["directories"] = True
    except Exception as exc:
        logger.error(f"Directory creation failed: {exc}")
    
    # Create bootstrap files
    try:
        await create_bootstrap_files()
        results["bootstrap"] = True
    except Exception as exc:
        logger.error(f"Bootstrap creation failed: {exc}")
    
    # Test Qdrant
    results["qdrant"] = await validate_qdrant_connection()
    
    # Test local memory layer
    results["mem0"] = await validate_mem0_connection()
    
    # Test redaction
    results["redaction"] = await test_secret_redaction()
    
    # Test bootstrap loading
    results["bootstrap_load"] = await test_bootstrap_loading()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("HEALTH CHECK SUMMARY")
    logger.info("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check, passed_check in results.items():
        status = "✓ PASS" if passed_check else "✗ FAIL"
        logger.info(f"  {status}: {check}")
    
    logger.info(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        logger.info("\n🎉 5-Layer Memory System is ready!")
    else:
        logger.warning(f"\n⚠ {total - passed} checks failed. Review errors above.")
    
    return results


async def main():
    """Main setup function."""
    logger.info("Starting 5-Layer Memory System setup...\n")
    
    # Run health checks
    results = await run_health_checks()
    
    # Exit with appropriate code
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    if passed == total:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
