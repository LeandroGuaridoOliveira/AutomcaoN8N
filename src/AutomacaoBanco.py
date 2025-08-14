# ============================================================================
# AutomacaoBanco.py — Atualiza textos do PMP com auto-seed opcional
# ----------------------------------------------------------------------------
# O QUE ESTE SCRIPT FAZ
# - Lê uma planilha Excel (aba padrão "Planilha1") contendo colunas como:
#   id_tipo, Texto Principal, Texto Secundário, (opcionais: Texto Title, Texto Meta Description).
# - (Opcional) Se 'id_tipo' não existir, tenta mapear a partir de (id_cat, id_grupo)
#   consultando uma tabela de mapeamento no SQL Server.
# - (Opcional) Cria registros-base (seed) nas tabelas de destino quando idTipo não existe.
# - Atualiza os campos de texto em:
#       PMP.dbo.PUB_TIPOS_TEXTOS              (TextoPrimario, TextoSecundario, Ativo)
#       PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS      (TextoTitle, TextoMetaDescription, Ativo)
# - Possui DRY-RUN para pré-visualizar o seed sem gravar no banco.
#
# EXEMPLOS DE USO (PowerShell):
#   # Somente ver o que seria criado (seed) — NÃO grava no banco
#   python .\AutomacaoBanco.py ".\Semana 04.xlsx" --auto-seed --dry-run --max-seed 200 `
#     --pick-idconteudo min --map-table TEMATICOS_CONTEUDO_ITEM --tipo-col IDTIPO --conteudo-col ID --default-idconteudo 1
#
#   # Executar de verdade (remover --dry-run)
#   python .\AutomacaoBanco.py ".\Semana 04.xlsx" --auto-seed --max-seed 200 `
#     --pick-idconteudo min --map-table TEMATICOS_CONTEUDO_ITEM --tipo-col IDTIPO --conteudo-col ID --default-idconteudo 1
# ============================================================================

import argparse
import logging
import os
import pydrive2
import sys
from typing import Dict, Iterable, List, Set, Tuple


import pandas as pd

#  CONFIGURAÇÃO DE AMBIENTE 

# MODO: define contra qual ambiente rodar.
# - "LOCAL"         : usa SQLite de homologação
# - "PRODUCAO"      : SQL Server de produção
MODO = "HOMOLOGACAO"  # "LOCAL" | "HOMOLOGACAO" | "PRODUCAO"

# ENV: parâmetros por ambiente.
# - Em SQL Server, conectamos no DATABASE "Querys" para leitura/apoio (se aplicável)
#   e atualizamos no banco de destino DEST_DATABASE (PMP).
ENV = {
    "LOCAL": {
        "SQLITE_PATH": "teste_local_API.db",  # arquivo SQLite para testes
    },
    "HOMOLOGACAO": {
        "SERVER": "10.1.96.71",
        "DATABASE": "Querys",     # conecta no Querys (.71)
        "USE_TRUSTED": True,    
        "USERNAME": None,
        "PASSWORD": None,
        "DEST_DATABASE": "PMP",   # banco onde vamos atualizar as tabelas destino
    },
    "PRODUCAO": {
        "SERVER": "IP_SERVIDOR_PROD",
        "DATABASE": "Querys",
        "USE_TRUSTED": True,
        "USERNAME": None,         # se USE_TRUSTED=False, preencher usuário/senha
        "PASSWORD": None,
        "DEST_DATABASE": "PMP",
    },
}

# Configuração de LOG: grava eventos relevantes pra diagnóstico.
LOG_FILE = "importacao.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def log_print(msg: str):
    # Loga em arquivo e  imprime no console
    print(msg, flush=True)
    logging.info(msg)

# =========================================================
# ============== CONEXÃO COM O BANCO ======================
# =========================================================
def get_connection():
    """
    Abre a conexão conforme o MODO
    Retorno: (conn, kind, dest_db)
      - conn   : conexão aberta (sqlite3.Connection | pyodbc.Connection)
      - kind   : "LOCAL" (SQLite) ou "SQLSERVER"
      - dest_db: nome do banco de destino (ex.: "PMP") quando for SQL Server
    """
    if MODO == "LOCAL":
        # Conexão local via SQLite (não exige credencial). Útil para testes.
        import sqlite3
        cfg = ENV["LOCAL"]
        log_print(f"[DB] LOCAL sqlite={cfg['SQLITE_PATH']}")
        conn = sqlite3.connect(cfg["SQLITE_PATH"])
        conn.execute("PRAGMA foreign_keys = ON;")  # reforça integridade referencial (quando aplicável)
        return conn, "LOCAL", None

    elif MODO in ("HOMOLOGACAO", "PRODUCAO"):
        # Conexão SQL Server via ODBC Driver 17
        import pyodbc
        cfg = ENV[MODO]
        server = cfg["SERVER"]; database = cfg["DATABASE"]
        trusted = cfg["USE_TRUSTED"]; user = cfg["USERNAME"]; pwd = cfg["PASSWORD"]

        log_print(f"[DB] {MODO} SERVER={server} DB={database} trusted={trusted} dest={cfg.get('DEST_DATABASE')}")
        if trusted:
            # Autenticação integrada (Windows/AD)
            conn_str = (
                "DRIVER={ODBC Driver 17 for SQL Server};"
                f"SERVER={server};DATABASE={database};"
                "Trusted_Connection=yes;TrustServerCertificate=yes;Connection Timeout=10;"
            )
        else:
            # Autenticação por usuário/senha
            if not (user and pwd):
                raise ValueError("Preencha USERNAME/PASSWORD ou USE_TRUSTED=True.")
            conn_str = (
                "DRIVER={ODBC Driver 17 for SQL Server};"
                f"SERVER={server};DATABASE={database};UID={user};PWD={pwd};"
                "TrustServerCertificate=yes;Connection Timeout=10;"
            )
        conn = pyodbc.connect(conn_str, timeout=10)
        log_print("[DB] Conexão SQL Server OK.")
        return conn, "SQLSERVER", cfg.get("DEST_DATABASE")
    else:
        raise ValueError("MODO inválido")

    # AUXILIARES SQL

def _ph(n: int) -> str:
    # Retorna '?, ?, ?, ...' com n interrogações — usado em IN/VALUES parametrizados.
    return ",".join(["?"] * n)

def fetch_existing_idtipos(conn, dest_db: str, ids: List[int]) -> Set[int]:
    """
    Descobre quais idTipo já existem em PMP.dbo.PUB_TIPOS_TEXTOS.
    - Faz em blocos de 1000 para não estourar o tamanho do IN.
    - Retorna um select com os idTipo encontrados.
    """
    if not ids:
        return set()
    cur = conn.cursor()
    out: Set[int] = set()
    for i in range(0, len(ids), 1000):
        chunk = [int(x) for x in ids[i:i+1000]]
        cur.execute(
            f"SELECT idTipo FROM [{dest_db}].dbo.PUB_TIPOS_TEXTOS WHERE idTipo IN ({_ph(len(chunk))})",
            chunk
        )
        out.update(int(r[0]) for r in cur.fetchall())
    cur.close()
    return out

def resolve_idconteudo(conn, dest_db: str, missing_ids: Iterable[int],
                       map_table: str = "TEMATICOS_CONTEUDO_ITEM",
                       tipo_col: str = "IDTIPO",
                       conteudo_col: str = "ID",
                       pick: str = "min") -> Dict[int, int]:
    """
    Mapeia idTipo -> IdConteudo consultando uma tabela de apoio
    - Quando um idTipo tem múltiplos conteúdos, escolhe MIN ou MAX (parametrizável via 'pick')
    - Processa em blocos de 1000 para eficiência
    Retorna: dict { idTipo: IdConteudo }
    """
    ids = sorted(set(int(x) for x in missing_ids))
    if not ids:
        return {}
    fn = "MIN" if pick.lower() == "min" else "MAX"
    sql_base = f"""
        SELECT {tipo_col}, {fn}({conteudo_col}) AS IdConteudo
        FROM [{dest_db}].dbo.{map_table}
        WHERE {tipo_col} IN ({{placeholders}}) AND {conteudo_col} IS NOT NULL
        GROUP BY {tipo_col}
    """
    cur = conn.cursor()
    mapping: Dict[int, int] = {}
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i+1000]
        cur.execute(sql_base.format(placeholders=_ph(len(chunk))), chunk)
        for idt, idc in cur.fetchall():
            mapping[int(idt)] = int(idc)
    cur.close()
    return mapping

def seed_missing(conn, dest_db: str, idtipo_to_idconteudo: Dict[int, int], dry_run: bool=True) -> Tuple[int, int]:
    """
    Cria registros base (seed) quando um idTipo ainda não existe nas tabelas:
      - PMP.dbo.PUB_TIPOS_TEXTOS
      - PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS
    Em DRY-RUN apenas informa o que seria criado
    Retorna (qtde_TT, qtde_TL) — aqui mantido 0/0 pois usamos IF NOT EXISTS (idempotente)
    """
    if not idtipo_to_idconteudo:
        return (0, 0)

    t_tt = f"[{dest_db}].dbo.PUB_TIPOS_TEXTOS"
    t_tl = f"[{dest_db}].dbo.PUB_TIPOS_TEXTOS_TITULOS"
    to_do = sorted((int(k), int(v)) for k, v in idtipo_to_idconteudo.items())

    if dry_run:
        log_print(f"[DRY-RUN] Seed sugerido: {len(to_do)} idTipo → TT & TL")
        for idt, idc in to_do[:20]:  # evita log excessivo
            log_print(f"[DRY-RUN] idTipo={idt} IdConteudo={idc}")
        return (0, 0)

    cur = conn.cursor()
    cur.execute("BEGIN TRAN;")
    try:
        for idt, idc in to_do:
            # TT: cria registro com textos vazios (não-nulos) e Ativo=1
            cur.execute(
                f"IF NOT EXISTS (SELECT 1 FROM {t_tt} WHERE idTipo=?) "
                f"INSERT INTO {t_tt}(idTipo, TextoPrimario, TextoSecundario, Ativo, IdConteudo, Header) "
                f"VALUES (?, '', '', 1, ?, NULL);",
                (idt, idt, idc)
            )
            # TL: grava strings vazias para campos NOT NULL (evita NULL)
            cur.execute(
                f"IF NOT EXISTS (SELECT 1 FROM {t_tl} WHERE idTipo=?) "
                f"INSERT INTO {t_tl}(idTipo, TextoTitle, TextoMetaDescription, Ativo, IdConteudo) "
                f"VALUES (?, '', '', 1, ?);",
                (idt, idt, idc)
            )
        cur.execute("COMMIT;")
    except Exception:
        cur.execute("ROLLBACK;")
        raise
    finally:
        cur.close()

    return (0, 0)

# LIMPEZA DA PLANILHA 
def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Padroniza nomes de colunas e aceita pequenas variações (ex.: 'Secundario' sem acento).
    Retorna um novo DataFrame normalizado.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    rename_map = {
        "Texto Principal": "Texto Principal",
        "Texto Secundário": "Texto Secundário",
        "Texto Secundario": "Texto Secundário", 
        "Texto Title": "Texto Title",
        "Texto Meta Description": "Texto Meta Description",
        "id_tipo": "id_tipo",
        "id_cat": "id_cat",
        "id_grupo": "id_grupo",
    }
    for k, v in rename_map.items():
        if k in df.columns:
            df.rename(columns={k: v}, inplace=True)
    return df

def ensure_id_tipo(conn, dest_db: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Garante a coluna 'id_tipo' para atualização:
    - Se já existir em planilha, retorna sem alterações.
    - Caso contrário, tenta mapear via tabela: PMP/Querys.dbo.PROCESSADO_BUSCA_TIPOS
      usando (id_cat, id_grupo) -> idTipo.
    - Registra aviso com pares não mapeados.
    """
    df = df.copy()
    if "id_tipo" in df.columns:
        return df
    if not {"id_cat", "id_grupo"}.issubset(df.columns):
        raise ValueError("Planilha precisa ter 'id_tipo' ou ('id_cat' e 'id_grupo').")

    cur = conn.cursor()
    cats = sorted(x for x in pd.to_numeric(df["id_cat"], errors="coerce").dropna().astype(int).unique().tolist())
    grupos = sorted(x for x in pd.to_numeric(df["id_grupo"], errors="coerce").dropna().astype(int).unique().tolist())
    if not cats or not grupos:
        raise ValueError("Colunas 'id_cat' e 'id_grupo' não têm valores válidos para mapear id_tipo.")

    sql = f"""
        SELECT DISTINCT idCategoria, idGrupo, idTipo
        FROM [{dest_db}].dbo.PROCESSADO_BUSCA_TIPOS
        WHERE idCategoria IN ({_ph(len(cats))}) AND idGrupo IN ({_ph(len(grupos))})
    """
    cur.execute(sql, cats + grupos)
    rows = cur.fetchall()
    cur.close()

    # constrói dict {(idCategoria, idGrupo): idTipo}
    mapa = {(int(idc), int(idg)): int(idt) for (idc, idg, idt) in rows}

    def _map_row(r):
        try:
            idc = int(r["id_cat"]); idg = int(r["id_grupo"])
        except Exception:
            return pd.NA
        return mapa.get((idc, idg), pd.NA)

    df["id_tipo"] = df.apply(_map_row, axis=1)
    faltam = df[df["id_tipo"].isna()][["id_cat", "id_grupo"]].drop_duplicates().values.tolist()
    if faltam:
        log_print(f"Aviso: pares id_cat/id_grupo sem id_tipo mapeado (exibindo até 20): {faltam[:20]}")
    return df

def build_frames(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    A partir da planilha normalizada, constrói dois DataFrames minimos:
    - df_textos  -> PUB_TIPOS_TEXTOS (idTipo, TextoPrimario, TextoSecundario)
    - df_titulos -> PUB_TIPOS_TEXTOS_TITULOS (idTipo, TextoTitle, TextoMetaDescription) [se colunas existirem]
    Também aplica limites de tamanho para Title (80) e Meta (320), se presentes.
    """
    # Prepara base para TIPOS_TEXTOS
    df_textos = pd.DataFrame({
        "idTipo": pd.to_numeric(df["id_tipo"], errors="coerce").astype("Int64"),
        "TextoPrimario": df.get("Texto Principal", pd.Series([None]*len(df))),
        "TextoSecundario": df.get("Texto Secundário", pd.Series([None]*len(df))),
    })
    df_textos = df_textos[df_textos["idTipo"].notna()].copy()

    # Prepara base para TITULOS (apenas se as colunas existirem na planilha)
    has_title = "Texto Title" in df.columns
    has_meta  = "Texto Meta Description" in df.columns
    df_titulos = pd.DataFrame(columns=["idTipo","TextoTitle","TextoMetaDescription"])
    if has_title or has_meta:
        df_titulos = pd.DataFrame({
            "idTipo": pd.to_numeric(df["id_tipo"], errors="coerce").astype("Int64"),
            "TextoTitle": df.get("Texto Title", pd.Series([None]*len(df))),
            "TextoMetaDescription": df.get("Texto Meta Description", pd.Series([None]*len(df))),
        })
        df_titulos = df_titulos[df_titulos["idTipo"].notna()].copy()
        if has_title:
            df_titulos["TextoTitle"] = df_titulos["TextoTitle"].astype(str).str.slice(0, 80)
        if has_meta:
            df_titulos["TextoMetaDescription"] = df_titulos["TextoMetaDescription"].astype(str).str.slice(0, 320)
    return df_textos, df_titulos

# =========================================================
# ========== ATUALIZAÇÕES NAS TABELAS DESTINO =============
# =========================================================
def update_textos(conn, dest_db: str, df_textos: pd.DataFrame) -> int:
    """
    Atualiza PMP.dbo.PUB_TIPOS_TEXTOS com TextoPrimario/TextoSecundario e marca Ativo=1.
    Retorna a quantidade total de linhas afetadas (soma de rowcount).
    """
    if df_textos.empty:
        return 0
    cur = conn.cursor()
    updated = 0
    for _, r in df_textos.iterrows():
        idt = int(r["idTipo"])
        t1 = None if pd.isna(r["TextoPrimario"]) else str(r["TextoPrimario"])
        t2 = None if pd.isna(r["TextoSecundario"]) else str(r["TextoSecundario"])
        cur.execute(
            f"UPDATE [{dest_db}].dbo.PUB_TIPOS_TEXTOS "
            f"SET TextoPrimario=?, TextoSecundario=?, Ativo=1 "
            f"WHERE idTipo=?;",
            (t1, t2, idt)
        )
        updated += cur.rowcount
    conn.commit()
    cur.close()
    return updated

def update_titulos(conn, dest_db: str, df_titulos: pd.DataFrame) -> int:
    """
    Atualiza PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS com TextoTitle/TextoMetaDescription e Ativo=1.
    Retorna a quantidade de linhas afetadas.
    """
    if df_titulos.empty:
        return 0
    cur = conn.cursor()
    updated = 0
    for _, r in df_titulos.iterrows():
        idt = int(r["idTipo"])
        ttitle = None if pd.isna(r["TextoTitle"]) else str(r["TextoTitle"])
        tmeta  = None if pd.isna(r["TextoMetaDescription"]) else str(r["TextoMetaDescription"])
        cur.execute(
            f"UPDATE [{dest_db}].dbo.PUB_TIPOS_TEXTOS_TITULOS "
            f"SET TextoTitle=?, TextoMetaDescription=?, Ativo=1 "
            f"WHERE idTipo=?;",
            (ttitle, tmeta, idt)
        )
        updated += cur.rowcount
    conn.commit()
    cur.close()
    return updated


 #                                  -------- MAIN --------
def main():
    # Parser dos argumentos de execução (ajuda embutida com --help)
    ap = argparse.ArgumentParser(description="Atualiza textos do PMP a partir de XLSX (com auto-seed opcional).")
    ap.add_argument("excel_path", help="Caminho do arquivo .xlsx")
    ap.add_argument("--sheet", default="Planilha1", help="Nome da aba (padrão: Planilha1)")

    # Auto-seed: cria as linhas base nas tabelas destino para idTipos ausentes
    ap.add_argument("--auto-seed", action="store_true",
                    help="Criar linha base quando idTipo não existir (usa tabela de mapeamento)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pré-visualiza seeds (não grava no banco).")

    # Travas de segurança para evitar seeds acidentais em massa
    ap.add_argument("--max-seed", type=int, default=50,
                    help="Máximo de seeds permitidos por execução (default: 50)")
    ap.add_argument("--abort-if-missing-ratio", type=float, default=0.35,
                    help="Aborta se %% de pendentes > limite (0.0–1.0) quando não há --auto-seed (default: 0.35)")

    # Estratégia para escolher IdConteudo quando houver múltiplos por idTipo
    ap.add_argument("--pick-idconteudo", choices=["min","max"], default="min",
                    help="Usa MIN ou MAX(IdConteudo/ID) por idTipo ao mapear")

    # Parametrização da tabela de mapeamento (idTipo -> IdConteudo)
    ap.add_argument("--map-table", default="TEMATICOS_CONTEUDO_ITEM",
                    help="Tabela de mapeamento idTipo→IdConteudo")
    ap.add_argument("--tipo-col", default="IDTIPO",
                    help="Nome da coluna do idTipo na tabela de mapeamento")
    ap.add_argument("--conteudo-col", default="ID",
                    help="Nome da coluna do IdConteudo na tabela de mapeamento")

    # Fallback: IdConteudo padrão para quem não mapeou (ex.: 1)
    ap.add_argument("--default-idconteudo", type=int, default=None,
                    help="Usar este IdConteudo quando não houver mapeamento (ex.: 1)")

    args = ap.parse_args()

    # 1) Leitura e normalização da planilha
    if not os.path.exists(args.excel_path):
        print(f"Arquivo não encontrado: {args.excel_path}")
        sys.exit(2)
    df = pd.read_excel(args.excel_path, sheet_name=args.sheet)
    df = normalize_dataframe(df)

    # 2) Conexão com o banco (conforme MODO) e enriquecimento/mapeamento de ids
    conn, kind, dest_db = get_connection()
    try:
        if kind == "SQLSERVER":
            # Garante a coluna id_tipo (mapeia a partir de id_cat/id_grupo se necessário)
            df = ensure_id_tipo(conn, dest_db, df)

        # 3) Constrói DataFrames prontos para UPDATE por tabela de destino
        df_tt, df_tl = build_frames(df)
        log_print(f"Lidas: TIPOS_TEXTOS={len(df_tt)} | TITULOS(após filtro)={len(df_tl)}")

        # 4) Lista de idTipos presentes na planilha (base de comparação)
        ids_plan = pd.to_numeric(df["id_tipo"], errors="coerce").dropna().astype(int).unique().tolist()

        if kind == "SQLSERVER":
            # 5) Verifica o que já existe no PMP e o que está faltando
            existentes = fetch_existing_idtipos(conn, dest_db, ids_plan)
            faltam_all = sorted(set(ids_plan) - existentes)
            log_print(f"No PMP: existem={len(existentes)} | faltam={len(faltam_all)}")
            log_print(f"IDs faltando (na planilha mas não no PMP): {faltam_all}")

            # 6) Trava: se muitos faltarem e não for usar auto-seed, aborta para evitar erro humano
            if ids_plan and not args.auto_seed:
                missing_ratio = len(faltam_all) / len(ids_plan)
                if missing_ratio > args.abort_if_missing_ratio:
                    log_print(f"ATENÇÃO: {missing_ratio:.0%} pendentes (> limite {args.abort_if_missing_ratio:.0%}). Rode com --auto-seed ou ajuste o limite.")
                    return

            # 7) Se autorizado, faz seed dos idTipos ausentes (limitado por --max-seed)
            if args.auto_seed and len(faltam_all) > 0:
                if len(faltam_all) > args.max_seed:
                    log_print(f"ATENÇÃO: seeds necessários ({len(faltam_all)}) > max-seed ({args.max_seed}). Abortando por segurança.")
                    return

                # Mapeia idTipo -> IdConteudo conforme tabela/colunas informadas
                mapa = resolve_idconteudo(conn, dest_db, faltam_all,
                                          map_table=args.map_table,
                                          tipo_col=args.tipo_col,
                                          conteudo_col=args.conteudo_col,
                                          pick=args.pick_idconteudo)
                sem_mapa = sorted(set(faltam_all) - set(mapa.keys()))
                log_print(f"Mapeados idTipo - IdConteudo: {len(mapa)} | Sem IdConteudo: {len(sem_mapa)}")

                # Fallback opcional para quem não veio no mapa
                if args.default_idconteudo is not None and sem_mapa:
                    for idt in sem_mapa:
                        mapa[idt] = args.default_idconteudo
                    log_print(f"Fallback aplicado: IdConteudo={args.default_idconteudo} para {len(sem_mapa)} idTipo sem mapeamento.")
                    sem_mapa = []

                # Executa o seed (ou apenas mostra, se --dry-run)
                tt_ins, tl_ins = seed_missing(conn, dest_db, mapa, dry_run=args.dry_run)
                log_print(f"Seed TT inseridos: {tt_ins} | TL inseridos: {tl_ins}")
                if sem_mapa:
                    log_print(f"Sem IdConteudo (tratar manualmente): {sem_mapa[:20]}{' ...' if len(sem_mapa)>20 else ''}")
                if args.dry_run:
                    log_print("DRY-RUN: nenhuma alteração feita. Encerrando antes do UPDATE.")
                    return

                # Reconta existentes após criar seeds
                existentes = fetch_existing_idtipos(conn, dest_db, ids_plan)

            # 8) Atualiza apenas os idTipos que efetivamente existem no destino
            df_tt = df_tt[df_tt["idTipo"].isin(existentes)].copy()
            df_tl = df_tl[df_tl["idTipo"].isin(existentes)].copy()

        # 9) Executa UPDATEs em cada tabela
        upd_tt = update_textos(conn, dest_db, df_tt) if not df_tt.empty else 0
        upd_tl = update_titulos(conn, dest_db, df_tl) if not df_tl.empty else 0
        log_print(f"Atualizados TIPOS_TEXTOS: {upd_tt}")
        log_print(f"Atualizados TITULOS     : {upd_tl}")
        log_print("Concluído.")
    finally:
        # 10) Fecha a conexão (garantido mesmo em caso de erro)
        conn.close()

if __name__ == "__main__":
    main()
