#!/usr/bin/env python3
"""PAN-OS 10.1 XML API VPN automation. Safe by default: drift blocks writes."""
import argparse
import ipaddress
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import requests
from dotenv import load_dotenv

load_dotenv()
ROOT = "/config/devices/entry[@name='localhost.localdomain']"


def esc(value):
    return escape(str(value), {'"': '&quot;', "'": '&apos;'})


def entry(name, body):
    return f'<entry name="{esc(name)}">{body}</entry>'


def member(value):
    return f'<member>{esc(value)}</member>'


def validate_config(c):
    required = ('management_ip', 'wan_interface', 'wan_ip', 'peer_wan_ip',
                'local_subnet', 'remote_subnet', 'tunnel_interface', 'tunnel_ip',
                'virtual_router', 'lan_zone', 'vpn_zone', 'vsys', 'psk')
    missing = [key for key in required if not c.get(key)]
    if missing:
        raise ValueError('Missing fields: ' + ', '.join(missing))
    for key in ('management_ip', 'peer_wan_ip'):
        ipaddress.ip_address(c[key])
    ipaddress.ip_interface(c['wan_ip'])
    for key in ('local_subnet', 'remote_subnet'):
        ipaddress.ip_network(c[key], strict=True)
    ipaddress.ip_interface(c['tunnel_ip'])
    if not re.fullmatch(r'tunnel\.\d+', c['tunnel_interface']):
        raise ValueError('tunnel_interface must be tunnel.N')
    if c['psk'] == 'CHANGE_ME' or len(c['psk']) < 12:
        raise ValueError('VPN_PSK must have at least 12 characters')
    for key in ('wan_interface', 'virtual_router', 'lan_zone', 'vpn_zone', 'vsys'):
        if not re.fullmatch(r'[A-Za-z0-9_.\-/]+', c[key]):
            raise ValueError('Invalid characters in ' + key)
    if not isinstance(c.get('verify_tls', False), (bool, str)):
        raise ValueError('verify_tls must be boolean or CA bundle path')


def operations(c):
    network = ROOT + '/network'
    vsys = ROOT + f"/vsys/entry[@name='{c['vsys']}']"
    tunnel = c['tunnel_interface']
    p1, p2, ike, vpn, route = ('AUTO-IKE-FGT', 'AUTO-IPSEC-FGT',
                               'AUTO-GW-FGT', 'AUTO-VPN-FGT', 'AUTO-ROUTE-FGT')
    local, remote = 'AUTO-LAN-PA', 'AUTO-LAN-FGT'
    out = []

    def add(name, xpath, xml, kind='entry'):
        out.append((name, xpath, xml, kind))

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
    add('VSYS interface membership', vsys+'/import/network/interface', member(tunnel), 'membership')
    add('Virtual router interface membership', network+f"/virtual-router/entry[@name='{c['virtual_router']}']/interface", member(tunnel), 'membership')
    # PAN-OS references the configured interface IP including its prefix length.
    wan = c['wan_ip']
    add('IKE gateway', network+f"/ike/gateway/entry[@name='{ike}']",
        '<authentication><pre-shared-key><key>'+esc(c['psk'])+'</key></pre-shared-key></authentication>'
        '<protocol><version>ikev2</version><ikev2><ike-crypto-profile>'+p1+'</ike-crypto-profile></ikev2></protocol>'
        '<protocol-common><nat-traversal><enable>no</enable></nat-traversal></protocol-common>'
        '<local-address><interface>'+esc(c['wan_interface'])+'</interface><ip>'+esc(wan)+'</ip></local-address>'
        '<peer-address><ip>'+esc(c['peer_wan_ip'])+'</ip></peer-address>')
    add('IPSec tunnel', network+f"/tunnel/ipsec/entry[@name='{vpn}']",
        '<tunnel-interface>'+esc(tunnel)+'</tunnel-interface><auto-key><ike-gateway>'+entry(ike, '')+'</ike-gateway>'
        '<ipsec-crypto-profile>'+p2+'</ipsec-crypto-profile></auto-key>')
    add('Static route', network+f"/virtual-router/entry[@name='{c['virtual_router']}']/routing-table/ip/static-route/entry[@name='{route}']",
        '<destination>'+esc(c['remote_subnet'])+'</destination><interface>'+esc(tunnel)+'</interface><metric>10</metric>')
    add('Local address', vsys+f"/address/entry[@name='{local}']", '<ip-netmask>'+esc(c['local_subnet'])+'</ip-netmask>')
    add('Remote address', vsys+f"/address/entry[@name='{remote}']", '<ip-netmask>'+esc(c['remote_subnet'])+'</ip-netmask>')
    rules = vsys+'/rulebase/security/rules'

    def rule(name, source_zone, dest_zone, source, dest):
        body = ('<from>'+member(source_zone)+'</from><to>'+member(dest_zone)+'</to>'
                '<source>'+member(source)+'</source><destination>'+member(dest)+'</destination>'
                '<source-user>'+member('any')+'</source-user><category>'+member('any')+'</category>'
                '<application>'+member('any')+'</application><service>'+member('any')+'</service>'
                '<action>allow</action><log-end>yes</log-end>')
        add(name, rules+f"/entry[@name='{name}']", body)

    rule('AUTO-PA-TO-FGT', c['lan_zone'], c['vpn_zone'], local, remote)
    rule('AUTO-FGT-TO-PA', c['vpn_zone'], c['lan_zone'], remote, local)
    return out


class Client:
    def __init__(self, c, key):
        self.url = f"https://{c['management_ip']}/api/"
        self.key = key
        self.session = requests.Session()
        self.session.verify = c.get('verify_tls', False)
        self.timeout = 30
        if self.session.verify is False:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print('WARNING: TLS certificate verification disabled (lab only).', file=sys.stderr)

    def request(self, **params):
        response = self.session.post(self.url, headers={'X-PAN-KEY': self.key},
                                     data=params, timeout=self.timeout)
        response.raise_for_status()
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as ex:
            raise RuntimeError('Invalid XML API response') from ex
        if root.attrib.get('status') != 'success':
            msg = ' '.join((root.findtext('.//msg/line') or root.findtext('.//msg') or 'API error').split())
            raise RuntimeError('PAN-OS API error: ' + msg)
        return root

    def get(self, xpath):
        try:
            result = self.request(type='config', action='get', xpath=xpath).find('./result')
            return result[0] if result is not None and len(result) else None
        except RuntimeError as exc:
            if any(s in str(exc).lower() for s in ('does not exist', 'not present', 'no such node', 'object not present')):
                return None
            raise

    def backup(self):
        result = self.request(type='config', action='show', xpath='/config').find('./result')
        if result is None or len(result) == 0:
            raise RuntimeError('Empty configuration backup')
        directory = Path('backups')
        directory.mkdir(exist_ok=True)
        path = directory / ('panos_config_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.xml')
        path.write_bytes(ET.tostring(result[0], encoding='utf-8', xml_declaration=True))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def commit(self, timeout=600):
        result = self.request(type='commit', cmd='<commit></commit>')
        job_id = result.findtext('.//job')
        if not job_id:
            raise RuntimeError('Commit response has no job ID; check jobs manually: '
                               + ET.tostring(result, encoding='unicode')[:500])
        print('Commit job:', job_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.request(type='op', cmd=f'<show><jobs><id>{esc(job_id)}</id></jobs></show>')
            status = (job.findtext('.//job/status') or '').strip().upper()
            outcome = (job.findtext('.//job/result') or '').strip().upper()
            if status == 'FIN':
                if outcome != 'OK':
                    detail = ' '.join(x.text or '' for x in job.findall('.//details//line'))
                    raise RuntimeError(f'Commit job {job_id}: FIN/{outcome}. {detail[:500]}')
                print(f'Commit job {job_id}: FIN/OK')
                return
            time.sleep(5)
        raise RuntimeError(f'Commit job {job_id} did not finish within {timeout}s')


def subset_matches(actual, expected, path=''):
    """Compare desired XML nodes, allowing additional PAN-OS default fields."""
    differences = []
    if actual is None:
        return [path + ': missing']
    if expected.tag != actual.tag:
        return [path + f': expected {expected.tag}, got {actual.tag}']
    for key, value in expected.attrib.items():
        if actual.attrib.get(key) != value:
            differences.append(path + f'/@{key}: mismatch')
    if not list(expected) and (expected.text or '').strip() != (actual.text or '').strip():
        # PAN-OS may mask the pre-shared key on read. Never print secret values.
        if path.endswith('/key'):
            return differences
        differences.append(path + ': value differs')
    for child in expected:
        candidates = [item for item in actual if item.tag == child.tag]
        if child.tag == 'entry' and 'name' in child.attrib:
            candidates = [item for item in candidates if item.attrib.get('name') == child.attrib['name']]
        if child.tag == 'member':
            candidates = [item for item in candidates if (item.text or '').strip() == (child.text or '').strip()]
        if not candidates:
            differences.append(path + '/' + child.tag + ': missing expected value')
        else:
            candidate_results = [subset_matches(item, child, path + '/' + child.tag) for item in candidates]
            differences.extend(min(candidate_results, key=len))
    return differences


def inspect(client, op):
    name, xpath, xml, kind = op
    actual = client.get(xpath)
    if kind == 'membership':
        if actual is None:
            return 'CREATE', []
        expected = ET.fromstring(xml)
        found = any((m.text or '').strip() == (expected.text or '').strip()
                    for m in actual.iter('member'))
        return ('UNCHANGED' if found else 'CREATE'), []
    if actual is None:
        return 'CREATE', []
    object_name = xpath.rsplit("/entry[@name='", 1)[1][:-2]
    expected = ET.fromstring(entry(object_name, xml))
    diff = subset_matches(actual, expected, name)
    return ('DRIFT' if diff else 'UNCHANGED'), diff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--mode', choices=('preview', 'apply', 'validate', 'commit'), default='preview')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    c = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    c['psk'] = os.environ.get('VPN_PSK', '')
    # Backward compatibility: the known working lab uses a /30 WAN interface.
    if '/' not in c.get('wan_ip', ''):
        c['wan_ip'] += '/' + str(c.get('wan_prefix', 30))
    validate_config(c)
    ops = operations(c)
    if args.mode == 'preview':
        for name, xpath, xml, _ in ops:
            print(f'[{name}] xpath={xpath}')
            print('  XML: [REDACTED: PSK]' if name == 'IKE gateway' else '  XML: ' + xml)
        return
    key = os.environ.get('PAN_API_KEY')
    if not key:
        raise ValueError('PAN_API_KEY environment variable required')
    client = Client(c, key)
    if args.mode == 'commit':
        if not args.confirm:
            raise ValueError('--confirm is required for commit')
        client.commit()
        return
    states = [(op, *inspect(client, op)) for op in ops]
    for op, status, differences in states:
        print(f'{status}: {op[0]}')
        for difference in differences:
            print('  ' + difference)
    drifts = [op[0] for op, status, _ in states if status == 'DRIFT']
    if drifts:
        raise RuntimeError('Configuration drift detected. No changes made: ' + ', '.join(drifts))
    missing = [op for op, status, _ in states if status == 'CREATE']
    if args.mode == 'validate':
        if missing:
            raise RuntimeError('Missing objects/members: ' + ', '.join(op[0] for op in missing))
        print('Candidate configuration matches expected fields (PSK value cannot be independently verified).')
        print('This does not establish running configuration or active VPN SAs.')
        return
    if not args.confirm:
        raise ValueError('--confirm is required for apply')
    if not missing:
        print('No changes required.')
        return
    backup = client.backup()
    print('Pre-change backup:', backup)
    for op in missing:
        name, xpath, xml, kind = op
        if kind == 'membership':
            # Adding a member preserves other interfaces in the list.
            client.request(type='config', action='set', xpath=xpath, element=xml)
        else:
            parent_xpath, object_name = xpath.rsplit("/entry[@name='", 1)
            client.request(type='config', action='set', xpath=parent_xpath,
                           element=entry(object_name[:-2], xml))
        print('CREATED:', name)
    print('Candidate updated. Run --mode validate, then PAN-OS validate full and commit.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, requests.RequestException, OSError, ET.ParseError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)
