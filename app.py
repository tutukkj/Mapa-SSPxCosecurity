import pandas as pd
import numpy as np
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.express as px
import plotly.graph_objects as go
import json
import os
from flask import Flask, render_template

# ==============================
# 1. SERVIDOR FLASK
# ==============================
# Instância do Flask que será usada para o Gunicorn
server = Flask(__name__)

@server.route('/')
def index():
    # Renderiza o arquivo HTML (se houver, caso contrário, retorne uma mensagem simples)
    return '<h1>Dashboard Ocorrências x Eventos</h1><p>Vá para /dashboard para ver a aplicação Dash.</p>'

# ==============================
# 2. DASH
# ==============================
# A instância do Dash é criada a partir do servidor Flask existente.
app = Dash(__name__, server=server, url_base_pathname='/dashboard/')

# ==============================
# 1) CARREGAMENTO E PRÉ-PROCESSAMENTO
# ==============================
# Carrega e processa os dados criminais
# Usa variáveis de ambiente para o caminho do arquivo, se disponível
CRIMINAL_FILE = os.getenv("CRIMINAL_FILE", "SPDadosCriminais_SAO_PAULO_limpo.xlsx")

try:
    df_criminal = pd.read_excel(CRIMINAL_FILE, engine='openpyxl')
    print(f"Planilha '{CRIMINAL_FILE}' carregada com sucesso.")
except FileNotFoundError:
    print(f"Erro: O arquivo '{CRIMINAL_FILE}' não foi encontrado.")
    # Em produção, um erro Fatal é mais adequado que um raise.
    # Em Railway, o build falharia se os arquivos não estivessem lá.
    raise
except Exception as e:
    print(f"Erro ao carregar o arquivo '{CRIMINAL_FILE}': {e}")
    raise

# Padroniza as colunas e tipos de dados
df_criminal.columns = df_criminal.columns.str.lower().str.replace(' ', '_', regex=False)
COLUNA_LATITUDE_CRIM = 'latitude'
COLUNA_LONGITUDE_CRIM = 'longitude'
COLUNA_BAIRRO_CRIM = 'bairro'
COLUNA_NATUREZA_CRIM = 'natureza_apurada'
COLUNA_DATA_CRIM = 'data_ocorrencia_bo'
COLUNA_HORA_CRIM = 'hora_ocorrencia_bo'

# Conversão da coluna de data e criação das colunas de ano, mes e cidade
if COLUNA_DATA_CRIM not in df_criminal.columns:
    COLUNA_DATA_CRIM = 'dataocorrencia' # fallback para o nome da coluna no outro código
if COLUNA_DATA_CRIM not in df_criminal.columns:
    raise ValueError(f"A coluna '{COLUNA_DATA_CRIM}' não foi encontrada.")

df_criminal[COLUNA_DATA_CRIM] = pd.to_datetime(df_criminal[COLUNA_DATA_CRIM], errors='coerce')
df_criminal = df_criminal.dropna(subset=[COLUNA_DATA_CRIM])
df_criminal['ano'] = df_criminal[COLUNA_DATA_CRIM].dt.year.astype('Int64')
df_criminal['mes'] = df_criminal[COLUNA_DATA_CRIM].dt.month
df_criminal['cidade'] = 'São Paulo' # Adiciona a cidade para permitir o filtro unificado

# --- ADIÇÃO PARA CONVERTER O NÚMERO DO MÊS PARA O NOME DO MÊS ---
# Cria um dicionário para mapear números para nomes de meses
nomes_meses = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}
# Aplica o mapeamento à coluna 'mes'
df_criminal['mes_nome'] = df_criminal['mes'].map(nomes_meses)

# Parser robusto de hora (0-23) para dados criminais
def extrair_hora_robusta(serie):
    if serie is None or serie.name is None:
        return pd.Series(0, index=df_criminal.index, dtype='int64')
    s = serie.copy()
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.hour.fillna(0).astype(int)
    if pd.api.types.is_timedelta64_dtype(s):
        return s.dt.components.hours.fillna(0).astype(int)
    s = s.astype('string').str.strip()
    com_dp = s.str.contains(":", na=False)
    horas = pd.Series(pd.NA, index=s.index, dtype="Int64")
    if com_dp.any():
        try:
            parsed = pd.to_datetime("2000-01-01 " + s[com_dp], errors="coerce")
            horas.loc[com_dp] = parsed.dt.hour.astype("Int64")
        except:
            pass
    sem_dp = ~com_dp
    if sem_dp.any():
        digits = s[sem_dp].str.replace(r"\D", "", regex=True)
        lens = digits.str.len()
        mask6 = lens >= 6
        horas.loc[sem_dp & mask6] = pd.to_numeric(digits[mask6].str.slice(0, 2), errors="coerce").astype("Int64")
        mask4_5 = (lens.between(3, 5)) & ~mask6
        horas.loc[sem_dp & mask4_5] = pd.to_numeric(digits[mask4_5].str.slice(0, 2), errors="coerce").astype("Int64")
        mask_le2 = (lens <= 2)
        horas.loc[sem_dp & mask_le2] = pd.to_numeric(digits[mask_le2], errors="coerce").astype("Int64")
    horas = horas.where((horas >= 0) & (horas <= 23))
    return horas.fillna(0).astype(int)

df_criminal['hora'] = extrair_hora_robusta(df_criminal.get(COLUNA_HORA_CRIM))

# Regiões para dados criminais
zonas_sao_paulo = {
    'Zona Norte': [
        'Água Fria', 'Brasilândia', 'Casa Verde', 'Freguesia do Ó', 'Jaçanã',
        'Jardim Japão', 'Jardim Julieta', 'Jardim Leme', 'Jardim Leonor Mendes de Barros',
        'Jardim Mabel', 'Jardim Recanto Verde', 'Lauzane Paulista', 'Limão', 'Mandaqui',
        'Mata Fria', 'Parada Inglesa', 'Parque Edu Chaves', 'Parque Mandaqui',
        'Parque Novo Mundo', 'Parque Paineiras', 'Parque Peruche', 'Parque Rodrigues Alves',
        'Parque Palmas do Tremembé', 'Parque Vila Guilherme', 'Pari', 'Perus',
        'Piqueri', 'Residencial Sol Nascente', 'Santa Terezinha', 'Santana', 'Tucuruvi',
        'Vila Albertina', 'Vila Amália', 'Vila Bancária', 'Vila Brasilândia',
        'Vila Cachoeira', 'Vila Dionísia', 'Vila Ede', 'Vila Elisa', 'Vila Ester',
        'Vila Fenelon', 'Vila Formosa', 'Vila Guilherme', 'Vila Gustavo', 'Vila Mazzei',
        'Vila Medeiros', 'Vila Nilo', 'Vila Nova Cachoeirinha', 'Vila Nova Mazzei',
        'Vila Nova Parada', 'Vila Paiva', 'Vila Perus', 'Vila Pirituba',
        'Vila Sabrina', 'Vila Santa Teresinha', 'Vila Siqueira', 'Vila Souza',
        'Vila Vergueiro', 'Vila Vitória', 'Vila Zat'
    ],
    'Zona Sul': [
        'Chácara Flora', 'Chácara Santo Antônio', 'Cidade Dutra', 'Ibirapuera',
        'Ipiranga', 'Jabaquara', 'Jardim América', 'Jardim Ângela', 'Jardim Arpoador',
        'Jardim da Glória', 'Jardim das Oliveiras', 'Jardim das Rosas',
        'Jardim do Carmo', 'Jardim Maringá', 'Jardim Mirante', 'Jardim Monte Belo',
        'Jardim Monte Kemel', 'Jardim Monte Verde', 'Jardim Morais Prado',
        'Jardim Nardini', 'Jardim Nova Vitória I', 'Jardim Paris', 'Jardim Paulista',
        'Jardim Paulistano', 'Jardim Prudência', 'Jardim Santa Amélia',
        'Jardim Santa Cruz', 'Jardim Santa Helena', 'Jardim Santa Rita',
        'Jardim Santo Amaro', 'Jardim São João', 'Jardim São José',
        'Jardim São Luís', 'Jardim São Sebastião', 'Jardim São Vicente',
        'Jardim Soraia', 'Jardim Umuarama', 'Jardim Vaz de Lima', 'Jardim Vergueiro',
        'Jardins', 'Jurubatuba', 'Moema', 'Morumbi', 'Paraisópolis', 'Parelheiros',
        'Parque Alto do Rio Bonito', 'Parque Americano', 'Parque Arariba',
        'Parque das Fontes', 'Parque do Estado', 'Parque Fernanda', 'Parque Grajaú',
        'Parque Independência', 'Parque Novo Grajaú', 'Parque Novo Santo Amaro',
        'Parque Residencial Cocaia', 'Parque Santo Amaro', 'Parque Santo Antônio',
        'Parque São Paulo', 'Parque São Rafael', 'Parque Sevilha', 'Pedreira',
        'Santo Amaro', 'Sapopemba', 'Saúde', 'Socorro', 'Vila Americana',
        'Vila Andrade', 'Vila Arcádia', 'Vila Bandeirantes', 'Vila Brasilina',
        'Vila Campestre', 'Vila Campo Grande', 'Vila Caraguatá', 'Vila Clemência',
        'Vila Clementino', 'Vila das Mercês', 'Vila do Encontro', 'Vila Dom Pedro I',
        'Vila Fátima', 'Vila Gertrudes', 'Vila Guacuri', 'Vila Guarani',
        'Vila Gumercindo', 'Vila Inglesa', 'Vila Joaniza', 'Vila Mariana',
        'Vila Mascote', 'Vila Missionária', 'Vila Monumento', 'Vila Moraes',
        'Vila Olímpia', 'Vila Pedreira', 'Vila Prudente', 'Vila Remo',
        'Vila Santa Catarina', 'Vila Santa Cecília', 'Vila Santa Delphina',
        'Vila Santa Efigênia', 'Vila Santa Tereza', 'Vila São Francisco',
        'Vila São José', 'Vila São Pedro', 'Vila São Paulo', 'Vila Socorro',
        'Vila Sofia', 'Vila Suzana', 'Vila Vera', 'Vila do Sítio', 'Várzea de Baixo'
    ],
    'Zona Leste': [
        'Aricanduva', 'Artur Alvim', 'Belém', 'Cidade A. E. Carvalho', 'Cidade Líder',
        'Cidade Patriarca', 'Cidade São Mateus', 'Cidade Tiradentes', 'José Bonifácio',
        'Lajeado', 'Mooca', 'Parada Inglesa', 'Parque Artur Alvim', 'Parque do Carmo',
        'Parque do Estado', 'Parque Fontene', 'Parque Guainazes', 'Parque Maria',
        'Parque Monte Líbano', 'Parque Novo Mundo', 'Parque Savóia',
        'Parque São Lucas', 'Parque São Rafael', 'Penha', 'Ponte Rasa',
        'São Miguel Paulista', 'Tatuapé', 'Vila América', 'Vila Antonieta',
        'Vila Aricanduva', 'Vila Califórnia', 'Vila Carmosina', 'Vila Carrão',
        'Vila Cláudio', 'Vila Divina Pastora', 'Vila Ema', 'Vila Formosa',
        'Vila Guilherme', 'Vila Industrial', 'Vila Jaçanã', 'Vila Jacuí',
        'Vila Manchester', 'Vila Maria', 'Vila Marieta', 'Vila Marilena',
        'Vila Mascote', 'Vila Matilde', 'Vila Nhocuné', 'Vila Pimentel',
        'Vila Prudente', 'Vila Santa Inês', 'Vila Santa Teresinha',
        'Vila São Francisco', 'Vila São Mateus', 'Vila São Miguel',
        'Vila São Rafael', 'Vila Silvia', 'Vila Silveira', 'Vila Siqueira',
        'Vila Talarico', 'Vila Tolstoi', 'Vila Zelina'
    ],
    'Zona Oeste': [
        'Butantã', 'Jaguaré', 'Jaraguá', 'Lapa', 'Morumbi', 'Perdizes', 'Pinheiros',
        'Pirituba', 'Pompeia', 'Rio Pequeno', 'Vila Iolanda', 'Vila Ipojuca',
        'Vila Leopoldina', 'Vila Madalena', 'Vila Sônia'
    ],
    'Centro': [
        'Aclimação', 'Barra Funda', 'Bela Vista', 'Bom Retiro', 'Cambuci',
        'Campos Elíseos', 'Consolação', 'Higienópolis', 'Jardim Anália Franco',
        'Jardim da Glória', 'Jardim do Carmo', 'Jardim Europa', 'Jardim Paulista',
        'Liberdade', 'Luz', 'Pacaembu', 'Pari', 'Praça da Árvore', 'República',
        'Santa Cecília', 'Sé', 'Vila Buarque', 'Vila Monumento'
    ],
    'Outras Localidades': [
        'Jardim Vivan', 'Jardim Wilma Flor', 'Jardim Coimbra', 'Jardim Vle Virtudes',
        'Vila Baby', 'Vila Barreto', 'Vila Bozzini', 'Vila Brasilia',
        'Vila Chabilandia', 'Vila Chely', 'Vila Curuça Velha', 'Vila Feliz',
        'Vila Franquis', 'Vila Friburgo', 'Vila Fukuya', 'Vila Ger',
        'Vila Gertrudes', 'Vila Heliopolis', 'Vila Itaim', 'Vila Jacu',
        'Vila Jaguari', 'Vila Jaçanã', 'Vila João', 'Vila Jurema', 'Vila Lousada',
        'Vila Mairiporã', 'Vila Manuel', 'Vila Mariazinha', 'Vila Mariana',
        'Vila Mazzei', 'Vila Monte', 'Vila Morumbi', 'Vila Nelson', 'Vila Nova'
    ]
}
df_criminal['regiao'] = 'Outra Região'
for regiao, bairros in zonas_sao_paulo.items():
    df_criminal.loc[df_criminal[COLUNA_BAIRRO_CRIM].isin(bairros), 'regiao'] = regiao

# Carrega e processa os dados de eventos
# Usa variáveis de ambiente para os caminhos dos arquivos, se disponíveis
EVENTOS_FILE = os.getenv("EVENTOS_FILE", "eventos_estruturados.json")
LOCAIS_FILE = os.getenv("LOCAIS_FILE", "locais.json")

try:
    with open(EVENTOS_FILE, "r", encoding="utf-8") as f:
        eventos = json.load(f)
    with open(LOCAIS_FILE, "r", encoding="utf-8") as f:
        locais = json.load(f)
except FileNotFoundError as e:
    print(f"Erro: O arquivo {e.filename} não foi encontrado.")
    raise SystemExit(1)

df_eventos = pd.DataFrame(eventos)
df_locais = pd.DataFrame(locais)
df_eventos = pd.merge(
    df_eventos, df_locais,
    how="left",
    left_on="local_id",
    right_on="id",
    suffixes=("_evento", "_local")
)
df_eventos.rename(columns={
    "numero_local": "numero",
    "nome": "nome_local",
    "endereco": "endereco_local"
}, inplace=True)

# Limpeza e conversão de tipos de dados para eventos
df_eventos["latitude"] = pd.to_numeric(df_eventos["latitude"], errors="coerce")
df_eventos["longitude"] = pd.to_numeric(df_eventos["longitude"], errors="coerce")
df_eventos = df_eventos.dropna(subset=["latitude", "longitude"])
df_eventos['data_evento'] = pd.to_datetime(df_eventos['data_evento'], errors='coerce')
df_eventos = df_eventos.dropna(subset=['data_evento'])
df_eventos['ano'] = df_eventos['data_evento'].dt.year.astype('Int64')
df_eventos['mes'] = df_eventos['data_evento'].dt.month # Adiciona a coluna de mês
df_eventos['hora'] = df_eventos['data_evento'].dt.hour
for col in ['bairro', 'cidade', 'evento_nome']:
    if col in df_eventos.columns:
        df_eventos[col] = df_eventos[col].astype('string').str.strip().str.title()
        df_eventos[col] = df_eventos[col].replace({'': pd.NA})
        
# --- ADIÇÃO PARA CONVERTER O NÚMERO DO MÊS PARA O NOME DO MÊS EM EVENTOS ---
df_eventos['mes_nome'] = df_eventos['mes'].map(nomes_meses)


# Escala de cores personalizada para os mapas
escala_personalizada = [
    [0.0, "rgba(0, 255, 255, 0)"],
    [0.01, "rgb(255, 255, 153)"],
    [0.1, "rgb(255, 204, 102)"],
    [0.4, "rgb(255, 102, 0)"],
    [0.7, "rgb(204, 51, 0)"],
    [1.0, "rgb(178, 24, 43)"]
]

# Opções de filtro unificadas
bairros_unicos = sorted(list(set(df_criminal[COLUNA_BAIRRO_CRIM].dropna().astype(str).unique()).union(set(df_eventos['bairro'].dropna().astype(str).unique()))))
naturezas_unicas = sorted(df_criminal[COLUNA_NATUREZA_CRIM].dropna().unique())
regioes_unicas = sorted(df_criminal['regiao'].dropna().unique())
# Anos e Cidades agora são unificados
anos_unicos = sorted([int(a) for a in set(df_criminal['ano'].dropna().unique()).union(set(df_eventos['ano'].dropna().unique()))])
cidades_unicas = sorted(list(set(df_criminal['cidade'].dropna().astype(str).unique()).union(set(df_eventos['cidade'].dropna().astype(str).unique()))))
eventos_unicos = sorted(df_eventos['evento_nome'].dropna().unique())
horas_unicas = list(range(24))
# Usa os nomes dos meses agora
meses_unicos = [nomes_meses[i] for i in sorted(df_criminal['mes'].dropna().unique())]
meses_mapping = {nome: num for num, nome in nomes_meses.items()}

# ==============================
# 3) LAYOUT DASH (AJUSTADO)
# ==============================
# Estilo comum para os filtros
filter_style = {'fontSize': '14px', 'width': '200px'}

app.layout = html.Div(
    style={
        'fontFamily': 'Arial, sans-serif',
        'backgroundColor': '#f0f2f5',
        'padding': '20px'
    },
    children=[
        # Título principal
        html.H1("Dashboard Ocorrências x Eventos", style={
            'textAlign': 'center',
            'color': '#333',
            'marginBottom': '20px'
        }),

        # Contêiner de filtros unificado e horizontal
        html.Div(
            style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'justifyContent': 'center',
                'padding': '20px',
                'backgroundColor': '#fff',
                'borderRadius': '12px',
                'boxShadow': '0 4px 15px rgba(0,0,0,0.1)',
                'marginBottom': '30px',
                'gap': '15px'
            },
            children=[
                # Filtros para o dashboard de crimes
                html.Div(style=filter_style, children=[html.Label("Região:", style=filter_style), dcc.Dropdown(
                    id='filtro-regiao', 
                    options=[{'label': i, 'value': i} for i in regioes_unicas],
                    value=None, 
                    clearable=True, 
                    placeholder="Todas",
                    style={'fontSize': '14px'}
                )]),
                html.Div(style=filter_style, children=[html.Label("Natureza Apurada:", style=filter_style), dcc.Dropdown(
                    id='filtro-natureza', 
                    options=[{'label': i, 'value': i} for i in naturezas_unicas],
                    value=None, 
                    clearable=True, 
                    placeholder="Todas",
                    style={'fontSize': '14px'}
                )]),

                # Filtros comuns
                # Alterado para usar o nome do mês como label e o número como valor
                html.Div(style=filter_style, children=[html.Label("Mês:", style=filter_style), dcc.Dropdown(
                    id='filtro-mes', 
                    options=[{'label': i, 'value': meses_mapping[i]} for i in meses_unicos],
                    value=None, 
                    clearable=True, 
                    placeholder="Todos os Meses",
                    style={'fontSize': '14px'}
                )]),
                html.Div(style=filter_style, children=[html.Label("Cidade:", style=filter_style), dcc.Dropdown(
                    id='filtro-cidade', 
                    options=[{'label': c, 'value': c} for c in cidades_unicas],
                    value=None, 
                    clearable=True, 
                    placeholder="Todas",
                    style={'fontSize': '14px'}
                )]),
                html.Div(style=filter_style, children=[html.Label("Bairro:", style=filter_style), dcc.Dropdown(
                    id='filtro-bairro', 
                    options=[{'label': b, 'value': b} for b in bairros_unicos],
                    value=None, 
                    clearable=True, 
                    placeholder="Todos",
                    style={'fontSize': '14px'}
                )]),
                html.Div(style=filter_style, children=[html.Label("Hora:", style=filter_style), dcc.Dropdown(
                    id='filtro-hora', 
                    options=[{'label': f'{h:02d}:00', 'value': h} for h in horas_unicas],
                    value=None, 
                    clearable=True, 
                    placeholder="Todas as Horas",
                    style={'fontSize': '14px'}
                )]),

                # Filtro para o dashboard de eventos
                html.Div(style=filter_style, children=[html.Label("Evento:", style=filter_style), dcc.Dropdown(
                    id='filtro-evento', 
                    options=[{'label': e, 'value': e} for e in eventos_unicos],
                    value=None, 
                    clearable=True, 
                    placeholder="Todos", 
                    style={'zIndex': 101, 'fontSize': '14px'}
                )]),
            ]
        ),

        # Contêiner principal para as duas colunas
        html.Div(
            style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'gap': '20px',
                'justifyContent': 'center',
            },
            children=[
                # Primeira Coluna (Mapa e Gráfico de Ocorrências Criminais)
                html.Div(
                    style={
                        'flex': '0 0 48%',
                        'display': 'flex',
                        'flexDirection': 'column',
                        'gap': '20px'
                    },
                    children=[
                        # Mapa de Ocorrências Criminais
                        html.Div(
                            style={
                                'padding': '15px',
                                'backgroundColor': '#fff',
                                'borderRadius': '12px',
                                'boxShadow': '0 4px 15px rgba(0,0,0,0.1)',
                                'height': 'auto'
                            },
                            children=[
                                html.H3("Mapa de Ocorrências Criminais (SSP)", style={'textAlign': 'center', 'color': '#d9534f', 'margin': '0'}),
                                html.Div(
                                    style={
                                        'display': 'flex', 'justifyContent': 'center', 'gap': '15px', 'margin': '20px 0'
                                    },
                                    children=[
                                        html.Div(id='card-natureza', className='metric-card', style={
                                            'padding': '20px', 'backgroundColor': '#fff',
                                            'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center', 'flex': '1'
                                        }),
                                        html.Div(id='card-ocorrencias', className='metric-card', style={
                                            'padding': '20px', 'backgroundColor': '#fff',
                                            'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center', 'flex': '1'
                                        })
                                    ]
                                ),
                                dcc.Graph(
                                    id='mapa-calor-criminal',
                                    config={'scrollZoom': True},
                                    style={'height': '60vh', 'width': '100%'}
                                )
                            ]
                        ),
                        
                        # Gráfico de Ocorrências por Hora
                        html.Div(
                            style={
                                'padding': '15px',
                                'backgroundColor': '#fff',
                                'borderRadius': '12px',
                                'boxShadow': '0 4px 15px rgba(0,0,0,0.1)',
                                'height': 'auto'
                            },
                            children=[
                                html.H3("Distribuição de Ocorrências por Hora", style={'textAlign': 'center', 'color': '#d9534f', 'margin': '0'}),
                                html.Div(id='card-horario', className='metric-card', style={
                                    'padding': '20px', 'backgroundColor': '#fff',
                                    'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center'
                                }),
                                dcc.Graph(
                                    id='grafico-ocorrencias-hora-criminal',
                                    style={'height': '60vh', 'width': '100%'}
                                )
                            ]
                        )
                    ]
                ),

                # Segunda Coluna (Mapa e Gráfico de Eventos)
                html.Div(
                    style={
                        'flex': '0 0 48%',
                        'display': 'flex',
                        'flexDirection': 'column',
                        'gap': '20px'
                    },
                    children=[
                        # Mapa de Eventos
                        html.Div(
                            style={
                                'padding': '15px',
                                'backgroundColor': '#fff',
                                'borderRadius': '12px',
                                'boxShadow': '0 4px 15px rgba(0,0,0,0.1)',
                                'height': 'auto'
                            },
                            children=[
                                html.H3("Mapa de Eventos (COSECURITY)", style={'textAlign': 'center', 'color': '#4B77BE', 'margin': '0'}),
                                html.Div(
                                    style={
                                        'display': 'flex', 'justifyContent': 'center', 'gap': '15px', 'margin': '20px 0'
                                    },
                                    children=[
                                        html.Div(id='card-evento-frequente', className='metric-card', style={
                                            'padding': '20px', 'backgroundColor': '#fff',
                                            'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center', 'flex': '1'
                                        }),
                                        html.Div(id='card-total-eventos', className='metric-card', style={
                                            'padding': '20px', 'backgroundColor': '#fff',
                                            'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center', 'flex': '1'
                                        })
                                    ]
                                ),
                                dcc.Graph(
                                    id='mapa-eventos',
                                    config={'scrollZoom': True, 'displayModeBar': False},
                                    style={'height': '60vh', 'width': '100%'}
                                )
                            ]
                        ),
                        
                        # Gráfico de Eventos por Hora
                        html.Div(
                            style={
                                'padding': '15px',
                                'backgroundColor': '#fff',
                                'borderRadius': '12px',
                                'boxShadow': '0 4px 15px rgba(0,0,0,0.1)',
                                'height': 'auto'
                            },
                            children=[
                                html.H3("Distribuição de Eventos por Hora", style={'textAlign': 'center', 'color': '#4B77BE', 'margin': '0'}),
                                html.Div(id='card-horario-eventos', className='metric-card', style={
                                    'padding': '20px', 'backgroundColor': '#fff',
                                    'borderRadius': '12px', 'boxShadow': '0 4px 15px rgba(0,0,0,0.1)', 'textAlign': 'center'
                                }),
                                dcc.Graph(
                                    id='grafico-hora-eventos',
                                    config={'displayModeBar': False},
                                    style={'height': '60vh', 'width': '100%'}
                                )
                            ]
                        )
                    ]
                )
            ]
        )
    ]
)

# ==============================
# 4) CALLBACK PRINCIPAL (AJUSTADO PARA NOVOS FILTROS UNIFICADOS)
# ==============================
@app.callback(
    [Output('mapa-calor-criminal', 'figure'),
     Output('grafico-ocorrencias-hora-criminal', 'figure'),
     Output('card-ocorrencias', 'children'),
     Output('card-horario', 'children'),
     Output('card-natureza', 'children'), # Novo output
     Output('mapa-eventos', 'figure'),
     Output('grafico-hora-eventos', 'figure'),
     Output('card-evento-frequente', 'children'),
     Output('card-horario-eventos', 'children'),
     Output('card-total-eventos', 'children')], # Novo output
    [Input('filtro-mes', 'value'),
     Input('filtro-regiao', 'value'),
     Input('filtro-cidade', 'value'),
     Input('filtro-bairro', 'value'),
     Input('filtro-natureza', 'value'),
     Input('filtro-evento', 'value'),
     Input('filtro-hora', 'value')]
)
def atualizar_dashboard_completo(mes, regiao, cidade, bairro, natureza, evento, hora):
    # --- FILTRAGEM DOS DADOS ---
    df_criminal_filtrado = df_criminal.copy()
    df_eventos_filtrado = df_eventos.copy()

    # Filtros que se aplicam a ambas as fontes de dados
    if mes is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado['mes'] == mes]
        df_eventos_filtrado = df_eventos_filtrado[df_eventos_filtrado['mes'] == mes]
    if cidade is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado['cidade'] == cidade]
        df_eventos_filtrado = df_eventos_filtrado[df_eventos_filtrado['cidade'] == cidade]
    if bairro is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado[COLUNA_BAIRRO_CRIM] == bairro]
        df_eventos_filtrado = df_eventos_filtrado[df_eventos_filtrado['bairro'] == bairro]
    if hora is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado['hora'] == hora]
        df_eventos_filtrado = df_eventos_filtrado[df_eventos_filtrado['hora'] == hora]

    # Filtros específicos do dashboard de crimes
    if regiao is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado['regiao'] == regiao]
    if natureza is not None:
        df_criminal_filtrado = df_criminal_filtrado[df_criminal_filtrado[COLUNA_NATUREZA_CRIM] == natureza]

    # Filtros específicos do dashboard de eventos
    if evento is not None:
        df_eventos_filtrado = df_eventos_filtrado[df_eventos_filtrado['evento_nome'] == evento]

    # --- GERAÇÃO DOS GRÁFICOS E CARTÕES DE CRIMES ---
    df_criminal_sem_hora_zero = df_criminal_filtrado[df_criminal_filtrado['hora'] != 0].copy()
    
    # Mapa Criminal
    contagem_mapa_crim = (
        df_criminal_filtrado
        [[COLUNA_LATITUDE_CRIM, COLUNA_LONGITUDE_CRIM]]
        .dropna()
        .groupby([COLUNA_LATITUDE_CRIM, COLUNA_LONGITUDE_CRIM])
        .size()
        .reset_index(name="casos")
    )
    if contagem_mapa_crim.empty:
        fig_mapa_crim = go.Figure().add_annotation(text="Nenhum dado encontrado para os filtros.")
    else:
        center_lat = contagem_mapa_crim[COLUNA_LATITUDE_CRIM].mean()
        center_lon = contagem_mapa_crim[COLUNA_LONGITUDE_CRIM].mean()
        zoom = 12 if bairro else 10 if regiao else 9
        fig_mapa_crim = px.density_mapbox(
            contagem_mapa_crim, lat=COLUNA_LATITUDE_CRIM, lon=COLUNA_LONGITUDE_CRIM, z="casos",
            radius=15, center=dict(lat=center_lat, lon=center_lon), zoom=zoom,
            mapbox_style="open-street-map", color_continuous_scale=escala_personalizada, opacity=0.8
        )
    fig_mapa_crim.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
    
    # Gráfico de barras de crimes por hora (sem hora 0)
    ocorrencias_por_hora_crim = (
        df_criminal_sem_hora_zero['hora'].value_counts().sort_index().reindex(range(1, 24), fill_value=0)
    )
    fig_hora_crim = px.bar(
        x=ocorrencias_por_hora_crim.index, y=ocorrencias_por_hora_crim.values,
        labels={'x': 'Hora do Dia (24h)', 'y': 'Número de Ocorrências'},
        title="Ocorrências por Hora do Dia", template="plotly_white",
        color_discrete_sequence=['#d9534f'], text_auto=True
    )
    fig_hora_crim.update_layout(
        xaxis={'tickmode': 'linear'}, yaxis={'tickformat': ',.0f'},
        title={'x': 0.5, 'xanchor': 'center'}, margin={"r":20, "t":40, "l":20, "b":20}
    )

    # Cartões de métrica de crimes (sem hora 0)
    total_ocorrencias = len(df_criminal_sem_hora_zero)
    if not ocorrencias_por_hora_crim.empty and ocorrencias_por_hora_crim.max() > 0:
        horario_mais_frequente_crim = int(ocorrencias_por_hora_crim.idxmax())
        horario_txt_crim = f"{horario_mais_frequente_crim:02d}:00"
    else:
        horario_txt_crim = "N/A"
    
    # Cálculo da natureza apurada mais frequente
    if not df_criminal_filtrado.empty:
        natureza_frequente = df_criminal_filtrado[COLUNA_NATUREZA_CRIM].mode().iloc[0] if not df_criminal_filtrado[COLUNA_NATUREZA_CRIM].mode().empty else "N/A"
    else:
        natureza_frequente = "N/A"

    card_ocorrencias = html.Div([html.Div(f'{total_ocorrencias:,}'.replace(',', '.'), className='metric-value'), html.Div('Total de Ocorrências', className='metric-label')])
    card_natureza = html.Div([html.Div(natureza_frequente, className='metric-value'), html.Div('Natureza Mais Frequente', className='metric-label')])
    card_horario = html.Div([html.Div(horario_txt_crim, className='metric-value'), html.Div('Horário Mais Frequente', className='metric-label')])


    # --- GERAÇÃO DOS GRÁFICOS E CARTÕES DE EVENTOS ---
    # Mapa de Eventos
    contagem_mapa_eventos = df_eventos_filtrado.groupby(["latitude", "longitude"], dropna=True).size().reset_index(name="casos")
    
    if not df_eventos_filtrado.empty:
        vc = df_eventos_filtrado['evento_nome'].dropna().value_counts()
        if len(vc) > 0:
            top_evento = vc.index[0]
        else:
            top_evento = "N/A"

        contagem_hora_eventos_reindexed = df_eventos_filtrado['hora'].value_counts().sort_index().reindex(range(24), fill_value=0)
        if not contagem_hora_eventos_reindexed.empty and contagem_hora_eventos_reindexed.max() > 0:
            horario_mais_frequente_eventos = int(contagem_hora_eventos_reindexed.idxmax())
            horario_txt_eventos = f"{horario_mais_frequente_eventos:02d}:00"
        else:
            horario_txt_eventos = "N/A"
    else:
        top_evento = "N/A"
        horario_txt_eventos = "N/A"

    # Definindo coordenadas fixas para o mapa de eventos
    fixed_center_lat = -23.550520
    fixed_center_lon = -46.633308
    fixed_zoom = 12

    if not contagem_mapa_eventos.empty:
        fig_mapa_eventos = px.density_mapbox(
            contagem_mapa_eventos, lat="latitude", lon="longitude", z="casos", radius=18,
            center=dict(lat=fixed_center_lat, lon=fixed_center_lon), zoom=fixed_zoom,
            mapbox_style="open-street-map", color_continuous_scale=escala_personalizada, opacity=1.0
        )
    else:
        fig_mapa_eventos = go.Figure().add_annotation(text="Nenhum evento encontrado para os filtros selecionados.")
    fig_mapa_eventos.update_layout(margin={"r":0, "t":0, "l":0, "b":0})

    # Gráfico de barras de eventos por hora
    contagem_hora_eventos = df_eventos_filtrado['hora'].value_counts().sort_index().reindex(range(24), fill_value=0)
    fig_hora_eventos = px.bar(
        x=contagem_hora_eventos.index, y=contagem_hora_eventos.values,
        labels={'x': 'Hora do Dia', 'y': 'Número de Eventos'},
        title="Distribuição de Eventos por Hora", template="plotly_white",
        color_discrete_sequence=['#4B77BE'], text_auto=True
    )
    fig_hora_eventos.update_layout(
        xaxis={'tickmode': 'linear'}, yaxis={'tickformat': ',.0f'},
        title={'x': 0.5, 'xanchor': 'center'}, margin={"r":20, "t":40, "l":20, "b":20}
    ) 

    # Novos cartões para eventos
    card_evento_frequente = html.Div([html.Div(top_evento, className='metric-value'), html.Div('Evento Mais Frequente', className='metric-label')])
    total_eventos = len(df_eventos_filtrado)
    card_total_eventos = html.Div([html.Div(f'{total_eventos:,}'.replace(',', '.'), className='metric-value'), html.Div('Total de Eventos', className='metric-label')])
    card_horario_eventos = html.Div([html.Div(horario_txt_eventos, className='metric-value'), html.Div('Horário Mais Frequente', className='metric-label')])

    return (
        fig_mapa_crim, fig_hora_crim, card_ocorrencias, card_horario, card_natureza,
        fig_mapa_eventos, fig_hora_eventos, card_evento_frequente, card_horario_eventos, card_total_eventos
    )

# A linha de execução do servidor foi removida, pois será gerenciada pelo Gunicorn.
# Para a execução local, você pode usar 'python app.py' com o Gunicorn.
#if __name__ == "__main__":
#    server.run(debug=True)
