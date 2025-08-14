# 📄 Automação: N8N + Google Drive + Watcher + SQL Server

## 🎯 Objetivo
- Gerar uma planilha **.xlsx** no N8N (após os agentes de IA), enviar ao **Google Drive** e
- Ter um **watcher** (script Python) que detecta o novo arquivo, baixa e executa o **AutomacaoBanco.py** para atualizar o **SQL Server**.
- Organizar arquivos em **/Processados** e **/Falha** e registrar logs.

---

## 🧭 Visão geral do fluxo
1) **N8N**: lê Sheets → passa por 2 agentes de IA → **Spreadsheet File** cria XLSX → **Google Drive (Upload)** envia para **/Entrada**.  
2) **Watcher (`watch_run.py`)**: monitora a pasta do Drive; quando acha um XLSX novo/atualizado:
   - Baixa para pasta temporária e **sanitiza o nome** (sem “:” e quebras de linha).
   - Executa `AutomacaoBanco.py` com os parâmetros definidos.
   - Se rodar OK → registra em `processados.json` e (opcional) **move no Drive para /Processados**.  
     Se falhar → (opcional) **move para /Falha**.
3) **AutomacaoBanco.py**: lê o XLSX e atualiza:
   - `PMP.dbo.PUB_TIPOS_TEXTOS` (TextoPrimario, TextoSecundario, Ativo=1)  
   - `PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS` (TextoTitle, TextoMetaDescription, Ativo=1)  
   - Se `--auto-seed`: cria linhas-base quando `idTipo` não existe (com mapeamento `IdConteudo`).

---

## 📦 Requisitos
- **Python 3.10+** (3.12 OK).
- Pacotes:
  ```bash
  pip install pandas openpyxl pyodbc google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2
  ```
- **ODBC Driver 17** for SQL Server (Windows).

---

## ⚙️ Configuração do Google (OAuth)
1. No **Google Cloud Console** → **APIs & Services** → **Library** → ative **Google Drive API** (e **Google Sheets API** se precisar).  
2. **Credentials** → **Create Credentials** → **OAuth client ID** → **Desktop app** → faça download do `credentials.json`.  
3. Coloque o `credentials.json` **na mesma pasta do `watch_run.py`**. Na primeira execução, abrirá o navegador, você loga e é criado o `token.json`.

> **Dica:** se trocar de conta, apague `token.json` e rode novamente para refazer o login.

---

## 🗂️ Pastas no Google Drive
Crie (ou defina) estas pastas e anote os **IDs** (parte após `folders/` na URL):
```
/Entrada
/Processados
/Falha
```
Compartilhe a pasta com a conta que você usará no OAuth (ou com a **Service Account**, se usar SA).
No `watch_run.py`, você pode definir via **variáveis de ambiente**:
```
DRIVE_FOLDER_ENTRADA_ID=<id>
DRIVE_FOLDER_PROCESSADOS_ID=<id>
DRIVE_FOLDER_FALHA_ID=<id>
```

---

## 🧩 N8N – configuração mínima
- **Spreadsheet File** → *Create spreadsheet*  
  - **Binary Property:** `data`  
  - **File Format:** `XLSX`  
  - **Sheet Name:** `Planilha1`  
  - **File Name (Expression):**
    ```
    planilha_final_{{ 
      (d => 
        String(d.getDate()).padStart(2,'0') + '_' +
        String(d.getMonth() + 1).padStart(2,'0') + '_' +
        d.getFullYear() + '_' +
        String(d.getHours()).padStart(2,'0') + '_' +
        String(d.getMinutes()).padStart(2,'0') + '_' +
        String(d.getSeconds()).padStart(2,'0')
      )(new Date()) 
    }}.xlsx
    ```
- **Google Drive → Upload**  
  - **Use Binary Data:** `true`  
  - **Binary Property:** `data`  
  - **Parent Folder:** `/Entrada`  
  - (**Opcional**) File Name com a **mesma expression** acima (ou deixe o do Spreadsheet File).

> **Importante:** ative o **modo Expression (fx)** no campo *File Name*; se aparecer literalmente com `{{...}}`, você está em modo texto.

---

## 🐍 Watcher (`watch_run.py`)
### Parâmetros principais (no código ou por env)
```python
FOLDER_ID = "ID_DA_PASTA_ENTRADA"     # se a listagem usa uma pasta única
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
CHECK_EVERY_SEC = 30
```
**Movimentação opcional** (por env):
```
DRIVE_FOLDER_ENTRADA_ID     = <id>
DRIVE_FOLDER_PROCESSADOS_ID = <id>
DRIVE_FOLDER_FALHA_ID       = <id>
```

### Execução
```bash
python -u watch_run.py
```
- `-u` = logs sem buffer (aparecem na hora).  
- Na 1ª vez, abre o navegador para login do Google.  
- Log detalhado também é salvo em **`watcher_debug.log`** (injetado pelo “hardmode” de debug).

### Como funciona internamente
1. Autentica no Drive (usa `credentials.json` + `token.json`).  
2. Lista arquivos .xlsx na pasta definida.  
3. Para cada arquivo, monta uma “assinatura” (`name`, `modifiedTime`, `md5Checksum`) e compara com `processados.json`.  
4. Se for novo/atualizado:
   - Sanitiza o nome (remove caracteres inválidos no Windows, como `:` e quebras de linha).
   - Baixa para um `TemporaryDirectory`.
   - Executa `AutomacaoBanco.py <arquivo baixado>`
   - Se **sucesso**: grava em `processados.json` e (se configurado) move para **/Processados**.  
     Se **falha**: (se configurado) move para **/Falha**.
   
> O watcher **não reprocessa** o mesmo `fileId` com o mesmo `md5Checksum`.

---

## 🏦 AutomacaoBanco.py – resumo de uso
### DRY‑RUN (sem gravar; mostra seeds)
```bash
python AutomacaoBanco.py "C:	mp\planilha.xlsx" --auto-seed --dry-run --max-seed 100 --pick-idconteudo min --map-table TEMATICOS_CONTEUDO_ITEM --tipo-col IDTIPO --conteudo-col ID --default-idconteudo 1
```
### Produção (aplica UPDATEs e SEEDs)
```bash
python AutomacaoBanco.py "C:	mp\planilha.xlsx" --auto-seed --max-seed 100 --pick-idconteudo min --map-table TEMATICOS_CONTEUDO_ITEM --tipo-col IDTIPO --conteudo-col ID --default-idconteudo 1
```
- Preenche `TextoPrimario` / `TextoSecundario` / `Ativo=1` e SEO (quando presentes).  
- Garante `id_tipo` válido (direto da planilha ou derivado de `id_cat/id_grupo` se implementado).  
- Cria base quando o `idTipo` não existe (seed).

---

## 🔍 Validação no SQL (antes/depois)
```sql
-- Antes (exemplo com IDs da planilha)
SELECT idTipo, TextoPrimario FROM PMP.dbo.PUB_TIPOS_TEXTOS WHERE idTipo IN (101,102,103);
SELECT idTipo, TextoTitle FROM PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS WHERE idTipo IN (101,102,103);

-- Depois
SELECT idTipo, TextoPrimario, TextoSecundario, Ativo
FROM PMP.dbo.PUB_TIPOS_TEXTOS WHERE idTipo IN (101,102,103);

SELECT idTipo, TextoTitle, TextoMetaDescription, Ativo
FROM PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS WHERE idTipo IN (101,102,103);
```

---

## 🧯 Troubleshooting
- **Nada aparece no terminal / fecha sozinho** → rode com:
  ```bash
  python -u -X dev watch_run.py
  ```
  e consulte `watcher_debug.log` na mesma pasta.  
- **Erro `Credentials.refresh() missing 'request'`** → importe e use:
  ```python
  from google.auth.transport.requests import Request
  creds.refresh(Request())
  ```
- **`FileNotFoundError: credentials.json`** → coloque o `credentials.json` na pasta do script (ou ajuste o caminho).  
- **`Invalid argument` ao salvar** → o nome tem `:`/quebras de linha. Use a sanitização (o watcher já trata).  
- **Token inválido/corrompido** → apague `token.json` e rode de novo para refazer o login.  
- **Horário errado no nome** → use expressão de data **local** no N8N (sem `toISOString()`) como no exemplo acima.

---

## 🧭 Dicas de operação
- Nome de arquivo **com data**: `planilha_final_DD_MM_YYYY_HH_MM_SS.xlsx` (já configurado no N8N).  
- Mantenha o watcher rodando em um **terminal dedicado** ou agendado (Windows Task Scheduler).  
- Faça **backup** da pasta **/Processados** periodicamente.

---

## ✅ Conclusão
Com este fluxo, você consegue:
- Automatizar de ponta a ponta (N8N → Drive → Watcher → SQL).
- Garantir consistência com seed controlado e logs.
- Organizar a pasta do Drive com **Processados** e **Falha**.
