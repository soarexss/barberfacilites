from fastapi import FastAPI, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import json
from datetime import datetime

app = FastAPI()

# Servir arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Página inicial
@app.get("/")
def home():
    return FileResponse("static/main.html")

# Ler clientes do JSON
def ler_clientes():
    try:
        with open("dados.json", "r") as f:
            return json.load(f)
    except:
        return []

# Salvar clientes no JSON
def salvar_clientes(clientes):
    with open("dados.json", "w") as f:
        json.dump(clientes, f, indent=4)

# Adicionar cliente
@app.post("/clientes")
def add_cliente(nome: str = Form(...), telefone: str = Form(...)):
    clientes = ler_clientes()
    clientes.append({"nome": nome, "telefone": telefone, "agendamentos":[]})
    salvar_clientes(clientes)
    return JSONResponse({"msg": f"Cliente {nome} adicionado!"})

# Adicionar agendamento
@app.post("/agendamentos")
def add_agendamento(
    cliente_nome: str = Form(...),
    data: str = Form(...),
    hora: str = Form(...),
    barbeiro: str = Form(...)
):
    clientes = ler_clientes()
    encontrado = False

    for c in clientes:
        if c["nome"].lower() == cliente_nome.lower():
            if "agendamentos" not in c:
                c["agendamentos"] = []
            c["agendamentos"].append({"data": data, "hora": hora, "barbeiro": barbeiro})
            encontrado = True
            break

    if not encontrado:
        return JSONResponse({"msg": "Cliente não encontrado!"}, status_code=404)

    salvar_clientes(clientes)
    return JSONResponse({"msg": f"Agendamento para {cliente_nome} adicionado!"})

# Listar agendamentos futuros
@app.get("/agendamentos")
def listar_agendamentos_futuros():
    clientes = ler_clientes()
    hoje = datetime.now().date()
    resultados = []

    for c in clientes:
        for ag in c.get("agendamentos", []):
            try:
                data_ag = datetime.strptime(ag["data"], "%d/%m/%Y").date()
                if data_ag >= hoje:
                    resultados.append({
                        "cliente": c["nome"],
                        "telefone": c["telefone"],
                        "data": ag["data"],
                        "hora": ag["hora"],
                        "barbeiro": ag["barbeiro"]
                    })
            except:
                continue

    return resultados
