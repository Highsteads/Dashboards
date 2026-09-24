#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_actions_xml_comments.py
# Description: Each endpoint comment in Actions.xml sits above the action it
#              describes (review 24-09-2026 [80]). Two blocks had drifted
#              above the wrong action and three routes had none, which misled
#              anyone reading the public repo's endpoint list.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import os
import re

from conftest import SP

TEXT = open(os.path.join(SP, "Actions.xml"), encoding="utf-8").read()
ROUTE = re.compile(r"<!--\s*POST /message/com\.clives\.indigoplugin\.dashboards/(\w+)/")
ACTION = re.compile(r'<Action id="(\w+)"')


def test_every_route_comment_names_the_action_below_it():
    wrong = []
    for m in ROUTE.finditer(TEXT):
        nxt = ACTION.search(TEXT, m.end())
        if not nxt or nxt.group(1) != m.group(1):
            wrong.append((m.group(1), nxt.group(1) if nxt else None))
    assert wrong == [], wrong


def test_every_action_has_a_comment_above_it():
    """Directly above it, or a shared comment for a pair that names it."""
    bare = []
    for m in ACTION.finditer(TEXT):
        before = TEXT[:m.start()].rstrip()
        if before.endswith("-->"):
            continue
        start = before.rfind("<!--")
        comment = before[start:before.find("-->", start)] if start >= 0 else ""
        if m.group(1) not in comment:
            bare.append(m.group(1))
    assert bare == [], bare
