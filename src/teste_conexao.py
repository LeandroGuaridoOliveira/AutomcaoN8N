# test_conexao.py
import pyodbc, sys

SERVER   = r"10.1.96.71" 
DATABASE = "Querys"                
TRUSTED  = True                    # True=Windows/AD
USERNAME = "USUARIO"               # preencher caso TRUSTED=False
PASSWORD = "SENHA"                 # preencher caso TRUSTED=False

DEST_DATABASE = "PMP"              # se conectar no Querys e quer testar leitura no PMP

def main():
    if TRUSTED:
        cs = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};DATABASE={DATABASE};"
            "Trusted_Connection=yes;TrustServerCertificate=yes;"
        )
    else:
        cs = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};DATABASE={DATABASE};"
            f"UID={USERNAME};PWD={PASSWORD};TrustServerCertificate=yes;"
        )

    print(f"Conectando em SERVER={SERVER} DB={DATABASE} (trusted={TRUSTED})…")
    with pyodbc.connect(cs, timeout=10) as conn:
        with conn.cursor() as cur:
            # teste básico
            cur.execute("SELECT 1")
            print("OK: SELECT 1 executou.")

            # teste de leitura no banco de destino (se conectado no Querys)
            if DEST_DATABASE:
                cur.execute(f"SELECT TOP (1) name FROM [{DEST_DATABASE}].sys.tables")
                row = cur.fetchone()
                print(f"OK: leu do [{DEST_DATABASE}].sys.tables →", row[0] if row else "(sem linhas)")
    print("Conexão e leitura OK.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FALHA:", e)
        sys.exit(1)
