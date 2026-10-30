"""Add E621BlockedTag model and database methods to db.py."""
import pathlib

p = pathlib.Path(r"c:\Users\CaioWithC\Documents\RalseiBot\db.py")
content = p.read_text(encoding="utf-8")

# 1) Add E621BlockedTag model before E621SearchStat
old_model = "class E621SearchStat(Base):\n"
new_model = (
    "class E621BlockedTag(Base):\n"
    '    __tablename__ = "e621_blocked_tags"\n'
    "    guild_id = Column(String, primary_key=True)\n"
    "    tag = Column(String, primary_key=True)\n"
    "\n\n"
    "class E621SearchStat(Base):\n"
)
content = content.replace(old_model, new_model, 1)

# 2) Add database methods before reset_e621_stats
old_method = "    def reset_e621_stats(self, guild_id):\n"
new_methods = (
    '    def add_e621_blocked_tag(self, guild_id, tag):\n'
    '        """Block a tag from e621 searches in a guild. Returns True if added, False if already blocked."""\n'
    '        if not guild_id or not tag:\n'
    '            return False\n'
    '        tag = str(tag).strip().lower()\n'
    '        with self.transaction() as session:\n'
    '            existing = session.get(E621BlockedTag, (str(guild_id), tag))\n'
    '            if existing:\n'
    '                return False\n'
    '            session.add(E621BlockedTag(guild_id=str(guild_id), tag=tag))\n'
    '            return True\n'
    '\n'
    '    def remove_e621_blocked_tag(self, guild_id, tag):\n'
    '        """Unblock a tag from e621 searches in a guild. Returns True if removed, False if not found."""\n'
    '        if not guild_id or not tag:\n'
    '            return False\n'
    '        tag = str(tag).strip().lower()\n'
    '        with self.transaction() as session:\n'
    '            existing = session.get(E621BlockedTag, (str(guild_id), tag))\n'
    '            if existing is None:\n'
    '                return False\n'
    '            session.delete(existing)\n'
    '            return True\n'
    '\n'
    '    def get_e621_blocked_tags(self, guild_id):\n'
    '        """Return a sorted list of blocked tags for a guild."""\n'
    '        if not guild_id:\n'
    '            return []\n'
    '        with Session(self.engine) as session:\n'
    '            rows = session.scalars(\n'
    '                select(E621BlockedTag.tag)\n'
    '                .where(E621BlockedTag.guild_id == str(guild_id))\n'
    '                .order_by(E621BlockedTag.tag)\n'
    '            ).all()\n'
    '            return list(rows)\n'
    '\n'
    '    def reset_e621_stats(self, guild_id):\n'
)
content = content.replace(old_method, new_methods, 1)

p.write_text(content, encoding="utf-8")
print("db.py updated successfully!")

