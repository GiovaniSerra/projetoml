# FortiGate FortiOS 7.6.2 | Automacao VPN IPSec

Automacao em Python usando a API REST/CMDB do FortiGate para configurar o lado FortiGate de uma VPN IPSec route-based com um Palo Alto PAN-OS 10.1.0, em laboratorio EVE-NG.

## Topologia validada

| Item | Valor |
| --- | --- |
| Gerenciamento FortiGate | `192.168.0.23` |
| WAN FortiGate | `port2`, `10.0.0.1/30` |
| WAN Palo Alto | `10.0.0.2/30` |
| LAN FortiGate | `port3`, `192.168.10.0/24` |
| LAN Palo Alto | `192.168.20.0/24` |
| IP logico FortiGate | `169.255.1.1/32` |
| IP logico Palo Alto | `169.255.1.2/32` |
| VPN | `VPN-ML` |

IKEv2 com PSK, DES/SHA256, DH14 e lifetime de 28800 s. IPSec ESP DES/SHA256, PFS DH14 e lifetime de 3600 s. **DES e inseguro e foi usado apenas por exigencia do laboratorio.**

## Script utilizado

`fortigate_vpn_etapas_corrigido.py` e o script usado na configuracao por etapas. Os arquivos `fortigate_rest.py` e `fortigate_rest_v2.py` sao versoes anteriores e nao devem ser confundidos com a implementacao validada.

Etapas disponiveis: `phase1`, `interface`, `phase2`, `route`, `addresses`, `policies`. Modos: `preview`, `inventory` e `apply`.

## Preparacao

A partir da raiz do projeto, com Python e dependencias instaladas:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r fortigate_rest_76/requirements.txt
```

Configure em `.env` (arquivo local, nao publicar):

```dotenv
FG_HOST=192.168.0.23
FG_API_TOKEN=SUBSTITUIR
VPN_PSK=SUBSTITUIR
```

O script consulta variaveis de ambiente. **Confirme que o `.env` foi carregado no processo** (por exemplo, via `python-dotenv` ou variaveis exportadas no PowerShell) antes de executar. Copie `fortigate_rest_76/config.example.json` para `fortigate_rest_76/config.json` e ajuste ao ambiente. O arquivo local nao e versionado.

## Comandos

Execute a partir da raiz `ML/`:

```powershell
python fortigate_rest_76/fortigate_vpn_etapas_corrigido.py --config fortigate_rest_76/config.json --mode preview
python fortigate_rest_76/fortigate_vpn_etapas_corrigido.py --config fortigate_rest_76/config.json --mode inventory
```

Para uma **nova implantacao**, execute cada etapa individualmente, apos inspecionar o preview e o inventario:

```powershell
python fortigate_rest_76/fortigate_vpn_etapas_corrigido.py --config fortigate_rest_76/config.json --mode apply --step phase1 --confirm
```

Repita somente as etapas necessarias na ordem `interface`, `phase2`, `route`, `addresses`, `policies`. **Nao execute `apply` novamente no laboratorio ja configurado:** o script aborta quando encontra objetos gerenciados existentes, exceto o tratamento especial da etapa de interface.

## Evidencias operacionais

No FortiGate:

```text
get vpn ipsec tunnel summary
diagnose vpn tunnel list name VPN-ML
```

No teste realizado, o tunel apresentou `status=up`, `sa=1`, `dpd status=ok` e incremento dos contadores IPSec de `enc=0/0` e `dec=0/0` para `enc=10/1400` e `dec=10/840` (pacotes/bytes), apos trafego entre as LANs.

## Limitacoes e seguranca

- O snapshot CMDB salvo em `backups/` **nao e um backup integral** do FortiGate.
- As chamadas REST nao sao transacionais; falhas podem deixar alteracoes parciais.
- `inventory` verifica presenca, nao equivalencia completa dos parametros.
- Nao ha rollback automatico nem monitoramento continuo.
- Nao publicar `.env`, tokens, PSK ou snapshots de configuracao.
- Configuracoes com DES, servico `ALL` e permissoes amplas nao sao recomendadas para producao.

Consulte o [README principal](../README.md) e o [plano de automacao](../docs/PLANO_AUTOMACAO_VPN.md).
