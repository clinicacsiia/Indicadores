# Indicadores CSI

Painel gerencial da **Clínica CSI** (diagnóstico por imagem, Salvador), como site: dados do Klingo → Supabase → painéis (Metas, Faturamento,
Financeiro, Despesas, Indicadores, Cesta, Suprimentos, Atendimento) com alertas guiados, exportação em PDF e acesso por usuário.

- **Site:** Next.js (App Router, TypeScript) na Vercel — `src/`
- **Cálculo dos painéis:** Python/pandas (os `gerar_*.py` do programa antigo) numa função da Vercel — `painel_py/`, `api/py/`
- **Banco, Auth, Realtime, agendamento:** Supabase — `supabase/migrations/`
- **Programa antigo (somente leitura):** `legado/`

Comece por `docs/`: [PREMISSAS](docs/PREMISSAS.md) (o que foi reconstruído e as dúvidas), [ARQUITETURA](docs/ARQUITETURA.md),
[OPERACAO](docs/OPERACAO.md) (passos manuais e checklist), [PLANO](docs/PLANO.md) (fases e situação).

```
npm ci && npm test && npm run lint     # site e motor Klingo
pip install -r requirements.txt && python -m unittest discover -s tests/python -v
```
Segredos só em variáveis de ambiente (`.env.example`); nada de dado real nem segredo no Git.
