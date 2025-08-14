import subprocess
from pydrive2.auth import ServiceAccountCredentials
from pydrive2.drive import GoogleDrive

# === CONFIGURAÇÕES ===
FOLDER_ID = "1Ts65yg_usUhsw3jQlNs1r3t2omiYgmFR"
LOCAL_XLSX = r"C:\Users\leandro.oliveira\Downloads\AutomacaoBanco\AutomacaoBanco-main\imports\planilha_final.xlsx"  
AUTOMACAO_PATH = r"C:\Users\leandro.oliveira\Downloads\AutomacaoBanco\AutomacaoBanco-main\Testes\AutomacaoBanco.py"  # caminho do AutomacaoBanco.py
ARGS = [
    "--sheet", "Planilha1",
    "--auto-seed", "--max-seed", "200", "--pick-idconteudo", "min",
    "--map-table", "TEMATICOS_CONTEUDO_ITEM",
    "--tipo-col", "IDTIPO", "--conteudo-col", "ID",
    "--default-idconteudo", "1"
]

# === LOGIN COM SERVICE ACCOUNT ===
credentials = ServiceAccountCredentials.from_json_keyfile_name(
    "service_account.json",  # seu arquivo JSON da Service Account
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = GoogleDrive(credentials)

# === BUSCAR O ARQUIVO MAIS RECENTE ===
file_list = drive.ListFile({
    'q': f"'{FOLDER_ID}' in parents and trashed=false and mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",
    'orderBy': 'modifiedDate desc'
}).GetList()

if not file_list:
    print("Nenhum XLSX encontrado na pasta.")
    exit(1)

latest = file_list[0]
print(f"Baixando: {latest['title']} ({latest['id']})")
latest.GetContentFile(LOCAL_XLSX)

# === EXECUTAR O IMPORTADOR ===
cmd = ["python", AUTOMACAO_PATH, LOCAL_XLSX] + ARGS
print("Executando:", " ".join(cmd))
subprocess.run(cmd, check=True)
print("Processo concluído com sucesso!")
