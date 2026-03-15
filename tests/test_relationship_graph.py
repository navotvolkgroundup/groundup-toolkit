"""Tests for lib/relationship_graph.py — central relationship graph store."""

import os
import tempfile
import pytest

from lib.relationship_graph import RelationshipGraph


@pytest.fixture
def graph(tmp_path):
    db_path = str(tmp_path / "test-relationships.db")
    g = RelationshipGraph(db_path=db_path)
    yield g
    g.close()


# ------------------------------------------------------------------
# Person upsert
# ------------------------------------------------------------------

class TestUpsertPerson:
    def test_create_new_person(self, graph):
        pid = graph.upsert_person("Alice", email="alice@example.com")
        assert pid is not None
        person = graph.get_person(email="alice@example.com")
        assert person["name"] == "Alice"
        assert person["email"] == "alice@example.com"

    def test_dedup_by_email(self, graph):
        id1 = graph.upsert_person("Alice", email="alice@example.com")
        id2 = graph.upsert_person("Alice Smith", email="alice@example.com")
        assert id1 == id2

    def test_dedup_by_linkedin(self, graph):
        id1 = graph.upsert_person("Bob", linkedin_url="https://linkedin.com/in/bob")
        id2 = graph.upsert_person("Robert", linkedin_url="https://linkedin.com/in/bob")
        assert id1 == id2

    def test_dedup_by_name_and_company(self, graph):
        id1 = graph.upsert_person("Charlie", company="Acme Corp")
        id2 = graph.upsert_person("Charlie", company="Acme Corp")
        assert id1 == id2

    def test_different_people_same_name_different_company(self, graph):
        id1 = graph.upsert_person("Charlie", company="Acme Corp")
        id2 = graph.upsert_person("Charlie", company="Other Inc")
        assert id1 != id2

    def test_fills_null_fields_on_match(self, graph):
        graph.upsert_person("Alice", email="alice@example.com")
        graph.upsert_person("Alice", email="alice@example.com", company="Acme")
        person = graph.get_person(email="alice@example.com")
        assert person["company"] == "Acme"

    def test_email_case_insensitive(self, graph):
        id1 = graph.upsert_person("Alice", email="Alice@Example.COM")
        id2 = graph.upsert_person("Alice", email="alice@example.com")
        assert id1 == id2


# ------------------------------------------------------------------
# Relationships
# ------------------------------------------------------------------

class TestRelationships:
    def test_add_relationship(self, graph):
        rel_id = graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@groundup.vc", "role": "team"},
            person_b={"name": "Bob", "email": "bob@startup.com", "role": "founder"},
            rel_type="email_thread",
            context="Series A discussion",
            source="gmail",
        )
        assert rel_id is not None

    def test_relationship_strengthens_on_repeat(self, graph):
        graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@vc.com"},
            person_b={"name": "Bob", "email": "bob@startup.com"},
            rel_type="email_thread",
            source="gmail",
        )
        graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@vc.com"},
            person_b={"name": "Bob", "email": "bob@startup.com"},
            rel_type="email_thread",
            source="gmail",
        )
        connections = graph.get_connections("alice@vc.com")
        assert len(connections) == 1
        assert connections[0]["strength"] == 2

    def test_different_rel_types_separate_edges(self, graph):
        graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@vc.com"},
            person_b={"name": "Bob", "email": "bob@startup.com"},
            rel_type="email_thread",
        )
        graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@vc.com"},
            person_b={"name": "Bob", "email": "bob@startup.com"},
            rel_type="meeting",
        )
        connections = graph.get_connections("alice@vc.com")
        assert len(connections) == 2

    def test_relationship_order_normalized(self, graph):
        """(A,B) and (B,A) should be the same edge."""
        graph.add_relationship(
            person_a={"name": "Alice", "email": "alice@vc.com"},
            person_b={"name": "Bob", "email": "bob@startup.com"},
            rel_type="email_thread",
        )
        graph.add_relationship(
            person_a={"name": "Bob", "email": "bob@startup.com"},
            person_b={"name": "Alice", "email": "alice@vc.com"},
            rel_type="email_thread",
        )
        connections = graph.get_connections("alice@vc.com")
        assert len(connections) == 1
        assert connections[0]["strength"] == 2

    def test_string_shorthand(self, graph):
        """Can pass email string instead of dict."""
        graph.add_relationship(
            person_a="alice@vc.com",
            person_b="bob@startup.com",
            rel_type="email_thread",
        )
        connections = graph.get_connections("alice@vc.com")
        assert len(connections) == 1


# ------------------------------------------------------------------
# Queries
# ------------------------------------------------------------------

class TestQueries:
    def test_get_connections_empty(self, graph):
        assert graph.get_connections("nobody@example.com") == []

    def test_get_connections_sorted_by_strength(self, graph):
        graph.add_relationship("alice@vc.com", "bob@startup.com", "email_thread")
        graph.add_relationship("alice@vc.com", "bob@startup.com", "email_thread")
        graph.add_relationship("alice@vc.com", "charlie@other.com", "email_thread")
        connections = graph.get_connections("alice@vc.com")
        assert len(connections) == 2
        assert connections[0]["person"]["email"] == "bob@startup.com"
        assert connections[0]["strength"] == 2

    def test_get_person_by_name(self, graph):
        graph.upsert_person("Alice Smith", email="alice@example.com")
        person = graph.get_person(name="Alice Smith")
        assert person is not None
        assert person["email"] == "alice@example.com"

    def test_get_person_not_found(self, graph):
        assert graph.get_person(email="nobody@example.com") is None


# ------------------------------------------------------------------
# Intro path
# ------------------------------------------------------------------

class TestIntroPath:
    def test_direct_connection(self, graph):
        graph.add_relationship("alice@vc.com", "bob@startup.com", "email_thread")
        path = graph.get_intro_path("alice@vc.com", "bob@startup.com")
        assert len(path) == 2
        assert path[0]["person"]["email"] == "alice@vc.com"
        assert path[1]["person"]["email"] == "bob@startup.com"

    def test_two_hop_path(self, graph):
        graph.add_relationship("alice@vc.com", "bob@middle.com", "email_thread")
        graph.add_relationship("bob@middle.com", "charlie@target.com", "meeting")
        path = graph.get_intro_path("alice@vc.com", "charlie@target.com")
        assert len(path) == 3
        assert path[0]["person"]["email"] == "alice@vc.com"
        assert path[1]["person"]["email"] == "bob@middle.com"
        assert path[2]["person"]["email"] == "charlie@target.com"
        assert path[2]["via_rel_type"] == "meeting"

    def test_no_path(self, graph):
        graph.add_relationship("alice@vc.com", "bob@startup.com", "email_thread")
        graph.add_relationship("charlie@other.com", "dave@another.com", "meeting")
        path = graph.get_intro_path("alice@vc.com", "charlie@other.com")
        assert path == []

    def test_same_person(self, graph):
        graph.upsert_person("Alice", email="alice@vc.com")
        path = graph.get_intro_path("alice@vc.com", "alice@vc.com")
        assert len(path) == 1

    def test_unknown_person(self, graph):
        path = graph.get_intro_path("nobody@x.com", "nobody2@x.com")
        assert path == []

    def test_max_depth_respected(self, graph):
        graph.add_relationship("a@x.com", "b@x.com", "email_thread")
        graph.add_relationship("b@x.com", "c@x.com", "email_thread")
        graph.add_relationship("c@x.com", "d@x.com", "email_thread")
        graph.add_relationship("d@x.com", "e@x.com", "email_thread")
        # 4-hop path, but max_depth=3
        path = graph.get_intro_path("a@x.com", "e@x.com", max_depth=3)
        assert path == []
        # 4-hop with higher max
        path = graph.get_intro_path("a@x.com", "e@x.com", max_depth=5)
        assert len(path) == 5


# ------------------------------------------------------------------
# Stats & formatting
# ------------------------------------------------------------------

class TestStatsAndFormatting:
    def test_stats_empty(self, graph):
        stats = graph.get_stats()
        assert stats["people"] == 0
        assert stats["relationships"] == 0

    def test_stats_with_data(self, graph):
        graph.add_relationship("alice@vc.com", "bob@startup.com", "email_thread")
        graph.add_relationship("alice@vc.com", "charlie@other.com", "meeting")
        stats = graph.get_stats()
        assert stats["people"] == 3
        assert stats["relationships"] == 2
        assert stats["by_type"]["email_thread"] == 1
        assert stats["by_type"]["meeting"] == 1

    def test_format_connections_text(self, graph):
        graph.add_relationship(
            {"name": "Alice", "email": "alice@vc.com", "company": "GroundUp"},
            {"name": "Bob", "email": "bob@startup.com", "company": "StartupCo"},
            "email_thread",
            context="Deal discussion",
        )
        text = graph.format_connections_text("alice@vc.com")
        assert "Bob" in text
        assert "email_thread" in text

    def test_format_connections_empty(self, graph):
        text = graph.format_connections_text("nobody@x.com")
        assert text == "No known connections."

    def test_format_intro_path_text(self, graph):
        graph.add_relationship("alice@vc.com", "bob@middle.com", "email_thread")
        graph.add_relationship("bob@middle.com", "charlie@target.com", "meeting")
        text = graph.format_intro_path_text("alice@vc.com", "charlie@target.com")
        assert "alice" in text.lower()
        assert "charlie" in text.lower()
        assert "→" in text

    def test_format_intro_path_no_connection(self, graph):
        text = graph.format_intro_path_text("a@x.com", "b@x.com")
        assert "No connection" in text
