import streamlit as st
import requests
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import altair as alt

# ==========================================
# FUNZIONI DI CALCOLO E DATI
# ==========================================

def scarica_produzione_ninja(lat, lon, token_api, mw_installati, turbina_scelta, anno=2019):
    """Interroga l'API di Renewables.ninja per l'EOLICO."""
    url = 'https://www.renewables.ninja/api/data/wind'
    headers = {'Authorization': f'Token {token_api}'}
    params = {
        'lat': lat, 'lon': lon,
        'date_from': f'{anno}-01-01', 'date_to': f'{anno}-12-31',
        'capacity': mw_installati * 1000,
        'height': 100,                     
        'turbine': turbina_scelta,
        'dataset': 'merra2',           
        'format': 'json'
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        st.error(f"Errore API Eolico (Lat {lat:.2f}, Lon {lon:.2f}): {r.text}")
        return None
        
    return _estrai_dati_ninja(r.json())

def scarica_produzione_fv_ninja(lat, lon, token_api, mw_installati, tipo_impianto, anno=2019):
    """Interroga l'API di Renewables.ninja per il FOTOVOLTAICO."""
    url = 'https://www.renewables.ninja/api/data/pv'
    headers = {'Authorization': f'Token {token_api}'}
    
    tracking = 1 if "Inseguitore" in tipo_impianto else 0
    
    params = {
        'lat': lat, 'lon': lon,
        'date_from': f'{anno}-01-01', 'date_to': f'{anno}-12-31',
        'capacity': mw_installati * 1000,
        'system_loss': 0.1,  
        'tracking': tracking,
        'tilt': 35,          
        'azim': 180,         
        'dataset': 'merra2',
        'format': 'json'
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        st.error(f"Errore API Fotovoltaico (Lat {lat:.2f}, Lon {lon:.2f}): {r.text}")
        return None
        
    return _estrai_dati_ninja(r.json())

def _estrai_dati_ninja(dati_json):
    """Funzione di sicurezza per estrarre la serie oraria dai JSON di Ninja"""
    if 'data' not in dati_json or len(dati_json['data']) == 0:
        st.error("L'API non ha restituito dati per queste coordinate.")
        return None
        
    records = []
    for time_key, value in dati_json['data'].items():
        if isinstance(value, dict):
            energia = value.get('electricity', list(value.values())[0] if value else 0.0)
        else:
            energia = value
        records.append({'Data_Ora': time_key, 'Produzione_kW': energia})
        
    df = pd.DataFrame(records)
    
    primo_valore = str(df['Data_Ora'].iloc[0])
    if primo_valore.isdigit():
        df['Data_Ora'] = pd.to_datetime(df['Data_Ora'].astype(float), unit='ms', utc=True)
    else:
        df['Data_Ora'] = pd.to_datetime(df['Data_Ora'], utc=True)
        
    df['Data_Ora'] = df['Data_Ora'].dt.tz_localize(None)
    df['Produzione_kW'] = pd.to_numeric(df['Produzione_kW'], errors='coerce').fillna(0)
    df['Produzione_MW'] = df['Produzione_kW'] / 1000.0
    return df

@st.cache_data(show_spinner=False)
def carica_fabbisogno_reale(file_path='20190101_20191231_MGP_Fabbisogno.xlsx'):
    try:
        df = pd.read_excel(file_path, thousands='.', decimal=',')
        rename_map = {'Nord': 'NORD', 'Centro Nord': 'CNOR', 'Centro Sud': 'CSUD', 
                      'Sud': 'SUD', 'Sicilia': 'SICI', 'Sardegna': 'SARD'}
        df = df.rename(columns=rename_map)
        df['Data_Ora'] = pd.to_datetime(df['Data'], format='%d/%m/%Y') + pd.to_timedelta(df['Ora'] - 1, unit='h')
        return df[['Data_Ora', 'NORD', 'CNOR', 'CSUD', 'SUD', 'SICI', 'SARD']]
    except Exception as e:
        return None

# ==========================================
# INTERFACCIA STREAMLIT
# ==========================================

st.set_page_config(page_title="Simulatore Flotta Rinnovabile", layout="wide")
st.title("☀️🌬️ Simulatore Macro-Energetico: Eolico + Fotovoltaico")

if 'flotta' not in st.session_state:
    st.session_state.flotta = []
if "map_center" not in st.session_state: 
    st.session_state.map_center = [41.9, 12.5] 

with st.expander("ℹ️ Come funziona questo scenario?"):
    st.markdown("""
    Questo strumento simula l'impatto di un portafoglio di impianti rinnovabili sul carico termico italiano (dati reali 2019).
    - Puoi mixare **Parchi Eolici** e **Campi Fotovoltaici**.
    - L'ipotesi di base è **Zero Trasmissione**: l'energia prodotta in una zona copre i consumi di quella specifica zona.
    """)

col_mappa, col_flotta = st.columns([1.2, 1])

with col_mappa:
    st.subheader("1. Posiziona Impianti")
    m = folium.Map(location=st.session_state.map_center, zoom_start=6)
    
    folium.TileLayer(tiles='OpenTopoMap', name='Mappa Topografica (Rilievi)').add_to(m)
    folium.TileLayer(tiles='OpenStreetMap', name='Mappa Stradale').add_to(m)
    folium.LayerControl().add_to(m)
    
    for i, parco in enumerate(st.session_state.flotta):
        colore = "blue" if parco['tipo'] == 'Eolico' else "orange"
        icona = "leaf" if parco['tipo'] == 'Eolico' else "sun"
        folium.Marker(
            [parco['lat'], parco['lon']], 
            popup=f"{parco['tipo']} ({parco['zona']}) - {parco['mw']} MW",
            icon=folium.Icon(color=colore, icon=icona)
        ).add_to(m)
        
    mappa = st_folium(m, height=450, use_container_width=True)

with col_flotta:
    st.subheader("2. Aggiungi al Portafoglio")
    
    if mappa is not None and "last_clicked" in mappa and mappa["last_clicked"] is not None:
        lat_click = mappa["last_clicked"]["lat"]
        lon_click = mappa["last_clicked"]["lng"]
    else:
        lat_click = 41.9
        lon_click = 12.5
    
    # ⚠️ FIX: Selettore spostato FUORI dal form per renderlo interattivo
    tipo_fonte = st.radio("Tecnologia:", ["🌬️ Eolico", "☀️ Fotovoltaico"], horizontal=True)
    
    with st.form("aggiungi_parco"):
        
        c1, c2 = st.columns(2)
        lat_in = c1.number_input("Latitudine", value=lat_click, format="%.4f")
        lon_in = c2.number_input("Longitudine", value=lon_click, format="%.4f")
        
        c3, c4 = st.columns(2)
        zona_in = c3.selectbox("Zona di Mercato", ["NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD"])
        mw_in = c4.number_input("Capacità Installata (MW)", min_value=1.0, value=50.0, step=10.0)
        
        if "Eolico" in tipo_fonte:
            modelli = {
                "Onshore Grande (Vestas V150 - 4.2 MW)": "Vestas V150 4200", # ⚠️ FIX: Ora è di default
                "Onshore Standard (Vestas V112 - 3.3 MW)": "Vestas V112 3300",
                "Offshore Gigante (Vestas V164 - 9.5 MW)": "Vestas V164 9500"
            }
            scelta_tecnica = st.selectbox("Modello Turbina", list(modelli.keys()))
            id_tecnico = modelli[scelta_tecnica]
        else:
            modelli = {
                "Fisso (Orientamento Sud, Tilt 35°)": "Fisso",
                "Inseguitore Monoassiale (Est-Ovest)": "Inseguitore"
            }
            scelta_tecnica = st.selectbox("Tipologia Impianto", list(modelli.keys()))
            id_tecnico = modelli[scelta_tecnica]
        
        submit_parco = st.form_submit_button("➕ Aggiungi Impianto alla Flotta")
        if submit_parco:
            st.session_state.flotta.append({
                "id": len(st.session_state.flotta) + 1,
                "tipo": "Eolico" if "Eolico" in tipo_fonte else "Fotovoltaico",
                "lat": lat_in, "lon": lon_in, 
                "zona": zona_in, "mw": mw_in,
                "dettaglio_id": id_tecnico,
                "dettaglio_nome": scelta_tecnica
            })
            st.rerun()

    st.subheader("La tua Flotta")
    if len(st.session_state.flotta) > 0:
        df_flotta = pd.DataFrame(st.session_state.flotta)
        st.dataframe(df_flotta[['tipo', 'zona', 'mw', 'lat', 'lon']], hide_index=True, use_container_width=True)
        if st.button("🗑️ Svuota Flotta"):
            st.session_state.flotta = []
            st.rerun()
    else:
        st.info("Nessun impianto aggiunto. Clicca sulla mappa.")

st.divider()
st.subheader("3. Avvia Simulazione")

# INSERISCI QUI IL TUO TOKEN API DI RENEWABLES.NINJA
TOKEN_NINJA = "c6039a7ae92563c77ebbb7586ba45a1c7cf42dc8"

if st.button("🚀 Avvia Simulazione di Rete (Anno 2019)", type="primary", use_container_width=True):
    if len(st.session_state.flotta) == 0:
        st.warning("Aggiungi almeno un impianto alla flotta prima di simulare.")
    elif TOKEN_NINJA == "INSERISCI_QUI_IL_TUO_TOKEN":
        st.error("⚠️ Devi inserire il tuo Token API nel codice (riga 197) prima di avviare la simulazione.")
    else:
        with st.spinner("Caricamento dati reali Terna e connessione API in corso..."):
            df_carico = carica_fabbisogno_reale('20190101_20191231_MGP_Fabbisogno.xlsx')
            
            if df_carico is None:
                st.error("❌ Errore: File Excel del fabbisogno non trovato o illeggibile. Assicurati di averlo caricato su GitHub e di avere 'openpyxl' in requirements.txt.")
                st.stop()
                
            df_prod_zone = pd.DataFrame({'Data_Ora': df_carico['Data_Ora']})
            for zona in ["NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD"]:
                df_prod_zone[zona] = 0.0
            
            errori = False
            for impianto in st.session_state.flotta:
                if impianto['tipo'] == 'Eolico':
                    df_produzione = scarica_produzione_ninja(
                        impianto['lat'], impianto['lon'], TOKEN_NINJA, 
                        impianto['mw'], impianto['dettaglio_id'], 2019
                    )
                else:
                    df_produzione = scarica_produzione_fv_ninja(
                        impianto['lat'], impianto['lon'], TOKEN_NINJA, 
                        impianto['mw'], impianto['dettaglio_id'], 2019
                    )
                
                if df_produzione is not None:
                    df_prod_zone[impianto['zona']] += df_produzione['Produzione_MW'].values
                    st.toast(f"✅ {impianto['tipo']} in {impianto['zona']}: {df_produzione['Produzione_MW'].sum()/1000:.1f} GWh annui")
                else:
                    errori = True
                    
            if not errori:
                zone_attive = df_flotta['zona'].unique().tolist()
                tabs = st.tabs(zone_attive + ["Riepilogo Nazionale"])
                
                df_nazionale_carico = 0
                df_nazionale_residuo = 0
                
                for idx, zona in enumerate(zone_attive):
                    carico_zona = df_carico[zona]
                    rinnovabili_zona = df_prod_zone[zona]
                    
                    carico_residuo = np.maximum(carico_zona - rinnovabili_zona, 0)
                    curtailment = np.maximum(rinnovabili_zona - carico_zona, 0)
                    
                    energia_richiesta_gwh = carico_zona.sum() / 1000
                    energia_rinnovabile_gwh = rinnovabili_zona.sum() / 1000
                    energia_termica_residua_gwh = carico_residuo.sum() / 1000
                    energia_tagliata_gwh = curtailment.sum() / 1000
                    copertura_pct = ((energia_richiesta_gwh - energia_termica_residua_gwh) / energia_richiesta_gwh) * 100
                    
                    df_nazionale_carico += carico_zona
                    df_nazionale_residuo += carico_residuo
                    
                    with tabs[idx]:
                        st.subheader(f"Zona {zona} - Risultati 2019")
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Capacità Rinnovabile (MW)", df_flotta[df_flotta['zona']==zona]['mw'].sum())
                        m2.metric("Copertura del Carico", f"{copertura_pct:.1f} %")
                        m3.metric("Energia Verde Prodotta", f"{energia_rinnovabile_gwh:.0f} GWh")
                        m4.metric("Overgeneration (Sprecata)", f"{energia_tagliata_gwh:.0f} GWh")
                        
                        st.markdown("#### Andamento del Carico (8760 ore)")
                        st.caption("🖱️ Usa la rotellina del mouse per fare zoom sui singoli mesi o giorni (vedrai chiaramente i picchi solari diurni).")
                        
                        df_chrono = pd.DataFrame({
                            'Data': df_carico['Data_Ora'],
                            'Carico Iniziale (MW)': carico_zona,
                            'Carico Residuo (MW)': carico_residuo
                        }).melt('Data', var_name='Tipo', value_name='MW')
                        
                        chart_chrono = alt.Chart(df_chrono).mark_line(opacity=0.8, strokeWidth=1).encode(
                            x=alt.X('Data:T', title='Mese del 2019'),
                            y=alt.Y('MW:Q', title='Potenza (MW)'),
                            color=alt.Color(
                                'Tipo:N', 
                                scale=alt.Scale(domain=['Carico Iniziale (MW)', 'Carico Residuo (MW)'], range=['#CCCCCC', '#FF3333']),
                                legend=alt.Legend(title="Legenda")
                            ),
                            tooltip=[alt.Tooltip('Data:T', format='%d %b %H:00'), 'Tipo:N', alt.Tooltip('MW:Q', format='.0f')]
                        ).properties(height=400).interactive(bind_y=False) 
                        
                        st.altair_chart(chart_chrono, use_container_width=True)
    
                with tabs[-1]:
                    st.subheader("Impatto Aggregato di Sistema")
                    st.info("Ipotesi 'Zero Trasmissione': i numeri sono la somma aritmetica delle singole zone.")
                    
                    carico_tot = df_nazionale_carico.sum() / 1000
                    residuo_tot = df_nazionale_residuo.sum() / 1000
                    risparmio_gas = (carico_tot - residuo_tot) * 0.20 
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Totale Carico Ridotto (GWh)", f"{(carico_tot - residuo_tot):.0f}")
                    c2.metric("Risparmio stimato Gas (Mln Smc)", f"{risparmio_gas/1000:.0f}")
                    c3.metric("Capacità Totale Flotta (MW)", df_flotta['mw'].sum())
