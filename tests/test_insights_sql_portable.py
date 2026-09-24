#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_insights_sql_portable.py
# Description: The battery-trend and room-temperature insight queries compared
#              a column with "" — a double-quoted IDENTIFIER, which SQLite
#              tolerates by falling back to a string literal and PostgreSQL
#              rejects as zero-length. On a Postgres history both insights
#              never appeared. The portable form is CAST(col AS TEXT) != ''.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0

import ast
import re
import sqlite3

from conftest import plugin_source_files

_EMPTY_IDENT = re.compile(r'(!=|<>|=)\s*""')


def _string_pieces():
    for path in plugin_source_files():
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield path, node.lineno, node.value


def test_no_sql_compares_with_an_empty_identifier():
    bad = [(p.rsplit("/", 1)[-1], line, text) for p, line, text in _string_pieces()
           if _EMPTY_IDENT.search(text)]
    assert not bad, f'"" is an identifier in PostgreSQL, not an empty string: {bad}'


def test_the_insight_queries_use_the_portable_filter():
    src = "".join(open(p, encoding="utf-8").read() for p in plugin_source_files()
                  if p.endswith("insights_mixin.py"))
    assert src.count('CAST("{col}" AS TEXT) != \\\'\\\'') == 2


def test_the_portable_filter_still_drops_blanks_on_sqlite():
    db = sqlite3.connect(":memory:")
    db.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, "v" TEXT)')
    db.executemany('INSERT INTO t ("v") VALUES (?)', [("12.5",), ("",), (None,), ("7",)])
    rows = db.execute('SELECT "v" FROM t WHERE "v" IS NOT NULL AND CAST("v" AS TEXT) != \'\' '
                      'ORDER BY id').fetchall()
    assert rows == [("12.5",), ("7",)]
