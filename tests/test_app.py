import unittest
import sys
import types
try:
    import flask
except ImportError:
    flask = types.ModuleType('flask')
    flask.Flask = lambda name: types.SimpleNamespace(route=lambda *a, **k: lambda fn: fn, logger=types.SimpleNamespace(exception=lambda *a: None))
    flask.render_template = lambda *a, **k: None
    flask.request = None
    sys.modules['flask'] = flask
try:
    import netmiko
except ImportError:
    netmiko = types.ModuleType('netmiko')
    netmiko.ConnectHandler = lambda **k: None
    netmiko.NetmikoAuthenticationException = type('NetmikoAuthenticationException', (Exception,), {})
    netmiko.NetmikoTimeoutException = type('NetmikoTimeoutException', (Exception,), {})
    sys.modules['netmiko'] = netmiko
from unittest.mock import patch
from app import validar_entrada, verificar_configuracao, configurar_switch

class TestValidacao(unittest.TestCase):
    def test_configuracao_valida(self):
        self.assertEqual(validar_entrada('192.168.0.12', 'admin', 'senha', 'SWITCH_AUTOMATIZADO', ['10', '20', '50']), [10, 20, 50])

    def test_ids_duplicados(self):
        with self.assertRaisesRegex(ValueError, 'diferentes'):
            validar_entrada('192.168.0.12', 'admin', 'senha', 'SWITCH', ['10', '10', '50'])

    def test_hostname_injecao(self):
        with self.assertRaises(ValueError):
            validar_entrada('192.168.0.12', 'admin', 'senha', 'SWITCH\nreload', ['10', '20', '50'])

    def test_detecta_nome_incorreto(self):
        output = '10 VLAN_TESTE active\n20 VLAN_VOZ active\n50 VLAN_SEGURANCA active\n'
        div = verificar_configuracao('SWITCH_AUTOMATIZADO', {10:'VLAN_DADOS',20:'VLAN_VOZ',50:'VLAN_SEGURANCA'}, 'hostname SWITCH_AUTOMATIZADO', output)
        self.assertEqual(len(div), 1)
        self.assertIn('VLAN_TESTE', div[0])

    def test_configuracao_correta(self):
        output = '10 VLAN_DADOS active\n20 VLAN_VOZ active\n50 VLAN_SEGURANCA active\n'
        self.assertEqual(verificar_configuracao('SWITCH_AUTOMATIZADO', {10:'VLAN_DADOS',20:'VLAN_VOZ',50:'VLAN_SEGURANCA'}, 'hostname SWITCH_AUTOMATIZADO', output), [])

    @patch('app.ConnectHandler')
    def test_desconecta_apos_falha(self, conectar):
        sessao = conectar.return_value
        sessao.send_config_set.side_effect = RuntimeError('Falha simulada')
        sucesso, _, _ = configurar_switch('192.168.0.12','admin','senha','10','20','50','SWITCH_AUTOMATIZADO')
        self.assertFalse(sucesso)
        sessao.disconnect.assert_called_once()

if __name__ == '__main__':
    unittest.main()
