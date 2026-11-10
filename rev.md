# Revisão de publicação

Esta pasta foi preparada a partir de `ML(1).zip`, sem modificar o projeto original.

Removidos do pacote: arquivos `.env`, `.git`, `.venv`, backups, caches, testes exploratórios com chamadas de escrita, versões antigas do FortiGate e `config.json` locais.

Mantidos: app Cisco, teste unitário Cisco, scripts operacionais de VPN, script Palo Alto revisado (ainda experimental), documentação, plano VPN e capturas de evidência.

O `.gitignore` foi reforçado. Os exemplos `.env.example` e `config.example.json` são modelos, não credenciais.

**Atenção:** a versão revisada do Palo Alto não foi comprovada em execução real. Não substituir a versão operacional sem testes. O script FortiGate também não tem idempotência completa.

**Histórico anterior:** o ZIP original continha `.git`. Foi inspecionada a lista de caminhos dos dois commits disponíveis; não foram encontrados `.env` reais ou backups nos caminhos versionados, mas isso não constitui auditoria exaustiva do conteúdo de todos os blobs. O pacote de entrega não inclui esse histórico.

**Recomendação:** criar um repositório Git novo a partir desta pasta limpa, ou revisar cuidadosamente o histórico local antes de reutilizá-lo. Se alguma chave foi exposta fora de ambiente autorizado, revogá-la.

**Não execute scripts `apply` ou `commit` somente para testar o pacote**: eles alteram equipamentos. Testes de integração e publicação final dependem do ambiente do usuário.
