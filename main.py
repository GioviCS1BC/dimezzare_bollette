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

def scarica_produzione_ninja(lat, lon, token_api, mw_installati, anno=2023):
    """
    Interroga l'API di Renewables.ninja per ottenere la produzione oraria diretta (in MW).
    I loro modelli includono già l'orografia del terreno e le curve di potenza delle turbine.
    """
    url = 'https://www.renewables.ninja/api/data/wind'
    headers = {'Authorization': f'Token {token_api}'}
    params = {
        'lat': lat,
        'lon': lon,
        'date_from': f'{anno}-01-01',
        'date_to': f'{anno}-12-31',
        'capacity': mw_installati * 1000,  # L'API ragiona in kW
        'height': 100,                     # Altezza mozzo (100 metri)
        'turbine': 'Vestas V112 3300',     # Turbina di riferimento
        'format': 'json'
    }
    
    r = requests.get(url, headers=headers, params=params)
    
    if r.status_code != 200:
        st.error(f"Errore API (Lat {lat:.2f}, Lon {lon:.2f}): {r.text}")
        return None
        
    dati = r.json()
    df = pd.DataFrame(list(dati['data'].items()), columns=['Data_Ora', 'Produzione_MW'])
    df['Data_Ora'] = pd.to_datetime(df['Data_Ora']).dt.tz_localize(None)
    df['Produzione_MW'] = df['Produzione_MW'] / 1000.0  # Riportiamo in MW
    
    return df

@st.cache_data(show_spinner=False)
def genera_carico_sintetico(anno=2023):
    """Genera un carico termico residuo fittizio (in MW) per le 6 zone italiane."""
    date_rng = pd.date_range(start=f'{anno}-01-01', end=f'{anno}-12-31 23:00:00', freq='h')
    ore = len(date_rng)
    
    base_load = {'NORD': 15000, 'CNOR': 3000, 'CSUD': 4000, 'SUD': 2500, 'SICI': 2000, 'SARD': 1000}
    df_carico = pd.DataFrame({'Data_Ora': date_rng})
    
    for zona, base in base_load.items():
        ciclo_giornaliero = -np.cos(np.linspace(0, 2 * np.pi, 24)) * (base * 0.2)
        ciclo_annuale = np.cos(np.linspace(0, 2 * np.pi, ore)) * (base * 0.15)
        rumore = np.random.normal(0, base * 0.05, ore)
        
        carico_orario = base + np.tile(ciclo_giornaliero, ore // 24 + 1)[:ore] + ciclo_annuale + rumore
        df_carico[zona] = np.maximum(carico_orario, base * 0.4) 
        
    return df_carico

# ==========================================
# INTERFACCIA STREAMLIT
# ==========================================

st.set_page_config(page_title="Simulatore Flotta Eolica (Renewables.ninja)", layout="wide")
st.title("🌬️ Simulatore Macro-Energetico Eolico")

if 'flotta' not in st.session_state:
    st.session_state.flotta = []
if "map_center" not in st.session_state: 
    st.session_state.map_center = [41.9, 12.5] 

with st.expander("ℹ️ Come funziona questo scenario?"):
    st.markdown("""
    Questo strumento simula l'impatto di un portafoglio di parchi eolici sulla rete elettrica, analizzando le **Zone di Mercato** italiane (NORD, CNOR, CSUD, SUD, SICI, SARD).
    - Il motore meteo è **Renewables.ninja**, che calcola l'aerodinamica reale del terreno (orografia) e l'efficienza delle turbine commerciali.
    - L'ipotesi di base è **Zero Trasmissione**: l'energia prodotta in una zona può essere consumata solo in quella zona.
    - Aggiungi parchi sulla mappa e avvia la simulazione oraria dell'intero anno.
    """)

col_mappa, col_flotta = st.columns([1.2, 1])

with col_mappa:
    st.subheader("1. Posiziona Parchi Eolici")
    st.caption("Usa il menu in alto a destra sulla mappa per attivare la vista Rilievi Topografici.")
    
    m = folium.Map(location=st.session_state.map_center, zoom_start=6)
    
    # Livelli mappa
    folium.TileLayer(tiles='OpenTopoMap', name='Mappa Topografica (Rilievi)').add_to(m)
    folium.TileLayer(tiles='OpenStreetMap', name='Mappa Stradale').add_to(m)
    folium.LayerControl().add_to(m)
    
    for i, parco in enumerate(st.session_state.flotta):
        folium.Marker(
            [parco['lat'], parco['lon']], 
            popup=f"{parco['zona']} - {parco['mw']} MW",
            icon=folium.Icon(color="green", icon="leaf")
        ).add_to(m)
        
    mappa = st_folium(m, height=450, use_container_width=True)

with col_flotta:
    st.subheader("2. Aggiungi al Portafoglio")
    
    # Recupero coordinate con controlli di sicurezza
    if mappa is not None and "last_clicked" in mappa and mappa["last_clicked"] is not None:
        lat_click = mappa["last_clicked"]["lat"]
        lon_click = mappa["last_clicked"]["lng"]
    else:
        lat_click = 41.9
        lon_click = 12.5
    
    with st.form("aggiungi_parco"):
        c1, c2 = st.columns(2)
        lat_in = c1.number_input("Latitudine", value=lat_click, format="%.4f")
        lon_in = c2.number_input("Longitudine", value=lon_click, format="%.4f")
        
        c3, c4 = st.columns(2)
        zona_in = c3.selectbox("Zona di Mercato", ["NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD"])
        mw_in = c4.number_input("Capacità Installata (MW)", min_value=1.0, value=50.0, step=10.0)
        
        submit_parco = st.form_submit_button("➕ Aggiungi Parco alla Flotta")
        if submit_parco:
            st.session_state.flotta.append({
                "id": len(st.session_state.flotta) + 1,
                "lat": lat_in, "lon": lon_in, 
                "zona": zona_in, "mw": mw_in
            })
            st.rerun()

    st.subheader("La tua Flotta")
    if len(st.session_state.flotta) > 0:
        df_flotta = pd.DataFrame(st.session_state.flotta)
        st.dataframe(df_flotta[['id', 'zona', 'mw', 'lat', 'lon']], hide_index=True, use_container_width=True)
        if st.button("🗑️ Svuota Flotta"):
            st.session_state.flotta = []
            st.rerun()
    else:
        st.info("Nessun parco aggiunto. Clicca sulla mappa.")

st.divider()
st.subheader("3. Avvia Simulazione")

# INSERISCI QUI IL TUO TOKEN API DI RENEWABLES.NINJA
TOKEN_NINJA = "INSERISCI_QUI_IL_TUO_TOKEN"

if st.button("🚀 Avvia Simulazione di Rete (Anno 2023)", type="primary", use_container_width=True):
    if len(st.session_state.flotta) == 0:
        st.warning("Aggiungi almeno un parco eolico alla flotta prima di simulare.")
    elif TOKEN_NINJA == "INSERISCI_QUI_IL_TUO_TOKEN":
        st.error("⚠️ Devi inserire il tuo Token API nel codice (riga 126) prima di avviare la simulazione.")
    else:
        with st.spinner("Connessione a Renewables.ninja in corso..."):
            df_carico = genera_carico_sintetico(2023)
            df_prod_zone = pd.DataFrame({'Data_Ora': df_carico['Data_Ora']})
            for zona in ["NORD", "CNOR", "CSUD", "SUD", "SICI", "SARD"]:
                df_prod_zone[zona] = 0.0
            
            errori = False
            for parco in st.session_state.flotta:
                df_produzione = scarica_produzione_ninja(
                    parco['lat'], 
                    parco['lon'], 
                    TOKEN_NINJA, 
                    parco['mw'], 
                    2023
                )
                if df_produzione is not None:
                    # L'API restituisce già i MW reali
                    df_prod_zone[parco['zona']] += df_produzione['Produzione_MW'].values
                else:
                    errori = True
                    
            if not errori:
                zone_attive = df_flotta['zona'].unique().tolist()
                tabs = st.tabs(zone_attive + ["Riepilogo Nazionale"])
                
                df_nazionale_carico = 0
                df_nazionale_residuo = 0
                
                for idx, zona in enumerate(zone_attive):
                    carico_zona = df_carico[zona]
                    eolico_zona = df_prod_zone[zona]
                    
                    carico_residuo = np.maximum(carico_zona - eolico_zona, 0)
                    curtailment = np.maximum(eolico_zona - carico_zona, 0)
                    
                    energia_richiesta_gwh = carico_zona.sum() / 1000
                    energia_eolica_gwh = eolico_zona.sum() / 1000
                    energia_termica_residua_gwh = carico_residuo.sum() / 1000
                    energia_tagliata_gwh = curtailment.sum() / 1000
                    copertura_pct = ((energia_richiesta_gwh - energia_termica_residua_gwh) / energia_richiesta_gwh) * 100
                    
                    df_nazionale_carico += carico_zona
                    df_nazionale_residuo += carico_residuo
                    
                    with tabs[idx]:
                        st.subheader(f"Zona {zona} - Risultati 2023")
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Capacità Eolica (MW)", df_flotta[df_flotta['zona']==zona]['mw'].sum())
                        m2.metric("Copertura del Carico", f"{copertura_pct:.1f} %")
                        m3.metric("Energia Eolica Prodotta", f"{energia_eolica_gwh:.0f} GWh")
                        m4.metric("Overgeneration (Sprecata)", f"{energia_tagliata_gwh:.0f} GWh")
                        
                        st.markdown("#### Andamento del Carico (8760 ore)")
                        st.caption("🖱️ Usa la rotellina del mouse per fare zoom sui singoli mesi o giorni.")
                        
                        df_chrono = pd.DataFrame({
                            'Data': df_carico['Data_Ora'],
                            'Carico Iniziale (MW)': carico_zona,
                            'Carico Residuo (MW)': carico_residuo
                        }).melt('Data', var_name='Tipo', value_name='MW')
                        
                        chart_chrono = alt.Chart(df_chrono).mark_line(opacity=0.8, strokeWidth=1).encode(
                            x=alt.X('Data:T', title='Mese del 2023'),
                            y=alt.Y('MW:Q', title='Potenza (MW)'),
                            color=alt.Color(
                                'Tipo:N', 
                                scale=alt.Scale(domain=['Carico Iniziale (MW)', 'Carico Residuo (MW)'], range=['#CCCCCC', '#FF3333']),
                                legend=alt.Legend(title="Legenda")
                            ),
                            tooltip=[alt.Tooltip('Data:T', format='%d %b %H:00'), 'Tipo:N', alt.Tooltip('MW:Q', format='.0f')]
                        ).properties(
                            height=400
                        ).interactive(bind_y=False) 
                        
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
