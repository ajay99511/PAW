"""Manual memory smoke test script.

Kept as a utility, but skipped in automated pytest runs because it depends on
external local services (Qdrant/Ollama) and user environment.
"""

import asyncio
import json

import pytest

from packages.memory.mem0_client import mem0_add, mem0_get_all, mem0_delete

pytestmark = pytest.mark.skip(reason="Manual memory smoke test; run directly if needed.")


async def test_memory():
    print("----- ADDING MEMORY -----")
    res = mem0_add("I am a software engineer working on PersonalAssist.", user_id="default")
    print(json.dumps(res, indent=2))

    print("\n----- GETTING MEMORIES -----")
    memories = mem0_get_all(user_id="default")
    print(json.dumps(memories, indent=2))

    if memories:
        print("\n----- DELETING MEMORY -----")
        first_id = memories[0]["id"]
        del_res = mem0_delete(first_id)
        print("Deleted:", del_res)

        print("\n----- GETTING MEMORIES AGAIN -----")
        memories = mem0_get_all(user_id="default")
        print(f"Count: {len(memories)}")


if __name__ == "__main__":
    asyncio.run(test_memory())
