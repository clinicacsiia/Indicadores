# CRM Ressonância — o que já está pronto e o que falta

Documento de trabalho da Clínica CSI. Última revisão: 22/10/2026.

---

## 1. O que a auditoria do banco encontrou (e o que foi corrigido)

Antes de mexer na tela, conferimos cada campo da aba contra o que o Klingo realmente
registra (relatórios 52, 7, 47, 18 e 260, de 1º de setembro a 22 de outubro).

| Problema encontrado | Tamanho do problema | O que foi feito |
| --- | --- | --- |
| Lista de exames inventada ("Joelho", "Coluna lombar") | O Klingo usa **69 nomes** diferentes. Nenhum batia | Catálogo `crm_rm_exame` com **63 exames**, nome exato do Klingo |
| Convênio em texto livre | **22 convênios** reais; cada atendente escreveria de um jeito | Catálogo `crm_rm_convenio` com **23**, lista fechada |
| Só "Particular" e "Convênio" | Faltavam **SUS** (76 exames) e **Cetrus** (antigo "SUS CURSO") | Quatro formas, iguais às do resto do sistema |
| Atendente digitava o preço | RM de crânio: R$ 420–490. Sob sedação: **R$ 2.150–2.350** | `crm_rm_precos()` mostra o preço realmente cobrado |
| Sem unidade | A RM é toda na CSI 2 (RM/TC) | Unidade fixa, alinhada ao `metas.json` |
| Sem como achar o paciente | A fila "retomar hoje" não servia para nada | Código do Klingo + telefone opcional + atalho do WhatsApp |
| "Demora na resposta" sem medida | É motivo de perda, mas não dava para medir | Carimbo de primeira resposta + indicador por canal |
| Ninguém sabia se o CRM refletia a operação | — | **Cobertura do CRM**: compara com o que o Klingo faturou |

**A descoberta mais importante:** a cobertura. Com os dados de hoje, o CRM registra uma
fração pequena das ressonâncias que a clínica faz. Enquanto isso não subir, todo
indicador da aba descreve uma amostra, não a clínica. Por isso a tela diz isso em
primeiro lugar, antes de qualquer outro número.

---

## 2. O que você precisa fazer para a aba ficar completa

### Agora (sem depender de ninguém de fora)

**1. Liberar o acesso.** Configurações → cada pessoa → "CRM Ressonância":
- call center e recepção: **Pode registrar**;
- coordenação e marketing: **Pode ver os indicadores**;
- quem precisa de valores em R$: marcar também "Dados financeiros".

**2. Preencher o preparo dos exames.** Hoje a tela diz "não cadastrado — pergunte à
equipe técnica", porque orientação de preparo é conteúdo clínico e não dá para inventar.
No Supabase, Table Editor → `crm_rm_exame`, preencha para os 10 exames mais feitos:
`preparo`, `contraste` e `duracao_min`. São os que respondem por quase todo o volume:

> RM PELVE · RM ARTICULAR · RM COLUNA CERVICAL OU DORSAL OU LOMBAR · RM DE CRÂNIO ·
> RM BACIA · RM CRÂNIO (ENCÉFALO) · RM MULTIPARAMÉTRICA DA PRÓSTATA · RM DA COLUNA
> LOMBO-SACRA · RM DE JOELHO · RM CRANIO SOB SEDACAO

**3. Preencher os convênios.** Table Editor → `crm_rm_convenio`: `exige_autorizacao` e
`prazo_autorizacao`. É o que faz a atendente avisar o paciente sem perguntar a ninguém.

**4. Combinar a regra com a equipe.** A aba só funciona se **todo** pedido de RM for
registrado, inclusive o que não agenda. Sugestão de rotina:
- começar o dia pela aba **Meu dia** e zerar "Responder primeiro";
- registrar o contato **antes** de resolver, não depois;
- confirmar os exames do dia seguinte pela própria aba;
- fechar o resultado dos exames do dia anterior.

**5. Reunião semanal de 30 minutos** na aba Indicadores: escolher os três maiores
gargalos e decidir uma ação para cada. Comece olhando a **cobertura**.

### Depois (depende do Klingo)

**6. Enviar o pedido ao suporte** (o texto está na conversa). O essencial é a situação
do atendimento e o código da marcação nos relatórios 18 e 47.

**7. Quando o Klingo responder**, a agenda deixa de ser digitada: as marcações entram
sozinhas, "Realizado" e "Faltou" vêm prontos, e a atendente só registra confirmação e
motivo. É a diferença entre a equipe alimentar o sistema e o sistema alimentar a equipe.

---

## 3. Decisões que são suas

| Decisão | Por que importa | Recomendação |
| --- | --- | --- |
| Guardar telefone no CRM? | É dado pessoal (LGPD). Sem ele, a fila de retorno fica difícil | Manter, porque é o mínimo para a finalidade. Preferir sempre o código do Klingo |
| Quanto tempo é "demora"? | Define quando o sistema cobra a equipe | Sugestão: 2 horas no horário comercial |
| Quem vê valores em R$? | Hoje depende de "Dados financeiros" | Coordenação sim; call center, provavelmente não |
| Apagar os dados de exemplo? | Enquanto estiverem lá, os números são fictícios | Apagar assim que a equipe começar a registrar de verdade |

---

## 4. O que esta aba ainda não faz

- **Não puxa a agenda do Klingo** — a agenda é digitada (item 6 acima).
- **Não conhece o Wellum.** Se ele exportar as conversas, cada contato novo de WhatsApp
  pode virar registro automático. Preciso saber o que o seu plano oferece.
- **Não cobre os outros exames.** É só Ressonância, de propósito: é o equipamento mais
  caro e com a agenda mais disputada. Depois de funcionar aqui, o mesmo modelo serve para
  tomografia e ultrassom.
- **Não tem meta por atendente.** Dá para fazer, mas só depois que o registro virar
  rotina — senão vira cobrança em cima de dado incompleto.

---

## 5. Como saber se deu certo

Em 30 dias, olhe nesta ordem:

1. **Cobertura do CRM** acima de 80% — sem isso, o resto não se sustenta.
2. **Contatos sem primeira resposta** perto de zero.
3. **Vagas recuperadas** subindo (hoje a maioria das vagas que abrem fica vazia).
4. **Taxa de conversão** e **absenteísmo**, que são o objetivo final.

Os dois primeiros medem se a equipe adotou. Os dois últimos medem se deu resultado. Não
adianta olhar os últimos enquanto os primeiros não estiverem de pé.
