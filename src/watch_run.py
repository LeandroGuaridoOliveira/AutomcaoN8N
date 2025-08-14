# === DEPENDÊNCIAS ===
# pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

import os, io, time, json, subprocess, tempfile, sys, signal, re
from typing import Dict, List

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ==================== CONFIG ====================
# Pasta onde o n8n deposita os .xlsx finais do workflow
FOLDER_ID = "1Ts65yg_usUhsw3jQlNs1r3t2omiYgmFR"

# OAuth: arquivos gerados/necessários
CREDENTIALS_FILE = "credentials.json"     # OAuth client ID (Desktop)
TOKEN_FILE = "token.json"                 # será criado/atualizado automaticamente
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Persistência de itens já processados (id → info)
PROCESSED_FILE = "processados.json"

# Script de automação e Python em uso
AUTOMACAO_SCRIPT = "AutomacaoBanco.py"
PYTHON_EXE = sys.executable

# Frequência de checagem (segundos)
CHECK_EVERY_SEC = 30

# Travas padrão de segurança 
BASE_AUTOMACAO_FLAGS: List[str] = [
    "--auto-seed",                 # cria linhas base para IDs ausentes
    "--pick-idconteudo", "min",
    "--map-table", "TEMATICOS_CONTEUDO_ITEM",
    "--tipo-col", "IDTIPO",
    "--conteudo-col", "ID",
    "--default-idconteudo", "1", 
    "--max-seed", "15",
    "--abort-if-missing-ratio", "1.0",
]

# ==================== LOG/UTIL ====================
def log(msg: str):
    print(msg, flush=True)

def load_processed() -> Dict[str, Dict]:
    if os.path.exists(PROCESSED_FILE):
        try:
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_processed(data: Dict[str, Dict]):
    tmp = PROCESSED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROCESSED_FILE)

# --- Sanitização de nome de arquivo (remove \n, \r, tabs, caracteres proibidos no Windows, etc.)
_WIN_FORBIDDEN = r'<>:"/\\|?*'
_CTRL = "".join(map(chr, range(0,32)))  # caracteres de controle 0-31
_SANITIZE_PATTERN = re.compile(f"[{re.escape(_WIN_FORBIDDEN + _CTRL)}]")

def sanitize_filename(name: str, default_stub: str = "arquivo.xlsx") -> str:
    # remove quebras/abas e espaços extras
    clean = name.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    clean = _SANITIZE_PATTERN.sub("_", clean)     # troca proibidos por _
    clean = re.sub(r"\s+", " ", clean)            # colapsa múltiplos espaços
    if not clean:
        clean = default_stub
    # garante extensão .xlsx
    if not clean.lower().endswith(".xlsx"):
        clean += ".xlsx"
    return clean

# ==================== DRIVE ====================
def _build_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def drive_service():
    svc = _build_service()
    try:
        about = svc.about().get(fields="user(emailAddress)").execute()
        log(f"[Drive] Autenticado como: {about.get('user',{}).get('emailAddress')}")
    except Exception as e:
        log(f"[Drive] Não foi possível obter e-mail do usuário: {e}")
    log(f"[Drive] Pasta alvo: {FOLDER_ID}")
    return svc

def get_most_recent_xlsx(service):
    """
    Retorna apenas o .xlsx mais recente da pasta (createdTime desc, top 1).
    """
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    q = f"'{FOLDER_ID}' in parents and mimeType='{mime_xlsx}' and trashed=false"
    fields = "files(id, name, mimeType, createdTime, modifiedTime, md5Checksum, parents)"

    res = service.files().list(
        q=q,
        fields=fields,
        pageSize=1,                         # pega só 1
        orderBy="createdTime desc",         # o mais novo primeiro
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        corpora="allDrives",
    ).execute()

    files = res.get("files", [])
    if files:
        f = files[0]
        log(f"[Drive] Mais recente: {f.get('name')} \n  ct={f.get('createdTime')} mt={f.get('modifiedTime')}")
        return f
    else:
        log("[Drive] Nenhum .xlsx na pasta no momento.")
        return None

def download_xlsx(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

# ==================== AUTOMACAO ====================
def build_flags_with_sheet(sheet_name: str) -> List[str]:
    flags = list(BASE_AUTOMACAO_FLAGS)
    # passa o nome da aba derivado do nome do arquivo
    flags.extend(["--sheet", sheet_name])
    # DRY-RUN via env var WATCH_DRY_RUN=1
    if os.environ.get("WATCH_DRY_RUN", "").strip() in ("1", "true", "True"):
        flags.append("--dry-run")
    return flags

def run_automacao(excel_path):
    # Nome fixo da aba dentro do arquivo Excel
    sheet_name = "Sheet"
    flags = list(BASE_AUTOMACAO_FLAGS)
    flags.extend(["--sheet", sheet_name])
    if os.environ.get("WATCH_DRY_RUN", "").strip() in ("1", "true", "True"):
        flags.append("--dry-run")

    cmd = [PYTHON_EXE, AUTOMACAO_SCRIPT, excel_path] + flags
    log(">> Exec: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    log(">> STDOUT:\n" + r.stdout)
    if r.stderr.strip():
        log(">> STDERR:\n" + r.stderr)
    if r.returncode != 0:
        raise RuntimeError(f"AutomacaoBanco.py falhou (code={r.returncode})")

def should_process(prev_info: Dict, current_info: Dict) -> bool:
    # Processa se for novo ou se o conteúdo mudou (md5); fallback em modifiedTime
    if not prev_info:
        return True
    prev_md5 = prev_info.get("md5Checksum")
    cur_md5 = current_info.get("md5Checksum")
    if cur_md5 and prev_md5 and cur_md5 != prev_md5:
        return True
    if not cur_md5:
        return current_info.get("modifiedTime") != prev_info.get("modifiedTime")
    return False

# ==================== MAIN LOOP ====================
_should_stop = False
def _graceful_exit(signum, frame):
    global _should_stop
    _should_stop = True
    log("Sinal recebido. Encerrando watcher...")

def main():
    signal.signal(signal.SIGINT, _graceful_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _graceful_exit)

    processed = load_processed()
    svc = drive_service()
    log("Watcher iniciado. Aguardando último .xlsx...")

    while not _should_stop:
        try:
            f = get_most_recent_xlsx(svc)
            if f:
                fid   = f["id"]
                fname = f["name"]
                safe_name = sanitize_filename(fname)
                if safe_name != fname:
                    log(f"[Watcher] Nome sanitizado: '{fname}' -> '{safe_name}'")

                cur_info = {
                    "name": safe_name,
                    "createdTime": f.get("createdTime"),
                    "modifiedTime": f.get("modifiedTime"),
                    "md5Checksum": f.get("md5Checksum"),
                }
                prev_info = processed.get(fid)

                if should_process(prev_info, cur_info):
                    log(f"[Watcher] Processando: {safe_name} ({fid})")
                    with tempfile.TemporaryDirectory() as tmpdir:
                        local_path = os.path.join(tmpdir, safe_name)
                        download_xlsx(svc, fid, local_path)
                        run_automacao(local_path)

                    processed[fid] = cur_info
                    save_processed(processed)
                    log(f"[Watcher] Concluído para: {safe_name}")
                # else: já processado e sem mudança

        except Exception as e:
            log(f"[ERRO] {e}")

        # Espera até a próxima checagem
        for _ in range(CHECK_EVERY_SEC):
            if _should_stop:
                break
            time.sleep(1)

    log("Watcher finalizado.")

if __name__ == "__main__":
    main()
