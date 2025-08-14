
# 📄 Script de Importação de Planilha para Banco de Dados (Versão Final)

## 🎯 Objetivo
Este script automatiza a **importação de textos gerados pela IA** a partir de uma planilha Excel, inserindo-os diretamente no **SQL Server** nas tabelas:

- `PUB_TIPOS_TEXTOS`
- `PUB_TIPOS_TEXTOS_TITULOS`

Possui suporte para **modo de teste** com SQLite e **modo de produção** com SQL Server via `pyodbc`.

---

## 🛠️ Fluxo Geral

1. **Leitura da planilha**.
2. **Modelagem dos dados** no formato correto das tabelas do banco.
3. **Conexão ao banco**:
   - TESTE → SQLite.
   - PRODUÇÃO → SQL Server.
4. **Inserção dos dados**:
   - TESTE → Inserção simples.
   - PRODUÇÃO → UPSERT com `MERGE`.
5. **Validação** (TESTE).
6. **Registro em log** de todas as ações e erros.

---

## 📂 Estrutura da Planilha

| id_tipo | Texto Principal | Texto Secundário | Texto Title (opcional) | Texto Meta Description (opcional) |
|---------|----------------|------------------|------------------------|------------------------------------|
| 79      | Conteúdo HTML  | Conteúdo HTML    | Título opcional        | Meta description opcional         |
| 81      | Conteúdo HTML  | Conteúdo HTML    | ...                    | ...                                |

---

## 🗄️ Estrutura das Tabelas no Banco

### **Tabela 1 – `PUB_TIPOS_TEXTOS`**
| Coluna         | Origem na planilha | Observação |
|----------------|-------------------|------------|
| idTipo         | id_tipo           | Identificador único |
| TextoPrimario  | Texto Principal   | Texto HTML |
| TextoSecundario| Texto Secundário  | Texto HTML |
| Ativo          | Valor fixo = 1    | Sempre ativo |
| IdConteudo     | NULL              | Sem dados |
| Header         | NULL              | Sem dados |

### **Tabela 2 – `PUB_TIPOS_TEXTOS_TITULOS`**
| Coluna               | Origem | Observação |
|----------------------|--------|------------|
| idTipo               | id_tipo| Identificador único |
| TextoTitle           | Texto Title (se existir) | Pode ser preenchido futuramente |
| TextoMetaDescription | Texto Meta Description (se existir) | Pode ser preenchido futuramente |
| Ativo                | 1      | Sempre ativo |
| IdConteudo           | NULL   | Sem dados |

---

## ⚙️ Como Funciona

### **1️⃣ Leitura da Planilha**
Utiliza `pandas.read_excel()` para carregar os dados da aba `"Planilha1"`.

### **2️⃣ Modelagem dos Dados**
Cria dois DataFrames (`df_tipos_textos` e `df_tipos_titulos`) com as colunas no formato exato das tabelas.

### **3️⃣ Conexão ao Banco**
- **TESTE** → SQLite em memória (`sqlite3.connect(":memory:")`).
- **PRODUÇÃO** → SQL Server (`pyodbc.connect(...)`).

### **4️⃣ Inserção dos Dados**
- **TESTE** → Inserção simples (`INSERT`).
- **PRODUÇÃO** → UPSERT com `MERGE` (atualiza se existir, insere se não existir).

### **5️⃣ Validação**
No modo TESTE, executa consultas `SELECT` para verificar se os dados foram gravados.

### **6️⃣ Registro em Log**
Todos os eventos são gravados no arquivo `importacao.log`:
- Quantidade de registros processados.
- Erros de inserção.
- Conclusão.

---

## 🚀 Como Usar

1. Instale as dependências:
```bash
pip install pandas openpyxl pyodbc
```

2. Configure o arquivo Python:
```python
MODO = "TESTE"  # ou "PRODUCAO"
```

3. No modo produção, configure a conexão com o SQL Server:
```python
conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=SEU_SERVIDOR;'
    'DATABASE=SEU_DATABASE;'
    'UID=SEU_USUARIO;'
    'PWD=SUA_SENHA;'
)
```

4. Execute o script:
```bash
python AutomacaoBanco.py
```

5. Confira o log no arquivo `importacao.log`.

---


```bash
No SQL SERVER:

   1- Checagem rápida pra ver se as tabelas existem.

      SELECT TOP 1 * FROM PMP.dbo.PUB_TIPOS_TEXTOS;
      SELECT TOP 1 * FROM PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS;

      -- Mapeamento para derivar id_tipo (se necessário)
      SELECT TOP 5 * FROM PMP.dbo.PROCESSADO_BUSCA_TIPOS;

      -- Mapa idTipo -> IdConteudo (para seed)
      SELECT TOP 5 * FROM PMP.dbo.TEMATICOS_CONTEUDO_ITEM;

   2- Update Sem o SEED:
"""
O que acontece:

O script filtra os id_tipo da planilha que já existem em PMP.dbo.PUB_TIPOS_TEXTOS.

Ele atualiza:

TextoPrimario, TextoSecundario, Ativo=1 em PUB_TIPOS_TEXTOS.

(se vierem) TextoTitle, TextoMetaDescription, Ativo=1 em PUB_TIPOS_TEXTOS_TITULOS.

Para id_tipo que não existem no PMP, nada é atualizado (rowcount=0).

Se a proporção de id_tipo inexistentes passar do limite (--abort-if-missing-ratio, default 35%), ele aborta para evitar “rodada fantasma”.
```