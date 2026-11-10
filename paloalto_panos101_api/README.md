# Palo Alto PAN-OS 10.1.0 | Automacao VPN IPSec

Automacao em Python por **XML API** para configurar o lado Palo Alto da VPN IPSec route-based com FortiGate FortiOS 7.6.2 em laboratorio EVE-NG.

## Topologia validada

| Item | Valor |
| --- | --- |
| Gerenciamento Palo Alto | `192.168.0.17` |
| WAN Palo Alto | `ethernet1/2`, `10.0.0.2/30` |
| WAN FortiGate | `10.0.0.1/30` |
| LAN Palo Alto | `ethernet1/3`, `192.168.20.0/24` |
| LAN FortiGate | `192.168.10.0/24` |
| Interface VPN | `tunnel.1`, `169.255.1.2/32` |
| Zona e roteador | `VPN`, virtual router `default`, `vsys1` |
| IKE Gateway | `AUTO-GW-FGT` |
| IPSec Tunnel | `AUTO-VPN-FGT` |

IKEv2 com PSK, DES/SHA256, DH14, lifetime 28800 s; ESP DES/SHA256, lifetime 3600 s. **DES e inseguro e foi usado apenas no laboratorio.**

## Scripts

- `paloalto_vpn.py`: script utilizado para criar os objetos no laboratorio, com backup, preview, apply, verificacao de presenca e solicitacao de commit.
- `paloalto_vpn_revisado.py`: revisao com comparacao de campos esperados, deteccao de divergencias (`DRIFT`), verificacao de membros de interface e acompanhamento de job de commit. **A revisao ainda precisa ser validada contra o equipamento antes de substituir o script operacional.**

## Preparacao

No PowerShell, a partir da raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r paloalto_panos101_api/requirements.txt
```

Variaveis locais no `.env` (nao publicar):

```dotenv
PAN_API_KEY=SUBSTITUIR
VPN_PSK=SUBSTITUIR
```

Copie `paloalto_panos101_api/config.example.json` para `paloalto_panos101_api/config.json` e ajuste ao ambiente. O arquivo local nao e versionado. O endereco local do IKE Gateway deve referenciar `10.0.0.2/30`, que foi aceito pela API no laboratorio. O arquivo de configuracao armazena `wan_ip` como `10.0.0.2`; o script compoe o prefixo.

## Verificacao sem alteracoes

```powershell
python paloalto_panos101_api/paloalto_vpn.py --config paloalto_panos101_api/config.json --mode preview
python paloalto_panos101_api/paloalto_vpn.py --config paloalto_panos101_api/config.json --mode validate
```

Para avaliar a versao revisada sem escrever configuracoes:

```powershell
python paloalto_panos101_api/paloalto_vpn_revisado.py --config paloalto_panos101_api/config.json --mode preview
python paloalto_panos101_api/paloalto_vpn_revisado.py --config paloalto_panos101_api/config.json --mode validate
```

**Nao execute `apply` ou `commit` em equipamento ja configurado sem revisar o estado candidato e o impacto.** `apply` altera a candidate configuration; `commit` pode incluir outras alteracoes pendentes de administradores.

## Validacao operacional realizada

No CLI operacional do Palo Alto (prompt `>`):

```text
show jobs all
show vpn ike-sa
show vpn ipsec-sa
show vpn flow
```

Resultados observados no laboratorio:

- Job `Validate`: `FIN / OK`.
- Job `Commit`: `FIN / OK`.
- IKEv2 `AUTO-GW-FGT`: `Established`, PSK/DH14/DES/SHA256.
- Child SA IPSec `AUTO-VPN-FGT`: `Mature`, ESP/DES/SHA256.
- No FortiGate, tunel `status=up` e contadores de pacotes criptografados e descriptografados incrementando apos os testes entre as LANs.

## Limitacoes e seguranca

- O script original verifica a existencia de objetos, nao equivalencia completa de configuracao.
- A revisao compara campos configurados, mas **nao comprova o valor da PSK**, nem substitui a verificacao de SAs ativas.
- Nao ha rollback automatico nem bloqueio de alteracoes concorrentes.
- O backup XML pode conter segredos e nao deve ser publicado.
- A verificacao TLS foi desabilitada no laboratorio com certificado nao confiavel; em producao, utilize CA/certificado validos.
- Regras com `service=any` e criptografia DES sao especificas deste laboratorio.

Consulte o [README principal](../README.md) e o [plano de automacao](../docs/PLANO_AUTOMACAO_VPN.md).
