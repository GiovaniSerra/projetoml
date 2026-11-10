import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')
load_dotenv()


def subnet(cidr):
    n = ipaddress.ip_network(cidr, strict=True)
    return [str(n.network_address), str(n.netmask)]


def plan(c):
    name = c['tunnel_name']
    local, remote = subnet(c['local_subnet']), subnet(c['remote_subnet'])
    psk = os.getenv('VPN_PSK')
    if not psk:
        raise ValueError('VPN_PSK missing from environment')
    return [
        ('vpn.ipsec/phase1-interface', name, {
            'name': name, 'interface': c['wan_interface'], 'type': 'static',
            'remote-gw': c['peer_public_ip'], 'ike-version': '2',
            'authmethod': 'psk', 'psksecret': psk,
            'proposal': 'des-sha256', 'dhgrp': '14', 'keylife': 28800,
        }),
        ('system/interface', name, {
    'ip': '169.255.1.1/32',
    'allowaccess': 'ping',
}),
('vpn.ipsec/phase2-interface', name + '_P2', {
            'name': name + '_P2', 'phase1name': name,
            'proposal': 'des-sha256', 'pfs': 'enable', 'dhgrp': '14',
            'keylifeseconds': 3600,
            # Route-based VPN: broad selectors; align PAN-OS proxy-ID/traffic selectors.
        }),
        ('router/static', None, {
            'dst': c['remote_subnet'],
            'device': name,
            'distance': 10,
            'status': 'enable',
            'comment': 'VPN-ML automation route'
        }),
        ('firewall/address', 'VPN_LOCAL_LAN', {
            'name': 'VPN_LOCAL_LAN', 'type': 'ipmask', 'subnet': c['local_subnet']
        }),
        ('firewall/address', 'VPN_REMOTE_LAN', {
            'name': 'VPN_REMOTE_LAN', 'type': 'ipmask', 'subnet': c['remote_subnet']
        }),
        ('firewall/policy', None, {
            'name': 'VPN_TO_PALO_ALTO',
            'srcintf': [{'name': c['lan_interface']}],
            'dstintf': [{'name': name}],
            'srcaddr': [{'name': 'VPN_LOCAL_LAN'}],
            'dstaddr': [{'name': 'VPN_REMOTE_LAN'}],
            'action': 'accept', 'schedule': 'always',
            'service': [{'name': 'ALL'}], 'nat': 'disable', 'logtraffic': 'all'
        }),
        ('firewall/policy', None, {
            'name': 'VPN_FROM_PALO_ALTO',
            'srcintf': [{'name': name}],
            'dstintf': [{'name': c['lan_interface']}],
            'srcaddr': [{'name': 'VPN_REMOTE_LAN'}],
            'dstaddr': [{'name': 'VPN_LOCAL_LAN'}],
            'action': 'accept', 'schedule': 'always',
            'service': [{'name': 'ALL'}], 'nat': 'disable', 'logtraffic': 'all'
        }),
    ]


class API:
    def __init__(self, c):
        host = os.getenv('FG_HOST') or os.getenv('FORTIGATE_HOST')
        token = os.getenv('FG_API_TOKEN') or os.getenv('FORTIGATE_API_TOKEN')
        if not host or not token:
            raise ValueError('FG_HOST/FG_API_TOKEN not configured')
        self.base = (host if host.startswith('https://') else 'https://' + host).rstrip('/')
        self.vdom = c.get('vdom', 'root')
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'Bearer ' + token,
                                     'Accept': 'application/json'})
        ca = os.getenv('FG_CA_BUNDLE')
        self.session.verify = ca if ca else False  # isolated self-signed lab only

    def call(self, method, path, key=None, payload=None):
        url = f'{self.base}/api/v2/cmdb/{path}'
        if key is not None:
            url += '/' + quote(str(key), safe='')
        r = self.session.request(method, url, params={'vdom': self.vdom},
                                 json=payload, timeout=20)
        if not r.ok:
            print(f"HTTP STATUS: {r.status_code}")
            print(f"METHOD: {method}")
            print(f"ENDPOINT: {path}")
            print(f"RESPONSE: {r.text[:2000]}")
            r.raise_for_status()
        data = r.json()
        if data.get('status') != 'success' or data.get('http_status', 200) >= 400:
            raise RuntimeError(f'{method} {path} rejected: {data.get("error", data.get("status"))}')
        return data

    def list(self, path):
        return self.call('GET', path).get('results', [])


def matched(path, key, payload, items):
    if path == 'router/static':
        import ipaddress
        def normalize(value):
            if isinstance(value, list) and len(value) == 2:
                return ipaddress.ip_network(
                    f"{value[0]}/{value[1]}", strict=False
                )
            if isinstance(value, str):
                return ipaddress.ip_network(
                    value.replace(" ", "/"), strict=False
                )
            return None
        desired_network = normalize(payload['dst'])
        return [
            x for x in items
            if x.get('device') == payload['device']
            and normalize(x.get('dst')) == desired_network
        ]
    if path == 'firewall/policy':
        return [x for x in items if x.get('name') == payload['name']]
    return [x for x in items if x.get('name') == key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--mode', choices=['preview', 'inventory', 'apply'], required=True)
    ap.add_argument('--confirm', action='store_true')
    ap.add_argument('--step', choices=['phase1', 'interface', 'phase2', 'route', 'addresses', 'policies'], help='Apply or inspect only the selected stage')
    args = ap.parse_args()
    if args.mode == 'apply' and not args.step:
        ap.error('apply requires --step to prevent bulk writes')
    c = json.loads(Path(args.config).read_text(encoding='utf-8'))
    ops = plan(c)
    stages = {
        'phase1': [0], 'interface': [1], 'phase2': [2],
        'route': [3], 'addresses': [4, 5], 'policies': [6, 7],
    }
    if args.step:
        ops = [ops[i] for i in stages[args.step]]
    if args.mode == 'preview':
        for path, key, payload in ops:
            safe = dict(payload)
            if 'psksecret' in safe:
                safe['psksecret'] = '<REDACTED>'
            print(json.dumps({'endpoint': path, 'key': key, 'payload': safe}, indent=2))
        print('PREVIEW ONLY: field representations must be confirmed on device.')
        return

    api = API(c)
    paths = list(dict.fromkeys(p for p, _, _ in ops))
    snapshots = {path: api.list(path) for path in paths}
    for path, key, payload in ops:
        matches = matched(path, key, payload, snapshots[path])
        print(('EXISTS' if matches else 'ABSENT'), path, key or payload.get('name') or payload.get('dst'))

    if args.mode == 'inventory':
        return
    if not args.confirm:
        ap.error('apply requires --confirm')
        
    if args.step == "interface":
        if not any(
            matched(path, key, payload, snapshots[path])
            for path, key, payload in ops
        ):
            raise RuntimeError(
                "ABORT: VPN interface does not exist. Create Phase 1 first."
            )
    else:
        if any(
            matched(path, key, payload, snapshots[path])
            for path, key, payload in ops
        ):
            raise RuntimeError(
                "ABORT: managed object already exists; no writes performed"
            )

    backup_dir = Path('backups')
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outfile = backup_dir / f'fortigate_cmdb_snapshot_{stamp}.json'
    # Snapshots may include sensitive configuration: redact secrets and restrict access.
    def redact(value):
        if isinstance(value, dict):
            return {k: ('<REDACTED>' if any(secret in k.lower() for secret in ('psk', 'password', 'secret', 'token', 'private-key')) else redact(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value
    outfile.write_text(json.dumps(redact(snapshots), indent=2), encoding='utf-8')
    try:
        outfile.chmod(0o600)
    except OSError:
        pass
    print('CMDB snapshot saved:', outfile)
    print('WARNING: This is not a full FortiGate configuration backup.')
    print('WARNING: API operations are not transactional. Partial writes may remain on error.')
    for path, key, payload in ops:
        if path == 'system/interface':
            api.call('PUT', path, key=key, payload=payload)
        else:
            api.call('POST', path, payload=payload)
        print('APPLIED', path, key or payload.get('name') or payload.get('dst'))
    print('Stage complete. Verify the created objects and their fields before the next stage.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, requests.RequestException) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)

