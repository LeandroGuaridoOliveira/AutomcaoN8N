📄 Automação de Importação de Planilhas para SQL Server com Watcher no Google Drive
🎯 Objetivo

Automatizar o processo de:

Receber uma planilha .xlsx gerada pelo fluxo do N8N (já com textos processados por IA).

Detectar automaticamente quando o arquivo for salvo no Google Drive.

Executar o script AutomacaoBanco.py para inserir/atualizar os dados no SQL Server.

Registrar logs e organizar arquivos processados.

🛠️ Fluxo Geral da Solução
1. Entrada da planilha

O N8N gera a planilha final (.xlsx) com os textos.

A planilha é enviada automaticamente para uma pasta específica do Google Drive.

2. Watcher (watch_run.py)

Fica monitorando a pasta do Drive usando a API do Google.

Quando detecta novo arquivo ou atualização:

Baixa o arquivo para um diretório temporário.

Executa o AutomacaoBanco.py com o arquivo baixado.

Registra no processados.json que o arquivo foi processado (para evitar repetição).

Move o arquivo para a pasta "Processados" ou "Falha" no Drive (opcional).

3. Script AutomacaoBanco.py

Lê a planilha.

Modela os dados para as tabelas:

PUB_TIPOS_TEXTOS

PUB_TIPOS_TEXTOS_TITULOS

Atualiza os registros existentes e, se necessário, cria novas linhas com seed automático para id_tipo inexistentes.

Registra logs detalhados.

📂 Estrutura Esperada da Planilha
id_tipo	Texto Principal	Texto Secundário	Texto Title	Texto Meta Description
79	HTML	HTML	Título	Meta
81	HTML	HTML	...	...
⚙️ Como Configurar
1. Pré-requisitos

Python 3.10 ou superior

Conta do Google com acesso à pasta do Drive

Dependências instaladas:

pip install pandas openpyxl pyodbc google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2

2. Configuração do Google API

No Google Cloud Console:

Criar um projeto.

Ativar a Google Drive API.

Criar credenciais OAuth Client ID do tipo "Desktop App".

Baixar o arquivo credentials.json e colocar na mesma pasta do watch_run.py.

Na primeira execução:

O script abrirá o navegador pedindo login.

Escolha a conta correta e permita o acesso.

Será criado o arquivo token.json para uso futuro (não precisa logar de novo).

3. Configuração do Watcher

No watch_run.py:

FOLDER_ID = "ID_DA_PASTA_NO_GOOGLE_DRIVE"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
CHECK_EVERY_SEC = 30  # intervalo de checagem em segundos

4. Configuração do AutomacaoBanco.py

Ajustar MODO para "PRODUCAO" ou "TESTE".

Configurar a string de conexão do SQL Server no modo produção:

conn = pyodbc.connect(
    'DRIVER={ODBC Driver 17 for SQL Server};'
    'SERVER=SEU_SERVIDOR;'
    'DATABASE=SEU_DATABASE;'
    'UID=SEU_USUARIO;'
    'PWD=SUA_SENHA;'
)

🚀 Como Usar
1. Rodar o Watcher

No terminal, na pasta do script:

python -u watch_run.py


O -u garante saída de log em tempo real.

O Watcher ficará ativo monitorando a pasta do Google Drive.

Quando detectar novo arquivo .xlsx, ele executa automaticamente o AutomacaoBanco.py.

2. Verificar no Banco

Antes de rodar, veja os id_tipo já existentes:

SELECT idTipo, TextoPrimario FROM PMP.dbo.PUB_TIPOS_TEXTOS;
SELECT idTipo, TextoTitle FROM PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS;


Após rodar, verifique novamente para confirmar a atualização:

SELECT idTipo, TextoPrimario, TextoSecundario, IdConteudo FROM PMP.dbo.PUB_TIPOS_TEXTOS;
SELECT idTipo, TextoTitle, TextoMetaDescription, IdConteudo FROM PMP.dbo.PUB_TIPOS_TEXTOS_TITULOS;

3. Organização de Arquivos no Drive

Processados: arquivos que foram importados com sucesso.

Falha: arquivos que geraram erro na importação.

Essa movimentação é feita pelo próprio watch_run.py (se as pastas forem configuradas).

📌 Boas Práticas

Sempre testar com --dry-run no AutomacaoBanco.py antes de atualizar o banco real.

Garantir que a planilha final gerada pelo N8N esteja no formato correto.

Manter backup da pasta de Processados no Drive.

Atualizar credentials.json se mudar de conta do Google.
