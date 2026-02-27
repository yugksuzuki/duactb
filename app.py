import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import Client, create_client

# CSS para melhor responsividade
st.markdown("""
<style>
    /* Improve container width on mobile */
    .main { max-width: 100%; }
    
    /* Responsive padding */
    .main > div { padding: 0 1rem; }
    
    /* Better spacing for small screens */
    @media (max-width: 640px) {
        .main > div { padding: 0 0.5rem; }
        h1 { font-size: 1.5rem !important; }
        h2 { font-size: 1.2rem !important; }
    }
    
    /* Fix column layout on mobile */
    [data-testid="column"] { flex-wrap: wrap; }
    
    /* Better table responsiveness */
    .stDataFrame { overflow-x: auto; }
    
    /* Improve form responsiveness */
    .stForm { width: 100%; }
</style>
""", unsafe_allow_html=True)

# Tenta importar a biblioteca de feriados (se não tiver, ele pula apenas os finais de semana)
try:
    import holidays
    FERIADOS_BR = holidays.Brazil()
    TEM_HOLIDAYS = True
except ImportError:
    FERIADOS_BR = []
    TEM_HOLIDAYS = False

def ajustar_dia_util(data_ts: pd.Timestamp) -> pd.Timestamp:
    """Avança a data para o próximo dia útil se cair em final de semana ou feriado."""
    while data_ts.weekday() >= 5 or data_ts.date() in FERIADOS_BR:
        data_ts += pd.Timedelta(days=1)
    return data_ts


@st.cache_resource
def get_supabase_client() -> Client:
    """Cria e devolve o cliente do Supabase."""
    supabase_url = None
    supabase_key = None

    try:
        supabase_url = st.secrets.get("SUPABASE_URL")
        supabase_key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        pass

    if not supabase_url:
        supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_key:
        supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        st.error(
            "Credenciais do Supabase não encontradas.\n\n"
            "Defina `SUPABASE_URL` e `SUPABASE_KEY` em `st.secrets` "
            "ou como variáveis de ambiente."
        )
        st.stop()

    return create_client(supabase_url, supabase_key)


def carregar_clientes(supabase: Client) -> pd.DataFrame:
    resp = supabase.table("clientes").select("*").execute()
    data = resp.data or []
    return pd.DataFrame(data)


def carregar_cobrancas(supabase: Client) -> pd.DataFrame:
    resp = supabase.table("cobrancas").select("*").execute()
    data = resp.data or []
    return pd.DataFrame(data)


def calcular_saldo_por_cliente(
    df_cobrancas: pd.DataFrame, df_clientes: pd.DataFrame
) -> pd.DataFrame:
    if df_cobrancas.empty or "valor" not in df_cobrancas.columns:
        return pd.DataFrame(columns=["cliente_id", "cliente_nome", "saldo_pendente"])

    df = df_cobrancas.copy()

    if "status" in df.columns:
        df = df[df["status"] == "pendente"]

    if df.empty:
        return pd.DataFrame(columns=["cliente_id", "cliente_nome", "saldo_pendente"])

    if "cliente_id" not in df.columns:
        soma_total = df["valor"].sum()
        return pd.DataFrame([{"cliente_id": None, "cliente_nome": None, "saldo_pendente": soma_total}])

    df_group = df.groupby("cliente_id")["valor"].sum().reset_index(name="saldo_pendente")
    cliente_nome_col = "cliente_nome"

    if not df_clientes.empty and "id" in df_clientes.columns:
        df_aux = df_clientes.copy()
        if "nome" in df_aux.columns:
            df_aux = df_aux[["id", "nome"]].rename(columns={"id": "cliente_id", "nome": cliente_nome_col})
            df_group = df_group.merge(df_aux, on="cliente_id", how="left")

    return df_group


def pagina_dashboard(supabase: Client) -> None:
    st.title("Dashboard")

    df_clientes = carregar_clientes(supabase)
    df_cobrancas = carregar_cobrancas(supabase)

    if df_cobrancas.empty:
        st.info("Ainda não há boletos/cobranças cadastrados.")
        return

    df_saldo = calcular_saldo_por_cliente(df_cobrancas, df_clientes)
    total_a_receber = df_saldo["saldo_pendente"].sum() if not df_saldo.empty else 0.0
    total_emitido = float(df_cobrancas["valor"].sum())

    df_pagos = (
        df_cobrancas[df_cobrancas["status"] == "pago"].copy()
        if "status" in df_cobrancas.columns
        else df_cobrancas.iloc[0:0].copy()
    )
    total_recebido = float(df_pagos["valor"].sum()) if not df_pagos.empty else 0.0
    perc_recebido = ((total_recebido / total_emitido * 100.0) if total_emitido > 0 else 0.0)

    qtd_boletos = int(len(df_cobrancas))
    qtd_pendentes = int(len(df_cobrancas[df_cobrancas["status"] == "pendente"])) if "status" in df_cobrancas.columns else qtd_boletos
    qtd_pagos = int(len(df_pagos))
    qtd_clientes_total = int(len(df_clientes)) if not df_clientes.empty else 0
    qtd_clientes_com_movimento = int(df_cobrancas["cliente_id"].nunique()) if "cliente_id" in df_cobrancas.columns else 0

    st.subheader("Visão Geral")
    
    # Responsive columns - 2 colunas em telas pequenas, 4 em telas grandes
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1], gap="small")
    with col1:
        st.metric("Total a Receber (R$)", f"{total_a_receber:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    with col2:
        st.metric("Total Emitido (R$)", f"{total_emitido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    with col3:
        st.metric("Total Recebido (R$)", f"{total_recebido:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    with col4:
        st.metric("% Recebido", f"{perc_recebido:.1f}%")

    col5, col6, col7, col8 = st.columns([1, 1, 1, 1], gap="small")
    with col5:
        st.metric("Boletos Pendentes", f"{qtd_pendentes}")
    with col6:
        st.metric("Boletos Pagos", f"{qtd_pagos}")
    with col7:
        st.metric("Clientes com Movimento", f"{qtd_clientes_com_movimento}")
    with col8:
        st.metric("Total de Clientes", f"{qtd_clientes_total}")

    if not df_saldo.empty:
        st.markdown("#### Top Devedores (Pendentes)")
        df_view = df_saldo.copy().sort_values("saldo_pendente", ascending=False).head(10)
        if "cliente_nome" in df_view.columns:
            df_view["Cliente"] = df_view["cliente_nome"]
        else:
            df_view["Cliente"] = None

        if "Cliente" in df_view.columns and "cliente_id" in df_view.columns:
            df_view["Cliente"] = df_view["Cliente"].fillna(df_view["cliente_id"].astype(str))

        cols_to_show = [c for c in ["Cliente", "saldo_pendente"] if c in df_view.columns]
        st.dataframe(
            df_view[cols_to_show].rename(columns={"saldo_pendente": "Saldo Pendente (R$)"}),
            use_container_width=True,
            hide_index=True
        )

    st.markdown("#### Próximos Vencimentos (Pendentes)")
    df_pend_venc = df_cobrancas.copy()
    if "status" in df_pend_venc.columns:
        df_pend_venc = df_pend_venc[df_pend_venc["status"] == "pendente"]

    if not df_pend_venc.empty:
        if not df_clientes.empty and "id" in df_clientes.columns and "cliente_id" in df_pend_venc.columns:
            df_cli = df_clientes.copy()[["id", "nome"]].rename(columns={"id": "cliente_id", "nome": "cliente_nome"})
            df_pend_venc = df_pend_venc.merge(df_cli, on="cliente_id", how="left")

        venc_col = "vencimento" if "vencimento" in df_pend_venc.columns else "data_vencimento"
        
        if venc_col in df_pend_venc.columns:
            df_pend_venc[venc_col] = pd.to_datetime(df_pend_venc[venc_col], utc=True, errors="coerce")
            df_pend_venc = df_pend_venc.sort_values(venc_col).head(15)

            hoje = pd.Timestamp.now(tz="UTC").normalize()
            df_pend_venc["dias_em_atraso"] = ((hoje - df_pend_venc[venc_col]).dt.days).clip(lower=0)
            df_pend_venc[venc_col] = df_pend_venc[venc_col].dt.strftime('%d/%m/%Y')

            cols = ["cliente_nome", venc_col, "valor", "dias_em_atraso", "arquivo_url"]
            cols = [c for c in cols if c in df_pend_venc.columns]

            st.dataframe(
                df_pend_venc[cols].rename(
                    columns={
                        "cliente_nome": "Cliente",
                        venc_col: "Vencimento",
                        "valor": "Valor (R$)",
                        "dias_em_atraso": "Dias em atraso",
                        "arquivo_url": "Arquivo"
                    }
                ),
                column_config={
                    "Arquivo": st.column_config.LinkColumn("Boleto", display_text="Abrir PDF/Img")
                },
                hide_index=True,
                use_container_width=True
            )
    else:
        st.info("Nenhum boleto pendente para próximos vencimentos.")

    st.markdown("---")
    st.subheader("Receitas (Boletos Pagos)")
    df_receitas = df_cobrancas.copy()
    if "status" in df_receitas.columns:
        df_receitas = df_receitas[df_receitas["status"] == "pago"]

    data_col = next((c for c in ["data_pagamento", "data", "created_at"] if c in df_receitas.columns), None)

    if df_receitas.empty or not data_col:
        st.info("Ainda não há receitas pagas ou não foi encontrada uma coluna de data.")
        return

    df_receitas[data_col] = pd.to_datetime(df_receitas[data_col])
    df_receitas["mes"] = df_receitas[data_col].dt.to_period("M").dt.to_timestamp()
    df_por_mes = df_receitas.groupby("mes")["valor"].sum().reset_index().sort_values("mes")

    fig = px.bar(
        df_por_mes, x="mes", y="valor",
        labels={"mes": "Mês", "valor": "Receita (R$)"}, 
        title="Receitas por mês"
    )
    fig.update_layout(hovermode="x unified", margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)


def pagina_cadastrar_cliente(supabase: Client) -> None:
    st.title("Cadastro de Clientes")
    
    # Remover padding desnecessário em telas pequenas
    st.markdown("""
    <style>
        .reportview-container { max-width: 100%; }
    </style>
    """, unsafe_allow_html=True)

    with st.form("form_cadastro_cliente", clear_on_submit=True):
        nome = st.text_input("Nome do Cliente", max_chars=150)
        
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            documento = st.text_input("Documento (CPF/CNPJ)", max_chars=20)
        with col2:
            email = st.text_input("E-mail", max_chars=150)
        
        telefone = st.text_input("Telefone", max_chars=50)
        
        st.markdown("---")
        if st.form_submit_button("Salvar Cliente", use_container_width=True):
            if not nome:
                st.warning("O campo Nome é obrigatório.")
                return

            data = {
                "nome": nome, "documento": documento or None,
                "email": email or None, "telefone": telefone or None,
                "created_at": datetime.utcnow().isoformat(),
            }
            try:
                supabase.table("clientes").insert(data).execute()
                st.success("✅ Cliente cadastrado com sucesso!")
                st.balloons()
            except Exception as e:
                st.error(f"❌ Erro ao cadastrar cliente: {e}")


def pagina_lancar_cobranca(supabase: Client) -> None:
    st.set_page_config(layout="wide")
    st.title("Lançar Boletos")

    df_clientes = carregar_clientes(supabase)
    if df_clientes.empty:
        st.info("Você precisa cadastrar clientes antes de lançar cobranças.")
        return

    df_clientes = df_clientes.sort_values("nome")
    nomes_clientes = df_clientes["nome"].tolist()

    st.markdown("### Configuração do Lançamento")
    tipo_lancamento = st.radio("Formato do Lançamento:", ["Único", "Parcelado"], horizontal=True)

    qtd_parcelas = 1
    preenchimento_auto = True
    
    # Variáveis padrão
    tipo_intervalo = "Mensal (Mesmo dia)"
    dias_intervalo = 30
    pular_fds = True

    if tipo_lancamento == "Parcelado":
        col_qtd, col_check = st.columns([1, 2], gap="medium")
        with col_qtd:
            qtd_parcelas = st.number_input("Quantidade de Parcelas", min_value=2, max_value=120, step=1, value=2)
        with col_check:
            st.write("")
            preenchimento_auto = st.checkbox("Valores iguais para todas as parcelas (Automático)", value=True)
            
        # MOVIDO PARA FORA DO FORMULÁRIO: Agora a tela atualiza na hora!
        if preenchimento_auto:
            st.markdown("##### Regras de Vencimento")
            col_i1, col_i2 = st.columns([1.5, 1.5], gap="medium")
            
            with col_i1:
                tipo_intervalo = st.selectbox("Intervalo entre parcelas", ["Mensal (Mesmo dia)", "Personalizado (Dias Corridos)"])
                if tipo_intervalo == "Personalizado (Dias Corridos)":
                    dias_intervalo = st.number_input("A cada quantos dias?", min_value=1, value=15, step=1)
            
            with col_i2:
                st.write("")
                pular_fds = st.checkbox("Avançar sábados, domingos e feriados", value=True)
                if pular_fds and not TEM_HOLIDAYS:
                    st.caption("⚠️ Feriados não suportados. Rode `pip install holidays` no terminal para ativar.")

    st.markdown("---")

    with st.form("form_lancar_cobranca", clear_on_submit=True):
        cliente_nome = st.selectbox("Cliente", nomes_clientes)
        descricao = st.text_area("Descrição Geral (aplicada a todos)", height=68)
        
        st.markdown("**Arquivo Global (Opcional)**")
        st.caption("Anexe aqui se você tiver um ÚNICO arquivo para vincular a todas as parcelas deste lançamento.")
        arquivo_global = st.file_uploader("Arquivo Único", type=["pdf", "png", "jpg", "jpeg"], label_visibility="collapsed")
        
        parcelas_info = []
        valor_base = 0.0
        data_base = pd.Timestamp.today().date()

        if tipo_lancamento == "Único":
            col1, col2 = st.columns(2, gap="medium")
            with col1:
                valor_base = st.number_input("Valor (R$)", min_value=0.0, step=0.01, format="%.2f")
            with col2:
                data_base = st.date_input("Data de Vencimento", label_visibility="visible")

        elif tipo_lancamento == "Parcelado" and preenchimento_auto:
            st.info(f"O sistema irá gerar **{qtd_parcelas} parcelas** automaticamente com as regras selecionadas acima.")
            col1, col2 = st.columns(2, gap="medium")
            with col1:
                valor_base = st.number_input("Valor de CADA parcela (R$)", min_value=0.0, step=0.01, format="%.2f")
            with col2:
                data_base = st.date_input("Data do 1º Vencimento", label_visibility="visible")

        elif tipo_lancamento == "Parcelado" and not preenchimento_auto:
            st.caption("Ajuste os valores, datas ou anexe boletos individuais de cada parcela abaixo:")
            with st.expander("🔽 Detalhamento das Parcelas", expanded=True):
                for i in range(qtd_parcelas):
                    st.markdown(f"**Parcela {i+1}**")
                    venc_sugerido = (pd.Timestamp.today() + pd.DateOffset(months=i)).date()
                    col1, col2 = st.columns(2, gap="medium")
                    with col1:
                        v = st.number_input(f"Valor (R$)", min_value=0.0, step=0.01, format="%.2f", key=f"val_{i}")
                    with col2:
                        d = st.date_input(f"Vencimento", value=venc_sugerido, key=f"venc_{i}")
                    
                    arq_indiv = st.file_uploader(f"Anexo Específico - Parcela {i+1} (Opcional)", type=["pdf", "png", "jpg", "jpeg"], key=f"arq_{i}", label_visibility="collapsed")
                    parcelas_info.append({"valor": v, "vencimento": d, "arquivo": arq_indiv})
                    st.divider()

        st.markdown("---")
        if st.form_submit_button("Lançar Boleto(s)", use_container_width=True):
            cliente_row = df_clientes[df_clientes["nome"] == cliente_nome].iloc[0]
            cliente_id = int(cliente_row["id"])
            payload_list = []
            valor_total = 0.0
            
            if tipo_lancamento == "Único":
                if valor_base <= 0: st.warning("O valor deve ser maior que zero."); return
                payload_list.append({
                    "cliente_id": cliente_id, "valor": float(valor_base),
                    "vencimento": str(data_base), "data_vencimento": datetime.combine(data_base, datetime.min.time()).isoformat(),
                    "descricao": descricao or None, "status": "pendente", "created_at": datetime.utcnow().isoformat(),
                })
            
            elif tipo_lancamento == "Parcelado" and preenchimento_auto:
                if valor_base <= 0: st.warning("O valor deve ser maior que zero."); return
                
                for i in range(qtd_parcelas):
                    if tipo_intervalo == "Mensal (Mesmo dia)":
                        venc_base_parcela = pd.to_datetime(data_base) + pd.DateOffset(months=i)
                    else:
                        venc_base_parcela = pd.to_datetime(data_base) + pd.Timedelta(days=(dias_intervalo * i))
                    
                    if pular_fds:
                        venc_final_dt = ajustar_dia_util(venc_base_parcela)
                    else:
                        venc_final_dt = venc_base_parcela
                        
                    venc_atual = venc_final_dt.date()
                    texto_parcela = f"(Parcela {i+1}/{qtd_parcelas})"
                    desc_final = f"{descricao} {texto_parcela}".strip() if descricao else texto_parcela
                    valor_total += valor_base
                    
                    payload_list.append({
                        "cliente_id": cliente_id, "valor": float(valor_base),
                        "vencimento": str(venc_atual), "data_vencimento": datetime.combine(venc_atual, datetime.min.time()).isoformat(),
                        "descricao": desc_final, "status": "pendente", "created_at": datetime.utcnow().isoformat(),
                    })
            
            else: # Manual
                if any(p["valor"] <= 0 for p in parcelas_info): st.warning("Valores devem ser maiores que zero."); return
                for i, p in enumerate(parcelas_info):
                    texto_parcela = f"(Parcela {i+1}/{qtd_parcelas})"
                    desc_final = f"{descricao} {texto_parcela}".strip() if descricao else texto_parcela
                    valor_total += p["valor"]
                    payload_list.append({
                        "cliente_id": cliente_id, "valor": float(p["valor"]),
                        "vencimento": str(p["vencimento"]), "data_vencimento": datetime.combine(p["vencimento"], datetime.min.time()).isoformat(),
                        "descricao": desc_final, "status": "pendente", "created_at": datetime.utcnow().isoformat(),
                    })

            try:
                response = supabase.table("cobrancas").insert(payload_list).execute()
                dados_inseridos = response.data

                url_global = None
                if arquivo_global and dados_inseridos:
                    primeiro_id = dados_inseridos[0]["id"]
                    path_global = f"{primeiro_id}/global_{datetime.utcnow().isoformat().replace(':', '-')}_{arquivo_global.name}"
                    bucket = supabase.storage.from_("boletos")
                    bucket.upload(path_global, arquivo_global.read(), file_options={"content-type": arquivo_global.type})
                    url_global = bucket.get_public_url(path_global)

                if dados_inseridos:
                    for i, item in enumerate(dados_inseridos):
                        cobranca_id = item["id"]
                        url_final = None

                        if tipo_lancamento == "Parcelado" and not preenchimento_auto:
                            arquivo_especifico = parcelas_info[i]["arquivo"]
                            if arquivo_especifico:
                                path_indiv = f"{cobranca_id}/indiv_{datetime.utcnow().isoformat().replace(':', '-')}_{arquivo_especifico.name}"
                                bucket = supabase.storage.from_("boletos")
                                bucket.upload(path_indiv, arquivo_especifico.read(), file_options={"content-type": arquivo_especifico.type})
                                url_final = bucket.get_public_url(path_indiv)
                            else:
                                url_final = url_global
                        else:
                            url_final = url_global

                        if url_final:
                            supabase.table("cobrancas").update({"arquivo_url": url_final}).eq("id", cobranca_id).execute()

                st.success("✅ Lançamento realizado com sucesso!")
                if tipo_lancamento == "Parcelado":
                    st.info(f"💰 Valor Total: R$ {valor_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            except Exception as e:
                st.error(f"Erro ao lançar cobrança(s): {e}")

def pagina_editar_cobranca(supabase: Client) -> None:
    st.title("Editar / Corrigir Boletos")

    df_clientes = carregar_clientes(supabase)
    df_cobrancas = carregar_cobrancas(supabase)

    if df_cobrancas.empty:
        st.info("Não há boletos cadastrados para editar.")
        return

    if "vencimento" in df_cobrancas.columns and "cliente_id" in df_cobrancas.columns:
        df_cobrancas = df_cobrancas.sort_values(by=["cliente_id", "vencimento"])

    df_edit = df_cobrancas.copy()
    
    if not df_clientes.empty and "id" in df_clientes.columns:
        df_cli_aux = df_clientes[['id', 'nome']].rename(columns={'id': 'cliente_id_link', 'nome': 'nome_do_cliente'})
        df_edit = df_edit.merge(df_cli_aux, left_on='cliente_id', right_on='cliente_id_link', how='left')

    df_edit["label"] = df_edit.apply(
        lambda r: f"ID: {r['id']} | {r.get('nome_do_cliente', 'Sem Nome')} | R$ {float(r['valor']):,.2f} | Venc: {r.get('vencimento', '')}", axis=1
    )

    escolha = st.selectbox("Selecione o boleto para editar", options=df_edit["label"].tolist())
    dados_atuais = df_edit[df_edit["label"] == escolha].iloc[0]
    id_boleto = int(dados_atuais["id"])

    with st.form("form_editar_cobranca"):
        st.subheader(f"Editando Registro #{id_boleto}")
        
        nomes_clientes = df_clientes["nome"].tolist() if not df_clientes.empty else []
        nome_atual = dados_atuais.get("nome_do_cliente", "")
        idx_cliente = nomes_clientes.index(nome_atual) if nome_atual in nomes_clientes else 0
        
        novo_cliente_nome = st.selectbox("Cliente", nomes_clientes, index=idx_cliente)
        
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            novo_valor = st.number_input("Valor (R$)", value=float(dados_atuais["valor"]), step=0.01)
            try:
                data_venc_original = pd.to_datetime(dados_atuais["vencimento"]).date()
            except Exception:
                data_venc_original = datetime.now().date()
            novo_vencimento = st.date_input("Data de Vencimento", value=data_venc_original)
        
        with col2:
            status_opcoes = ["pendente", "pago", "baixado"]
            status_atual = str(dados_atuais.get("status", "pendente")).lower()
            if status_atual not in status_opcoes: status_atual = "pendente"
            novo_status = st.selectbox("Status", status_opcoes, index=status_opcoes.index(status_atual))
            
            desc_atual = dados_atuais.get("descricao", "")
            if pd.isna(desc_atual) or desc_atual is None: desc_atual = ""
            nova_desc = st.text_area("Descrição", value=str(desc_atual), height=107)

        st.markdown("**Atualizar Anexo**")
        if pd.notna(dados_atuais.get("arquivo_url")):
            st.info(f"[🔗 Ver Arquivo Atual do Boleto]({dados_atuais['arquivo_url']})")
        arquivo = st.file_uploader("Substituir Boleto (Deixe em branco para manter o atual)", type=["pdf", "png", "jpg", "jpeg"])

        st.markdown("---")
        if st.form_submit_button("Salvar Alterações", use_container_width=True):
            novo_cliente_id = int(df_clientes[df_clientes["nome"] == novo_cliente_nome]["id"].iloc[0])
            
            payload = {
                "cliente_id": novo_cliente_id,
                "valor": float(novo_valor),
                "vencimento": str(novo_vencimento),
                "data_vencimento": datetime.combine(novo_vencimento, datetime.min.time()).isoformat(),
                "descricao": nova_desc if nova_desc.strip() else None,
                "status": novo_status
            }

            try:
                if arquivo:
                    path = f"{id_boleto}/{datetime.utcnow().isoformat().replace(':', '-')}_{arquivo.name}"
                    bucket = supabase.storage.from_("boletos")
                    bucket.upload(path, arquivo.read(), file_options={"content-type": arquivo.type})
                    payload["arquivo_url"] = bucket.get_public_url(path)

                supabase.table("cobrancas").update(payload).eq("id", id_boleto).execute()
                st.success(f"Boleto #{id_boleto} atualizado com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao atualizar: {e}")


def pagina_baixar_boletos(supabase: Client) -> None:
    st.title("Baixar / Pagar Boletos")

    df_clientes = carregar_clientes(supabase)
    df_cobrancas = carregar_cobrancas(supabase)

    if df_cobrancas.empty:
        st.info("Ainda não há boletos cadastrados.")
        return

    df_abertos = df_cobrancas[df_cobrancas["status"] == "pendente"].copy() if "status" in df_cobrancas.columns else df_cobrancas.copy()

    if df_abertos.empty:
        st.success("Não há boletos pendentes para baixar ou marcar como pagos.")
        return
    
    if "vencimento" in df_abertos.columns and "cliente_id" in df_abertos.columns:
        df_abertos = df_abertos.sort_values(by=["cliente_id", "vencimento"])

    if not df_clientes.empty and "id" in df_clientes.columns and "cliente_id" in df_abertos.columns:
        df_cli = df_clientes.copy()[["id", "nome"]].rename(columns={"id": "cliente_id", "nome": "cliente_nome"})
        df_abertos = df_abertos.merge(df_cli, on="cliente_id", how="left")

    df_abertos["cliente_label"] = df_abertos.get("cliente_nome", df_abertos.get("cliente_id", ""))
    df_abertos["venc_label"] = df_abertos.get("vencimento", df_abertos.get("data_vencimento", ""))
    
    df_abertos["vencimento_formatado"] = pd.to_datetime(df_abertos["venc_label"]).dt.strftime('%d/%m/%Y')
    
    st.markdown("#### Boletos Pendentes")
    cols_display = ["id", "cliente_label", "valor", "vencimento_formatado", "descricao", "arquivo_url"]
    cols_display = [c for c in cols_display if c in df_abertos.columns]
    
    st.dataframe(
        df_abertos[cols_display].rename(
            columns={
                "id": "ID", "cliente_label": "Cliente", "valor": "Valor (R$)",
                "vencimento_formatado": "Vencimento", "descricao": "Descrição", "arquivo_url": "Anexo"
            }
        ),
        column_config={
            "Anexo": st.column_config.LinkColumn("Boleto", display_text="Abrir PDF/Img")
        },
        hide_index=True,
        use_container_width=True
    )

    df_abertos["label"] = df_abertos.apply(
        lambda row: f"ID {row['id']} | {row['cliente_label']} | R$ {float(row['valor']):,.2f} | Venc: {row['venc_label']}", axis=1
    )

    st.markdown("---")
    with st.form("form_baixar_boleto"):
        escolha_label = st.selectbox("Selecione o boleto para atualizar", options=df_abertos["label"].tolist())
        acao = st.radio("Marcar como:", ("Pago", "Baixado / Cancelado"), horizontal=False)
        
        st.markdown("---")
        if st.form_submit_button("Confirmar Baixa", use_container_width=True):
            cobranca_id = int(df_abertos[df_abertos["label"] == escolha_label].iloc[0]["id"])
            novo_status = "pago" if acao == "Pago" else "baixado"
            
            payload_completo = {"status": novo_status, "data_pagamento": datetime.utcnow().isoformat()}

            try:
                supabase.table("cobrancas").update(payload_completo).eq("id", cobranca_id).execute()
                st.success(f"Boleto ID {cobranca_id} marcado como {novo_status}.")
                st.rerun()
            except Exception:
                try:
                    supabase.table("cobrancas").update({"status": novo_status}).eq("id", cobranca_id).execute()
                    st.success(f"Boleto ID {cobranca_id} marcado como {novo_status}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao atualizar boleto: {e}")


def main() -> None:
    st.set_page_config(page_title="ERP Devedores", page_icon="💰", layout="wide", initial_sidebar_state="expanded")

    st.sidebar.title("Menu")
    opcao = st.sidebar.radio(
        "Navegação",
        ("Cadastro de Clientes", "Lançar Boletos", "Editar Boleto", "Baixar / Pagar Boletos", "Dashboard")
    )

    supabase = get_supabase_client()

    if opcao == "Cadastro de Clientes":
        pagina_cadastrar_cliente(supabase)
    elif opcao == "Lançar Boletos":
        pagina_lancar_cobranca(supabase)
    elif opcao == "Editar Boleto":
        pagina_editar_cobranca(supabase)
    elif opcao == "Baixar / Pagar Boletos":
        pagina_baixar_boletos(supabase)
    elif opcao == "Dashboard":
        pagina_dashboard(supabase)

if __name__ == "__main__":
    main()