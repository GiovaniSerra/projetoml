# Plano de automação da VPN IPSec: FortiGate e Palo Alto

## 1. Objetivo e escopo

Planejar a configuração automatizada de uma VPN site-to-site **route-based** e IKEv2 entre FortiOS 7.6.2 e PAN-OS 10.1.0, com configuração, verificação, alertas e rastreabilidade. O desafio solicita principalmente o **planejamento**; os scripts e a implementação em EVE-NG são extensões práticas opcionais que foram realizadas no laboratório.

## 2. Parâmetros do laboratório

| Item | FortiGate | Palo Alto |
| --- | --- | --- |
| IP de gerenciamento | `192.168.0.23` | `192.168.0.17` |
| Interface WAN | `port2` | `ethernet1/2` |
| IP WAN | `10.0.0.1/30` | `10.0.0.2/30` |
| Interface LAN | `port3` | `ethernet1/3` |
| Gateway LAN | `192.168.10.254/24` | `192.168.20.254/24` |
| Host de teste | `192.168.10.10` | `192.168.20.20` |
| Interface lógica | `VPN-ML` | `tunnel.1` |
| IP da interface lógica | `169.255.1.1/32` | `169.255.1.2/32` |
| Rede de túnel especificada no desafio | `169.255.1.0/30` | `169.255.1.0/30` |

Os IPs lógicos são configurados como `/32` nas interfaces do laboratório; a rede `/30` é a referência de endereçamento do desafio. A nuvem `Net` representa gerenciamento e não o trajeto da VPN.

| Parâmetro | Valor |
| --- | --- |
| IKE | IKEv2, PSK, DES, SHA256, DH group 14, lifetime 28800 s |
| IPSec ESP | DES, SHA256, PFS group 14, lifetime 3600 s |
| Seletores | Amplos (`0.0.0.0/0`) no laboratório route-based |
| Rota FortiGate | `192.168.20.0/24` via `VPN-ML` |
| Rota Palo Alto | `192.168.10.0/24` via `tunnel.1` |
| NAT | Não aplicado ao tráfego entre as duas LANs |

**Segurança:** DES é inseguro e foi utilizado somente por requisito de laboratório. Não reutilizar estas propostas em produção.

## 3. Ferramentas e interfaces de automação

- **Python + requests:** comunicação HTTPS e tratamento de respostas das APIs.
- **FortiGate REST API / CMDB:** configuração dos objetos de Phase 1, Phase 2, interface de túnel, rota, endereços e políticas. Script: `fortigate_rest_76/fortigate_vpn_etapas_corrigido.py`.
- **Palo Alto XML API:** criação de IKE/IPSec crypto profiles, gateway, tunnel, zona, associações ao VSYS/virtual router, rota e políticas. Script: `paloalto_panos101_api/paloalto_vpn.py`.
- **CLI operacional:** inspeção de estado IKE/IPSec, rotas e contadores para validação independente.
- **Git:** versionamento de scripts, documentação e evidências, sem credenciais ou backups sensíveis.

## 4. Fluxo lógico de automação

1. Ler configuração JSON e segredos de variáveis de ambiente; validar campos, endereços e consistência de propostas.
2. Testar acesso HTTPS, autenticação e permissões de cada API.
3. Consultar configuração existente, identificar objetos presentes e evitar sobrescrever recursos não relacionados.
4. Salvar backup anterior às mudanças. No FortiGate, o snapshot CMDB produzido pelo script **não substitui um backup completo** do equipamento.
5. Configurar no FortiGate Phase 1 IKEv2, interface `VPN-ML`, Phase 2, rota, objetos de endereço e políticas bidirecionais sem NAT.
6. Configurar no Palo Alto os perfis IKE/IPSec, `tunnel.1`, zona `VPN`, associações ao VSYS e virtual router, IKE Gateway, IPSec Tunnel, rota, objetos e políticas.
7. Validar a candidate configuration do Palo Alto e executar commit, conferindo conclusão `FIN / OK`.
8. Consultar SAs e gerar tráfego ICMP entre os hosts; verificar incremento de pacotes criptografados/descriptografados.
9. Registrar erros e evidências, preservando segredos. Em falha parcial, interromper e avaliar recuperação manual.

## 5. Particularidades de interoperabilidade

- O FortiGate aplica mudanças CMDB diretamente; o Palo Alto exige commit separado da candidate configuration.
- REST/JSON e XML API têm estruturas, referências e mensagens de erro distintas.
- No Palo Alto, o IP local do IKE Gateway precisou referenciar `10.0.0.2/30`, correspondente ao endereço configurado na interface.
- O túnel route-based usa rotas e interfaces lógicas; os seletores devem ser compatíveis nos dois peers.
- A associação de `tunnel.1` ao virtual router deve ser validada por **pertencimento à lista**, não apenas pela existência do nó XML.
- NAT-T, PSK, algoritmos, PFS, lifetimes, zonas e políticas devem ser compatíveis. Mudanças parciais podem exigir intervenção manual.

## 6. Validação e estratégia de alertas

| Falha ou divergência | Detecção planejada | Alerta / ação |
| --- | --- | --- |
| API inacessível | Timeout, TLS ou erro HTTP | Informar equipamento e operação, interromper |
| Autenticação rejeitada | HTTP/API error | Alertar sem imprimir token/PSK |
| Objeto ausente | Consulta CMDB/XML API | Reportar objeto e etapa |
| Configuração divergente | Comparação de parâmetros desejados e atuais | Reportar DRIFT; não sobrescrever automaticamente |
| Falha de validação/commit | PAN-OS `validate full` e job | Reportar erro e impedir conclusão falsa |
| IKEv2 não estabelecida | `show vpn ike-sa` | Verificar PSK, propostas, peer e conectividade |
| IPSec SA ausente | `show vpn ipsec-sa`, diagnóstico FortiGate | Verificar Phase 2, PFS e seletores |
| Tráfego não criptografado | Pings e contadores `enc/dec` | Verificar rotas, políticas e caminho de dados |

**Estado da implementação:** os scripts originais criam objetos e verificam principalmente sua existência. A detecção integral de drift, rollback e o polling automático do commit não devem ser considerados validados em equipamento. A tabela descreve a estratégia de validação planejada e os procedimentos manuais complementares.

## 7. Evidências obtidas no laboratório

- Validação e commit PAN-OS concluídos com `FIN / OK`.
- IKEv2 em `Established`; IPSec Child SA em `Mature`.
- FortiGate com `status=up`, `sa=1` e DPD `ok`.
- Após testes de tráfego, contadores `dec:pkts/bytes=10/840` e `enc:pkts/bytes=10/1400`.
- Pings entre as LANs realizados; incremento dos contadores comprova tráfego criptografado bidirecional.

## 8. Limitações e próximos passos

- Implementar e testar comparação completa do estado desejado nos dois fabricantes.
- Automatizar a confirmação do job de commit, incluindo timeout e erros.
- Ampliar testes unitários com mocks das APIs e cenários de falha.
- Criar procedimento de recuperação de alterações parciais e restauração a partir de backups completos.
- Manter os arquivos `.env`, backups e histórico com credenciais fora da publicação.
