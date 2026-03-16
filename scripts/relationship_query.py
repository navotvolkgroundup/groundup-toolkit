#!/usr/bin/env python3
"""Query the relationship graph from the command line.

Usage:
    python3 scripts/relationship_query.py connections <email_or_name>
    python3 scripts/relationship_query.py intro-path <from> <to>
    python3 scripts/relationship_query.py stats
    python3 scripts/relationship_query.py --json connections <email_or_name>
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.relationship_graph import RelationshipGraph


def cmd_connections(graph, identifier, as_json=False):
    connections = graph.get_connections(identifier)
    if as_json:
        print(json.dumps(connections, indent=2, default=str))
        return
    if not connections:
        print(f"No connections found for '{identifier}'.")
        return
    print(f"Connections for '{identifier}' ({len(connections)} total):\n")
    for c in connections:
        p = c['person']
        strength = f" ({c['strength']}x)" if c['strength'] > 1 else ""
        ctx = f" — {c['context']}" if c['context'] else ""
        company = f" @ {p['company']}" if p.get('company') else ""
        print(f"  {p['name']}{company} [{c['rel_type']}]{strength}{ctx}")
        print(f"    Source: {c['source'] or '?'} | First: {c['first_seen'][:10]} | Last: {c['last_seen'][:10]}")


def cmd_intro_path(graph, from_id, to_id, as_json=False):
    path = graph.get_intro_path(from_id, to_id)
    if as_json:
        print(json.dumps(path, indent=2, default=str))
        return
    if not path:
        print(f"No connection path found between '{from_id}' and '{to_id}'.")
        return
    print(f"Intro path ({len(path) - 1} hop{'s' if len(path) > 2 else ''}):\n")
    for i, step in enumerate(path):
        p = step['person']
        if i == 0:
            print(f"  {p['name']} ({p.get('email') or p.get('company') or '?'})")
        else:
            rel = step['via_rel_type'] or '?'
            ctx = f" [{step['via_context']}]" if step.get('via_context') else ""
            print(f"  → ({rel}{ctx}) → {p['name']} ({p.get('email') or p.get('company') or '?'})")


def cmd_stats(graph, as_json=False):
    stats = graph.get_stats()
    if as_json:
        print(json.dumps(stats, indent=2))
        return
    print(f"People: {stats['people']}")
    print(f"Relationships: {stats['relationships']}")
    if stats['by_type']:
        print("By type:")
        for t, count in stats['by_type'].items():
            print(f"  {t}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Query the relationship graph")
    parser.add_argument('--json', action='store_true', help="Output as JSON")
    sub = parser.add_subparsers(dest='command')

    conn_parser = sub.add_parser('connections', help="Show connections for a person")
    conn_parser.add_argument('identifier', help="Email, LinkedIn URL, or name")

    path_parser = sub.add_parser('intro-path', help="Find intro path between two people")
    path_parser.add_argument('from_id', help="Start person (email/name)")
    path_parser.add_argument('to_id', help="Target person (email/name)")

    search_parser = sub.add_parser('search', help="Search people by partial name/email")
    search_parser.add_argument('query', help="Search query")

    sub.add_parser('stats', help="Show graph statistics")

    args = parser.parse_args()
    graph = RelationshipGraph()

    try:
        if args.command == 'connections':
            cmd_connections(graph, args.identifier, as_json=args.json)
        elif args.command == 'intro-path':
            cmd_intro_path(graph, args.from_id, args.to_id, as_json=args.json)
        elif args.command == 'search':
            results = graph.search_people(args.query)
            if args.json:
                print(json.dumps(results, indent=2, default=str))
            elif not results:
                print(f"No people found matching '{args.query}'.")
            else:
                print(f"Found {len(results)} match(es) for '{args.query}':\n")
                for p in results:
                    company = f" @ {p['company']}" if p.get('company') else ""
                    print(f"  {p['name']}{company} — {p.get('email') or 'no email'}")
        elif args.command == 'stats':
            cmd_stats(graph, as_json=args.json)
        else:
            parser.print_help()
    finally:
        graph.close()


if __name__ == '__main__':
    main()
