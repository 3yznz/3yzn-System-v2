# Project: 3YZN Discord Bot
# Author: 3YZN (@3yzn)
# Copyright (c) 2026 3YZN
# License: See LICENSE
import pytest
import aiosqlite
from database import Database

@pytest.mark.asyncio
async def test_database_initializes_and_persists(tmp_path):
    db=Database(str(tmp_path / "test.sqlite3"))
    await db.initialize()
    await db.execute("INSERT INTO separator_settings(guild_id,trigger,image_url,matching_mode) VALUES(?,?,?,?)", (123,"hello","https://example.com/image.png","substring"))
    row=await db.fetchone("SELECT trigger FROM separator_settings WHERE guild_id=?", (123,))
    assert row["trigger"] == "hello"
    await db.close()


@pytest.mark.asyncio
async def test_database_adds_member_system_columns_without_losing_mute_role(tmp_path):
    import aiosqlite

    path = str(tmp_path / "legacy.sqlite3")
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            "CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, mute_role_id INTEGER)"
        )
        await connection.execute(
            "INSERT INTO guild_settings(guild_id, mute_role_id) VALUES(?, ?)", (456, 789)
        )
        await connection.commit()

    db = Database(path)
    await db.initialize()
    row = await db.fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (456,))
    assert row["mute_role_id"] == 789
    assert "auto_role_member_id" in row.keys()
    assert row["auto_role_member_id"] is None
    await db.execute(
        "UPDATE guild_settings SET welcome_channel_id=? WHERE guild_id=?", (111, 456)
    )
    row = await db.fetchone("SELECT * FROM guild_settings WHERE guild_id=?", (456,))
    assert row["welcome_channel_id"] == 111
    assert row["mute_role_id"] == 789
    await db.close()
