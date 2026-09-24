#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_config_secure.py
# Description: Every credential field in the Configure dialog is masked
#              (review 24-09-2026 [29]). pgPassword showed in clear, so a
#              screenshot posted with a help request carried the password.
#              secure="true" masks the field; it does not encrypt the pref.
# Author:      CliveS & Claude Opus 5.5
# Date:        24-09-2026
# Version:     1.0
import os
import re
import xml.etree.ElementTree as ET

from conftest import SP

SECRET_WORDS = re.compile(r"(pass|password|apikey|token|secret)$", re.IGNORECASE)


def test_every_credential_field_is_masked():
    root = ET.parse(os.path.join(SP, "PluginConfig.xml")).getroot()
    fields = [f for f in root.iter("Field") if f.get("type") == "textfield"]
    creds = [f.get("id") for f in fields if SECRET_WORDS.search(f.get("id") or "")]
    assert "pgPassword" in creds and "indigoApiKey" in creds, creds
    bare = [f.get("id") for f in fields
            if f.get("id") in creds and f.get("secure") != "true"]
    assert bare == [], f"credential fields shown in clear: {bare}"
