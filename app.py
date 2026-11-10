"""Parte 1: configuração e validação de VLANs em switch Cisco via SSH."""
import datetime
import ipaddress
import os
import re
from pathlib import Path

from flask import Flask, render_template, request
from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / 'backups'
HOSTNAME_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,62}$')
VLAN_PATTERN = re.compile(r'^\s*(\d+)\s+(\S+)\s+(\S+)(?:\s|$)')


def validar_entrada(host, username, password, hostname, vlans):
    """Valida entradas antes de montar comandos de configuração."""
    try:
        ipaddress.ip_address(host.strip())
    except (ValueError, AttributeError):
        raise ValueError('Informe um endereço IP válido para o switch.') from None
    if not username or not username.strip() or not password:
        raise ValueError('Usuário e senha são obrigatórios.')
    if not HOSTNAME_PATTERN.fullmatch(hostname or ''):
        raise ValueError('Hostname inválido: use 1 a 63 caracteres, iniciando com letra, apenas letras, números, _ ou -.')
    try:
        ids = [int(v) if str(v).isdigit() else -1 for v in vlans]
    except (ValueError, TypeError):
        raise ValueError('IDs de VLAN devem ser números inteiros.') from None
    if any(v < 1 or v > 4094 for v in ids):
        raise ValueError('IDs de VLAN devem estar entre 1 e 4094.')
    if len(set(ids)) != len(ids):
        raise ValueError('As VLANs Dados, Voz e Segurança devem ter IDs diferentes.')
    return ids


def verificar_configuracao(hostname_esperado, vlans_esperadas, saida_hostname, saida_vlans):
    """Compara hostname e pares ID/nome/status de cada VLAN."""
    divergencias = []
    match = re.search(r'^hostname\s+(\S+)\s*$', saida_hostname, re.MULTILINE)
    hostname_atual = match.group(1) if match else None
    if hostname_atual != hostname_esperado:
        divergencias.append(f"Hostname esperado '{hostname_esperado}', encontrado '{hostname_atual or 'não identificado'}'.")

    vlans_atuais = {}
    for linha in saida_vlans.splitlines():
        match = VLAN_PATTERN.match(linha)
        if match:
            vlans_atuais[int(match.group(1))] = (match.group(2), match.group(3))
    for vid, nome in vlans_esperadas.items():
        atual = vlans_atuais.get(vid)
        if atual is None:
            divergencias.append(f'VLAN {vid} ({nome}) não encontrada.')
        elif atual[0] != nome:
            divergencias.append(f'VLAN {vid}: nome esperado {nome}, encontrado {atual[0]}.')
        elif atual[1].lower() != 'active':
            divergencias.append(f'VLAN {vid} ({nome}): status encontrado {atual[1]}, esperado active.')
    return divergencias


def configurar_switch(host, username, password, vlan_dados, vlan_voz, vlan_seguranca, hostname):
    try:
        ids = validar_entrada(host, username, password, hostname,
                             [vlan_dados, vlan_voz, vlan_seguranca])
    except ValueError as exc:
        return False, f'Dados inválidos: {exc}', ''

    vlans = dict(zip(ids, ['VLAN_DADOS', 'VLAN_VOZ', 'VLAN_SEGURANCA']))
    device = {
        'device_type': 'cisco_ios', 'host': host.strip(),
        'username': username.strip(), 'password': password,
    }
    comandos = [f'hostname {hostname}']
    for vid, nome in vlans.items():
        comandos.extend([f'vlan {vid}', f' name {nome}'])

    net_connect = None
    try:
        net_connect = ConnectHandler(**device)
        output = net_connect.send_config_set(comandos)
        net_connect.set_base_prompt()
        # Não relatar sucesso se o IOS rejeitou algum comando.
        if re.search(r'%\s*(?:Invalid input|Error|Incomplete command|Ambiguous command)', output, re.I):
            return False, 'O switch rejeitou um ou mais comandos. Verifique o log.', output

        net_connect.save_config()
        config_running = net_connect.send_command('show running-config')
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_path = BACKUP_DIR / f'{hostname}_{timestamp}.cfg'
        backup_path.write_text(config_running, encoding='utf-8')

        saida_hostname = net_connect.send_command('show running-config | include ^hostname')
        saida_vlans = net_connect.send_command('show vlan brief')
        divergencias = verificar_configuracao(hostname, vlans, saida_hostname, saida_vlans)
        if divergencias:
            return False, 'Alerta: configuração aplicada, mas foram encontradas divergências.', (
                'DIVERGÊNCIAS ENCONTRADAS:\n' + '\n'.join(divergencias)
                + '\n\nBackup: ' + str(backup_path.relative_to(BASE_DIR))
                + '\n\nLog de configuração:\n' + output)
        return True, ('Sucesso! Configuração aplicada, validada e backup salvo em '
                      + str(backup_path.relative_to(BASE_DIR)) + '.'), output
    except NetmikoAuthenticationException:
        return False, 'Falha de Autenticação: Verifique o usuário e senha do switch.', ''
    except NetmikoTimeoutException:
        return False, 'Tempo de limite excedido: O switch está inacessível ou o IP está incorreto.', ''
    except Exception as exc:
        app.logger.exception('Falha ao configurar switch')
        return False, f'Erro durante a automação: {type(exc).__name__}. Consulte o log do servidor.', ''
    finally:
        if net_connect is not None:
            try:
                net_connect.disconnect()
            except Exception:
                app.logger.exception('Falha ao encerrar sessão SSH')


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        campos = {k: request.form.get(k, '') for k in (
            'host', 'username', 'hostname', 'vlan_dados', 'vlan_voz', 'vlan_seguranca')}
        success, message, output = configurar_switch(
            campos['host'], campos['username'], request.form.get('password', ''),
            campos['vlan_dados'], campos['vlan_voz'], campos['vlan_seguranca'], campos['hostname'])
        return render_template('index.html', message=message, output=output,
                               success=success, values=campos)
    return render_template('index.html', values={})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
