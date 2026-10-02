# Recibo de deploy — <task_id> — <ambiente>

Evidência após operação; não preencher como sucesso antes da verificação.
[Política de risco](../RISK_POLICY.md) e gates/capabilities vigentes se aplicam.

## Candidato e aprovação

- Task Contract / Packet e revisão:
- PR:
- Commit final validado:
- Artefato/build e digest:
- Revisão de QA: <identidade/sessão, horário, candidato e resultado>
- Referência visual / aceite pertinente:
- Capability, autorização/gate e escopo: <refs sem segredos>

## Operação e leitura posterior

- Ambiente:
- Executor operacional:
- Início / fim:
- Candidato efetivamente publicado:
- Identidade/versão observadas no runtime:
- Healthchecks e verificação funcional pertinente:
- Resultado: <confirmado / falhou / desconhecido>
- Evidências retidas e validade:

## Recuperação e fechamento

- Release anterior / artefato de reversão:
- Procedimento autorizado de reversão:
- Limites: <health não comprova todas as funções; migração pode exigir restore>
- Estado final registrado no Paperclip:
- Checkpoint final:

Se commit ou artefato diferir do aprovado/validado, registrar a divergência e
revalidar o candidato pertinente. Merge/rebuild não herda evidência por nome de
branch. Segredos, cookies e URLs assinadas nunca entram no recibo.
