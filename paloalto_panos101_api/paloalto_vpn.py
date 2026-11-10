#!/usr/bin/env python3
"""PAN-OS 10.1 XML API lab automation: preview, backup, apply, validate, commit."""
import argparse
import ipaddress
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from dotenv import load_dotenv
import requests

load_dotenv()

ROOT = "/config/devices/entry[@name='localhost.localdomain']"

def e(v):
    return escape(str(v), {'"': '&quot;', "'": '&apos;'})

def entry(name, body):
    return f'<entry name="{e(name)}">{body}</entry>'

def member(value):
    return f'<member>{e(value)}</member>'

def node(path, value):
    return f'<{path}>{e(value)}</{path}>'

def validate_config(c):
    required = ['management_ip','wan_interface','wan_ip','peer_wan_ip','local_subnet',
                'remote_subnet','tunnel_interface','tunnel_ip','virtual_router',
                'lan_zone','vpn_zone','vsys','psk']
    missing = [k for k in required if not c.get(k)]
    if missing: raise ValueError('Missing fields: ' + ', '.join(missing))
    for k in ('management_ip','wan_ip','peer_wan_ip'):
        ipaddress.ip_address(c[k])
    for k in ('local_subnet','remote_subnet','tunnel_ip'):
        ipaddress.ip_interface(c[k]) if k == 'tunnel_ip' else ipaddress.ip_network(c[k], strict=False)
    if not re.fullmatch(r'tunnel\.\d+', c['tunnel_interface']):
        raise ValueError('tunnel_interface must be tunnel.N')
    if c['psk'] == 'CHANGE_ME' or len(c['psk']) < 12:
        raise ValueError('Set a strong PSK via VPN_PSK (at least 12 characters)')
    for k in ('wan_interface','virtual_router','lan_zone','vpn_zone','vsys'):
        if not re.fullmatch(r'[A-Za-z0-9_.\-/]+', c[k]):
            raise ValueError('Invalid characters in ' + k)

def operations(c):
    network = ROOT + '/network'
    vsys = ROOT + f"/vsys/entry[@name='{c['vsys']}']"
    tunnel = c['tunnel_interface']
    p1 = 'AUTO-IKE-FGT'
    p2 = 'AUTO-IPSEC-FGT'
    ike = 'AUTO-GW-FGT'
    vpn = 'AUTO-VPN-FGT'
    route = 'AUTO-ROUTE-FGT'
    address_local, address_remote = 'AUTO-LAN-PA', 'AUTO-LAN-FGT'
    out = []
    def add(name, xpath, xml): out.append((name, xpath, xml))
    add('IKE crypto profile', network+f"/ike/crypto-profiles/ike-crypto-profiles/entry[@name='{p1}']",
        '<encryption>'+member('des')+'</encryption><hash>'+member('sha256')+'</hash>'
        '<dh-group>'+member('group14')+'</dh-group><lifetime><hours>8</hours></lifetime>')
    add('IPSec crypto profile', network+f"/ike/crypto-profiles/ipsec-crypto-profiles/entry[@name='{p2}']",
        '<esp><encryption>'+member('des')+'</encryption><authentication>'+member('sha256')+'</authentication></esp>'
        '<dh-group>group14</dh-group><lifetime><hours>1</hours></lifetime>')
    add('Tunnel interface', network+f"/interface/tunnel/units/entry[@name='{tunnel}']",
        '<ip>'+entry(c['tunnel_ip'], '')+'</ip><comment>Managed by lab automation</comment>')
    add('VPN zone', vsys+f"/zone/entry[@name='{c['vpn_zone']}']",
        '<network><layer3>'+member(tunnel)+'</layer3></network>')
    add('VSYS interface membership', vsys+'/import/network/interface', member(tunnel))
    add('Virtual router interface membership', network+f"/virtual-router/entry[@name='{c['virtual_router']}']/interface", member(tunnel))
    add('IKE gateway', network+f"/ike/gateway/entry[@name='{ike}']",
        '<authentication><pre-shared-key><key>'+e(c['psk'])+'</key></pre-shared-key></authentication>'
        '<protocol><version>ikev2</version><ikev2><ike-crypto-profile>'+p1+'</ike-crypto-profile></ikev2></protocol>'
        '<protocol-common><nat-traversal><enable>no</enable></nat-traversal></protocol-common>'
        '<local-address><interface>'+e(c['wan_interface'])+'</interface><ip>'+e(c['wan_ip'] + '/30')+'</ip></local-address>'
        '<peer-address><ip>'+e(c['peer_wan_ip'])+'</ip></peer-address>')
    add('IPSec tunnel', network+f"/tunnel/ipsec/entry[@name='{vpn}']",
        '<tunnel-interface>'+e(tunnel)+'</tunnel-interface><auto-key><ike-gateway>'+entry(ike, '')+'</ike-gateway>'
        '<ipsec-crypto-profile>'+p2+'</ipsec-crypto-profile></auto-key>')
    add('Static route', network+f"/virtual-router/entry[@name='{c['virtual_router']}']/routing-table/ip/static-route/entry[@name='{route}']",
        '<destination>'+e(c['remote_subnet'])+'</destination><interface>'+e(tunnel)+'</interface><metric>10</metric>')
    add('Local address', vsys+f"/address/entry[@name='{address_local}']", '<ip-netmask>'+e(c['local_subnet'])+'</ip-netmask>')
    add('Remote address', vsys+f"/address/entry[@name='{address_remote}']", '<ip-netmask>'+e(c['remote_subnet'])+'</ip-netmask>')
    rules = vsys+'/rulebase/security/rules'
    def rule(name, source_zone, dest_zone, source, dest):
        body = ('<from>'+member(source_zone)+'</from><to>'+member(dest_zone)+'</to>'
                '<source>'+member(source)+'</source><destination>'+member(dest)+'</destination>'
                '<source-user>'+member('any')+'</source-user><category>'+member('any')+'</category>'
                '<application>'+member('any')+'</application><service>'+member('any')+'</service>'
                '<action>allow</action><log-end>yes</log-end>')
        add(name, rules+f"/entry[@name='{name}']", body)
    rule('AUTO-PA-TO-FGT', c['lan_zone'], c['vpn_zone'], address_local, address_remote)
    rule('AUTO-FGT-TO-PA', c['vpn_zone'], c['lan_zone'], address_remote, address_local)
    return out

class Client:
    def __init__(self, c, key):
        self.url = f"https://{c['management_ip']}/api/"
        self.key = key
        self.session = requests.Session()
        self.session.verify = c.get('ca_bundle', False)
        self.timeout = 25
    def request(self, **params):
        response = self.session.post(self.url, headers={'X-PAN-KEY': self.key},
                                     data=params, timeout=self.timeout)
        response.raise_for_status()
        try: root = ET.fromstring(response.content)
        except ET.ParseError as ex: raise RuntimeError('Invalid XML API response') from ex
        if root.attrib.get('status') != 'success':
            msg = ' '.join((root.findtext('.//msg/line') or root.findtext('.//msg') or 'API error').split())
            raise RuntimeError(f'PAN-OS API error: {msg}')
        return root
    def exists(self, xpath):
        try:
            root = self.request(type='config', action='get', xpath=xpath)
            return root.find('./result') is not None and len(root.find('./result')) > 0
        except RuntimeError as exc:
            if 'does not exist' in str(exc).lower() or 'not present' in str(exc).lower(): return False
            raise
    def backup(self):
        root = self.request(type='config', action='show', xpath='/config')
        result = root.find('result')
        if result is None or len(result) == 0: raise RuntimeError('Empty configuration backup')
        directory = Path('backups'); directory.mkdir(exist_ok=True)
        path = directory / ('panos_config_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.xml')
        path.write_bytes(ET.tostring(result[0], encoding='utf-8', xml_declaration=True))
        try: path.chmod(0o600)
        except OSError: pass
        return path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--mode', choices=['preview','apply','validate','commit'], default='preview')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    c = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    c['psk'] = os.environ.get('VPN_PSK', '')
    validate_config(c)
    ops = operations(c)
    if args.mode == 'preview':
        for name, xpath, xml in ops:
            print(f'[{name}] xpath={xpath}')
            print('  XML: [REDACTED: contains PSK]' if name == 'IKE gateway' else '  XML: '+xml)
        return
    key = os.environ.get('PAN_API_KEY')
    if not key: raise ValueError('PAN_API_KEY environment variable required')
    client = Client(c, key)
    if args.mode == 'validate':
        failures = []
        for name, xpath, _ in ops:
            found = client.exists(xpath)
            print(('OK' if found else 'MISSING')+' '+name)
            if not found: failures.append(name)
        if failures: raise RuntimeError('Missing configuration objects: '+', '.join(failures))
        print('Objects exist in candidate configuration. This does not verify values, commit or live SAs.')
        return
    if not args.confirm: raise ValueError('--confirm is required for changes')
    if args.mode == 'commit':
        root = client.request(type='commit', cmd='<commit></commit>')
        print('Commit requested:', ET.tostring(root.find('result'), encoding='unicode') if root.find('result') is not None else 'API accepted')
        print('Check job status before claiming commit success.')
        return
    backup = client.backup()
    print('Pre-change backup:', backup)
    for name, xpath, xml in ops:
        if client.exists(xpath):
            print('SKIP existing object:', name)
            continue
            
        if "/entry[@name='" in xpath and xpath.endswith("']"):
            parent_xpath, object_name = xpath.rsplit(
                "/entry[@name='", 1
            )
            object_name = object_name[:-2]
            client.request(
                type='config',
                action='set',
                xpath=parent_xpath,
                element=entry(object_name, xml)
            )
        else:
            client.request(
                type='config',
                action='set',
                xpath=xpath,
                element=xml
            )
        print('CREATED:', name)
    print('Candidate updated. Review diff and validate before separate --mode commit.')

if __name__ == '__main__':
    try: main()
    except (ValueError, RuntimeError, requests.RequestException, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)