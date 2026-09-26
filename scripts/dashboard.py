#!/usr/bin/env python3
"""Generate a small, provisioned Grafana dashboard; no credentials or real addresses."""

import json


def dashboard():
    datasource = {'type': 'prometheus', 'uid': 'prometheus'}
    definitions = [
        ('Ready replicas (expected 2)', 'stat', 'sum(portal_ready{job="home-portal"}) or vector(0)', 'short'),
        ('Scrapeable replicas (expected 2)', 'stat', 'sum(up{job="home-portal"}) or vector(0)', 'short'),
        ('Business requests / second', 'timeseries', 'sum(rate(portal_http_requests_total{job="home-portal"}[2m]))', 'reqps'),
        ('Non-200 business requests / second', 'timeseries', 'sum(rate(portal_http_requests_total{job="home-portal",status!="200"}[2m])) or vector(0)', 'reqps'),
        ('Server handling p95 (histogram estimate)', 'timeseries', 'histogram_quantile(0.95, sum by (le) (rate(portal_http_request_duration_seconds_bucket{job="home-portal"}[2m])))', 's'),
        ('Current resident memory / pod', 'timeseries', 'portal_process_resident_memory_bytes{job="home-portal"}', 'bytes'),
        ('CPU cores used / pod', 'timeseries', 'rate(portal_process_cpu_seconds_total{job="home-portal"}[2m])', 'short'),
        ('Running revision / pod', 'table', 'portal_build_info{job="home-portal"}', 'short'),
    ]
    panels = []
    for index, (title, kind, query, unit) in enumerate(definitions):
        panel = {'id': index + 1, 'title': title, 'type': kind, 'datasource': datasource,
                 'gridPos': {'x': (index % 2) * 12, 'y': (index // 2) * 8, 'w': 12, 'h': 8},
                 'fieldConfig': {'defaults': {'unit': unit, 'min': 0}, 'overrides': []},
                 'targets': [{'refId': 'A', 'expr': query, 'legendFormat': '{{pod}}',
                              'instant': kind in ('stat', 'table'), 'format': 'table' if kind == 'table' else 'time_series'}],
                 'options': {}}
        if kind == 'stat':
            panel['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                                'colorMode': 'value', 'graphMode': 'none', 'textMode': 'auto'}
        panels.append(panel)
    return {'uid': 'pi-k3s-home-portal', 'title': 'Pi k3s - home portal', 'schemaVersion': 39,
            'version': 1, 'tags': ['pi-k3s-lab'], 'timezone': 'browser', 'refresh': '15s',
            'time': {'from': 'now-30m', 'to': 'now'}, 'panels': panels,
            'description': 'Single-node lab. Probes and /metrics excluded from business counters. Server p95 is not client p95 or an SLA.'}


if __name__ == '__main__':
    print(json.dumps(dashboard(), indent=2))
