#!/usr/bin/env python3
"""Render the live image/config references into kubectl's JSON representation."""

import json
import sys

deployment = json.load(sys.stdin)
pod = deployment["spec"]["template"]["spec"]
pod["containers"][0]["image"] = sys.argv[1]
pod["containers"][0]["imagePullPolicy"] = sys.argv[3]
pod["volumes"][0]["configMap"]["name"] = sys.argv[2]
json.dump(deployment, sys.stdout)
