import { exigirSessao } from "@/lib/sessao";
import { admin } from "@/lib/supabase/admin";
import { NOME_DO_MENU, MENUS } from "@/klingo/config";
import { aprovarPedido, criarUsuario, editarUsuario, recusarPedido, removerUsuario, salvarCusto, trocarMinhaSenha } from "./acoes";
import Conferir from "./Conferir";
import FormAcao from "./FormAcao";

export const dynamic = "force-dynamic";

const quando = (iso: string) => new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Bahia", dateStyle: "short", timeStyle: "short" });

function EscolhaDeMenus({ marcados = [] as string[], admin: souAdmin = false }) {
  const todos = marcados.includes("*");
  return (
    <div className="menus-escolha">
      <label><input type="checkbox" name="admin" defaultChecked={souAdmin} /> Administrador</label>
      <label><input type="checkbox" name="todos" defaultChecked={todos} /> Todos os painéis</label>
      {MENUS.map((m) => <label key={m}><input type="checkbox" name="menus" value={m} defaultChecked={marcados.includes(m)} /> {NOME_DO_MENU[m]}</label>)}
    </div>
  );
}

export default async function Conta({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const sessao = await exigirAdminOuUsuario();
  const q = ((await searchParams).q ?? "").trim().slice(0, 60);
  const db = admin();
  const [pedidos, usuarios, custos, hist, aud] = sessao.admin ? await Promise.all([
    db.from("solicitacoes_cadastro").select("id, usuario, mensagem, solicitado_em").order("solicitado_em"),
    db.from("perfis").select("id, usuario, admin, relatorios").order("usuario"),
    (q ? db.from("custos_itens").select("*").ilike("item", `%${q.replace(/[%_]/g, "")}%`) : db.from("custos_itens").select("*")).order("item").limit(100),
    db.from("historico_atualizacoes").select("modulo_id, status, mensagem, duracao_segundos, data_hora, usuario").order("id", { ascending: false }).limit(40),
    db.from("auditoria").select("quando, usuario, acao, detalhe").order("id", { ascending: false }).limit(40),
  ]) : [null, null, null, null, null];

  return (
    <div className="conta">
      <section>
        <h2>Minha senha</h2>
        <FormAcao acao={trocarMinhaSenha} rotulo="Trocar senha" className="form-coluna">
          <label>Senha atual<input name="atual" type="password" autoComplete="current-password" required /></label>
          <label>Nova senha<input name="nova" type="password" autoComplete="new-password" required minLength={8} /></label>
          <label>Confirmar nova senha<input name="confirmar" type="password" autoComplete="new-password" required /></label>
        </FormAcao>
      </section>

      {sessao.admin && (<>
        <section>
          <h2>Pedidos de cadastro {pedidos?.data?.length ? <span className="tag">{pedidos.data.length}</span> : null}</h2>
          {!pedidos?.data?.length && <p className="vazio">Nenhum pedido pendente.</p>}
          {pedidos?.data?.map((p) => (
            <div className="cartao" key={p.id}>
              <b>{p.usuario}</b> <span className="micro">pediu em {quando(p.solicitado_em)}</span>
              {p.mensagem && <p className="nota">“{p.mensagem}”</p>}
              <FormAcao acao={aprovarPedido.bind(null, p.id)} rotulo="Aprovar"><EscolhaDeMenus /></FormAcao>
              <FormAcao acao={recusarPedido.bind(null, p.id)} rotulo="Recusar" perigo confirmar={`Recusar o pedido de ${p.usuario}?`} />
            </div>
          ))}
        </section>

        <section>
          <h2>Usuários</h2>
          {usuarios?.data?.map((u) => (
            <details className="cartao" key={u.id}>
              <summary><b>{u.usuario}</b> {u.admin && <span className="tag">admin</span>} <span className="micro">{u.relatorios.includes("*") ? "todos os painéis" : u.relatorios.map((m: string) => NOME_DO_MENU[m as keyof typeof NOME_DO_MENU] ?? m).join(", ") || "nenhum painel"}</span></summary>
              <FormAcao acao={editarUsuario.bind(null, u.id)} rotulo="Salvar" className="form-coluna">
                <EscolhaDeMenus marcados={u.relatorios} admin={u.admin} />
                <label>Nova senha (deixe em branco para manter)<input name="nova" type="password" autoComplete="new-password" /></label>
              </FormAcao>
              {u.id !== sessao.userId && <FormAcao acao={removerUsuario.bind(null, u.id)} rotulo="Remover usuário" perigo confirmar={`Remover ${u.usuario}? Isso não pode ser desfeito.`} />}
            </details>
          ))}
          <details className="cartao">
            <summary><b>Novo usuário</b></summary>
            <FormAcao acao={criarUsuario} rotulo="Criar" className="form-coluna">
              <label>Usuário<input name="usuario" required minLength={2} maxLength={32} autoComplete="off" /></label>
              <label>Senha<input name="senha" type="password" required minLength={8} autoComplete="new-password" /></label>
              <EscolhaDeMenus />
            </FormAcao>
          </details>
        </section>

        <section>
          <h2>Custos dos itens</h2>
          <p className="nota">Suprimentos: o preço de UMA unidade do estoque (na unidade mostrada). Se a unidade é CX, o preço da caixa. Vale no painel depois de Atualizar agora.</p>
          <form className="linha-form" method="get"><input name="q" defaultValue={q} placeholder="Buscar item" /><button className="btn sec pq">Buscar</button></form>
          {!custos?.data?.length && <p className="vazio">Nenhum item. Os itens aparecem aqui depois que o painel de Suprimentos for aberto uma vez com dados.</p>}
          <div className="tab-wrap"><table className="t"><thead><tr><th>Item</th><th>Un.</th><th className="n">Custo no Klingo</th><th>Custo informado (R$)</th></tr></thead><tbody>
            {custos?.data?.map((c) => (
              <tr key={c.item}><td className="txt">{c.item}<div className="micro">{c.embalagem}</div></td><td>{c.unidade}</td><td className="n">{c.custo_klingo != null ? Number(c.custo_klingo).toLocaleString("pt-BR", { minimumFractionDigits: 2 }) : "—"}</td>
                <td><FormAcao acao={salvarCusto.bind(null, c.item)} rotulo="Salvar"><input name="custo" defaultValue={c.custo ?? ""} inputMode="decimal" size={8} /><input name="observacao" defaultValue={c.observacao ?? ""} placeholder="Observação" /></FormAcao></td></tr>
            ))}
          </tbody></table></div>
        </section>

        <section>
          <h2>Conferir números</h2>
          <p className="nota">Cruza os relatórios entre si (produção × convênios, faturas emitidas × em aberto, recebido × movimentadas, Metas × produção, Cesta × produção).</p>
          <Conferir />
        </section>

        <section>
          <h2>Histórico de atualizações</h2>
          <div className="tab-wrap"><table className="t"><thead><tr><th>Quando</th><th>Painel</th><th>Situação</th><th>Quem</th><th className="n">Seg.</th><th>Mensagem</th></tr></thead><tbody>
            {hist?.data?.map((h, i) => <tr key={i}><td>{quando(h.data_hora)}</td><td>{NOME_DO_MENU[h.modulo_id as keyof typeof NOME_DO_MENU] ?? h.modulo_id}</td><td>{h.status}</td><td>{h.usuario}</td><td className="n">{Number(h.duracao_segundos).toFixed(0)}</td><td className="txt">{h.mensagem}</td></tr>)}
          </tbody></table></div>
        </section>

        <section>
          <h2>Auditoria</h2>
          <div className="tab-wrap"><table className="t"><thead><tr><th>Quando</th><th>Quem</th><th>O quê</th><th>Detalhe</th></tr></thead><tbody>
            {aud?.data?.map((a, i) => <tr key={i}><td>{quando(a.quando)}</td><td>{a.usuario ?? "—"}</td><td>{a.acao}</td><td className="txt micro">{JSON.stringify(a.detalhe)}</td></tr>)}
          </tbody></table></div>
        </section>
      </>)}
    </div>
  );
}

async function exigirAdminOuUsuario() {
  return exigirSessao();
}
