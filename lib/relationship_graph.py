"""
Relationship Graph — Central store for person-to-person connections.

Captures edges from email threads, meetings, LinkedIn, and social graph signals
into a single SQLite database. Supports intro-path queries ("how are we connected
to this founder?") and connection strength tracking.

Usage:
    from lib.relationship_graph import RelationshipGraph

    graph = RelationshipGraph()  # uses default DB path
    graph.add_relationship(
        person_a={"name": "Alice", "email": "alice@groundup.vc", "role": "team"},
        person_b={"name": "Bob", "email": "bob@startup.com", "role": "founder"},
        rel_type="email_thread",
        context="Series A discussion",
        source="gmail",
    )
    connections = graph.get_connections("bob@startup.com")
    path = graph.get_intro_path("alice@groundup.vc", "charlie@other.com")
"""

import os
import sqlite3
from collections import deque
from datetime import datetime, timezone


DEFAULT_DB_PATH = os.path.join(
    os.environ.get("TOOLKIT_DATA", os.path.expanduser("~/groundup-toolkit/data")),
    "relationship-graph.db",
)


class RelationshipGraph:
    """SQLite-backed relationship graph."""

    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get("RELATIONSHIP_DB", DEFAULT_DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_tables()
        return self._conn

    def _init_tables(self):
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                linkedin_url TEXT,
                company TEXT,
                role TEXT,
                hubspot_contact_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_people_email
                ON people(email) WHERE email IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_people_linkedin
                ON people(linkedin_url) WHERE linkedin_url IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_people_name ON people(name);

            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_a_id INTEGER NOT NULL REFERENCES people(id),
                person_b_id INTEGER NOT NULL REFERENCES people(id),
                rel_type TEXT NOT NULL,
                context TEXT,
                source TEXT,
                strength INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rel_person_a ON relationships(person_a_id);
            CREATE INDEX IF NOT EXISTS idx_rel_person_b ON relationships(person_b_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(rel_type);
        """)
        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # People upsert
    # ------------------------------------------------------------------

    def upsert_person(self, name, email=None, linkedin_url=None,
                      company=None, role=None, hubspot_contact_id=None):
        """Find or create a person. Returns person ID.

        Matches by email first, then linkedin_url, then exact name+company.
        Updates fields if provided and currently NULL.
        """
        conn = self._get_conn()
        now = datetime.now(tz=timezone.utc).isoformat()

        # Try email match
        if email:
            row = conn.execute(
                "SELECT id FROM people WHERE email = ?", (email.lower(),)
            ).fetchone()
            if row:
                self._update_person_fields(row["id"], name, linkedin_url, company, role, hubspot_contact_id, now)
                return row["id"]

        # Try linkedin match
        if linkedin_url:
            row = conn.execute(
                "SELECT id FROM people WHERE linkedin_url = ?", (linkedin_url,)
            ).fetchone()
            if row:
                self._update_person_fields(row["id"], name, email, company, role, hubspot_contact_id, now)
                return row["id"]

        # Try name+company match (avoid creating duplicates for same person at same company)
        if name and company:
            row = conn.execute(
                "SELECT id FROM people WHERE LOWER(name) = LOWER(?) AND LOWER(company) = LOWER(?)",
                (name, company),
            ).fetchone()
            if row:
                self._update_person_fields(row["id"], None, email, linkedin_url, None, hubspot_contact_id, now)
                return row["id"]

        # Create new
        cursor = conn.execute(
            """INSERT INTO people (name, email, linkedin_url, company, role,
                                   hubspot_contact_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, email.lower() if email else None, linkedin_url,
             company, role, hubspot_contact_id, now, now),
        )
        conn.commit()
        return cursor.lastrowid

    def _update_person_fields(self, person_id, name, email_or_linkedin,
                              company_or_linkedin, role, hubspot_contact_id, now):
        """Fill in NULL fields on an existing person record."""
        conn = self._get_conn()
        updates = []
        params = []

        # We use a generic approach: only update if current value is NULL
        fields_to_check = [
            ("email", email_or_linkedin if email_or_linkedin and "@" in str(email_or_linkedin) else None),
            ("linkedin_url", email_or_linkedin if email_or_linkedin and "@" not in str(email_or_linkedin) else None),
            ("company", company_or_linkedin if company_or_linkedin and "linkedin" not in str(company_or_linkedin or "").lower() else None),
            ("role", role),
            ("hubspot_contact_id", hubspot_contact_id),
        ]

        for field, value in fields_to_check:
            if value is not None:
                updates.append(f"{field} = COALESCE({field}, ?)")
                params.append(value.lower() if field == "email" else value)

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(person_id)
            conn.execute(
                f"UPDATE people SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Relationship upsert
    # ------------------------------------------------------------------

    def add_relationship(self, person_a, person_b, rel_type, context=None, source=None):
        """Add or strengthen a relationship between two people.

        Args:
            person_a: dict with at least 'name', optionally 'email', 'linkedin_url',
                      'company', 'role'.
            person_b: same format as person_a.
            rel_type: 'email_thread', 'meeting', 'co_founder', 'advisor',
                      'linkedin_connection', 'recommendation', etc.
            context: free text (deal name, meeting title, company name).
            source: 'gmail', 'calendar', 'linkedin', 'hubspot', 'founder-scout'.

        Returns:
            relationship ID.
        """
        id_a = self.upsert_person(**self._person_kwargs(person_a))
        id_b = self.upsert_person(**self._person_kwargs(person_b))

        # Normalize order so (A,B) and (B,A) are the same edge
        if id_a > id_b:
            id_a, id_b = id_b, id_a

        conn = self._get_conn()
        now = datetime.now(tz=timezone.utc).isoformat()

        # Check for existing edge of same type
        existing = conn.execute(
            """SELECT id, strength FROM relationships
               WHERE person_a_id = ? AND person_b_id = ? AND rel_type = ?""",
            (id_a, id_b, rel_type),
        ).fetchone()

        if existing:
            # Strengthen existing relationship
            conn.execute(
                """UPDATE relationships
                   SET strength = strength + 1, last_seen = ?, context = COALESCE(?, context)
                   WHERE id = ?""",
                (now, context, existing["id"]),
            )
            conn.commit()
            return existing["id"]

        cursor = conn.execute(
            """INSERT INTO relationships
                   (person_a_id, person_b_id, rel_type, context, source, strength, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (id_a, id_b, rel_type, context, source, now, now),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _person_kwargs(person):
        """Extract upsert_person kwargs from a dict."""
        if isinstance(person, str):
            # Treat as email if contains @, else as name
            if "@" in person:
                return {"name": person.split("@")[0], "email": person}
            return {"name": person}
        return {
            "name": person.get("name", "Unknown"),
            "email": person.get("email"),
            "linkedin_url": person.get("linkedin_url"),
            "company": person.get("company"),
            "role": person.get("role"),
            "hubspot_contact_id": person.get("hubspot_contact_id"),
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_person(self, email=None, linkedin_url=None, name=None):
        """Look up a person by email, linkedin_url, or name. Returns dict or None."""
        conn = self._get_conn()
        if email:
            row = conn.execute("SELECT * FROM people WHERE email = ?", (email.lower(),)).fetchone()
            if row:
                return dict(row)
        if linkedin_url:
            row = conn.execute("SELECT * FROM people WHERE linkedin_url = ?", (linkedin_url,)).fetchone()
            if row:
                return dict(row)
        if name:
            row = conn.execute("SELECT * FROM people WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
            if row:
                return dict(row)
        return None

    def get_connections(self, identifier, depth=1):
        """Get all connections for a person.

        Args:
            identifier: email, linkedin_url, or name string.
            depth: how many hops (1 = direct connections only).

        Returns:
            List of dicts: [{person: {...}, rel_type, context, source, strength, first_seen, last_seen}]
        """
        person = self._resolve_person(identifier)
        if not person:
            return []

        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.*, p.id as pid, p.name, p.email, p.linkedin_url, p.company, p.role
               FROM relationships r
               JOIN people p ON p.id = CASE
                   WHEN r.person_a_id = ? THEN r.person_b_id
                   ELSE r.person_a_id
               END
               WHERE r.person_a_id = ? OR r.person_b_id = ?
               ORDER BY r.strength DESC, r.last_seen DESC""",
            (person["id"], person["id"], person["id"]),
        ).fetchall()

        connections = []
        for row in rows:
            connections.append({
                "person": {
                    "id": row["pid"],
                    "name": row["name"],
                    "email": row["email"],
                    "linkedin_url": row["linkedin_url"],
                    "company": row["company"],
                    "role": row["role"],
                },
                "rel_type": row["rel_type"],
                "context": row["context"],
                "source": row["source"],
                "strength": row["strength"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            })

        return connections

    def get_intro_path(self, from_identifier, to_identifier, max_depth=3):
        """Find shortest path between two people via BFS.

        Args:
            from_identifier: email, linkedin_url, or name of start person.
            to_identifier: email, linkedin_url, or name of target person.
            max_depth: maximum hops to search.

        Returns:
            List of dicts representing the path: [{person: {...}, via_rel_type, via_context}]
            Empty list if no path found.
        """
        start = self._resolve_person(from_identifier)
        end = self._resolve_person(to_identifier)
        if not start or not end:
            return []
        if start["id"] == end["id"]:
            return [{"person": start, "via_rel_type": None, "via_context": None}]

        conn = self._get_conn()

        # BFS
        visited = {start["id"]}
        # Queue entries: (person_id, path_so_far)
        queue = deque()
        queue.append((start["id"], [{"person": dict(start), "via_rel_type": None, "via_context": None}]))

        while queue:
            current_id, path = queue.popleft()

            if len(path) > max_depth:
                continue

            # Get neighbors
            neighbors = conn.execute(
                """SELECT r.rel_type, r.context,
                          CASE WHEN r.person_a_id = ? THEN r.person_b_id ELSE r.person_a_id END as neighbor_id
                   FROM relationships r
                   WHERE r.person_a_id = ? OR r.person_b_id = ?""",
                (current_id, current_id, current_id),
            ).fetchall()

            for row in neighbors:
                neighbor_id = row["neighbor_id"]
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)

                neighbor = conn.execute("SELECT * FROM people WHERE id = ?", (neighbor_id,)).fetchone()
                if not neighbor:
                    continue

                new_path = path + [{
                    "person": dict(neighbor),
                    "via_rel_type": row["rel_type"],
                    "via_context": row["context"],
                }]

                if neighbor_id == end["id"]:
                    return new_path

                queue.append((neighbor_id, new_path))

        return []

    def get_stats(self):
        """Return summary stats about the graph."""
        conn = self._get_conn()
        people_count = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        rel_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        type_counts = conn.execute(
            "SELECT rel_type, COUNT(*) as cnt FROM relationships GROUP BY rel_type ORDER BY cnt DESC"
        ).fetchall()
        return {
            "people": people_count,
            "relationships": rel_count,
            "by_type": {row["rel_type"]: row["cnt"] for row in type_counts},
        }

    def _resolve_person(self, identifier):
        """Resolve a string identifier to a person dict."""
        if isinstance(identifier, dict):
            return identifier
        if isinstance(identifier, int):
            conn = self._get_conn()
            row = conn.execute("SELECT * FROM people WHERE id = ?", (identifier,)).fetchone()
            return dict(row) if row else None
        # String: try email, linkedin, name
        return self.get_person(
            email=identifier if "@" in identifier else None,
            linkedin_url=identifier if "linkedin.com" in identifier else None,
            name=identifier if "@" not in identifier and "linkedin.com" not in identifier else None,
        )

    def format_connections_text(self, identifier):
        """Format connections as human-readable text for WhatsApp/notifications."""
        connections = self.get_connections(identifier)
        if not connections:
            return "No known connections."

        lines = []
        for c in connections[:10]:
            p = c["person"]
            strength_str = f" ({c['strength']}x)" if c["strength"] > 1 else ""
            context_str = f" — {c['context']}" if c["context"] else ""
            lines.append(
                f"• {p['name']} ({p.get('company') or p.get('role') or '?'})"
                f" via {c['rel_type']}{strength_str}{context_str}"
            )
        return "\n".join(lines)

    def format_intro_path_text(self, from_id, to_id):
        """Format intro path as human-readable text."""
        path = self.get_intro_path(from_id, to_id)
        if not path:
            return "No connection path found."
        if len(path) == 1:
            return "Direct connection."

        parts = [path[0]["person"]["name"]]
        for step in path[1:]:
            rel = step["via_rel_type"] or "?"
            parts.append(f"→ ({rel}) → {step['person']['name']}")
        return " ".join(parts)
