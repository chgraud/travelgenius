import streamlit as st
from amadeus import Client
import google.generativeai as genai
import os
import urllib.parse
from datetime import datetime, timedelta
import calendar
import time
import pydeck as pdk
import json
import re
from dotenv import load_dotenv

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
load_dotenv()
st.set_page_config(page_title="Travel Genius Pro 5.3", layout="wide", page_icon="🌍")

BLOQUES_HORARIOS = {
    "Cualquier hora": (0, 24), "Mañana (06:00 - 12:00)": (6, 12),
    "Mediodía (12:00 - 15:00)": (12, 15), "Tarde (15:00 - 21:00)": (15, 21),
    "Noche (21:00 - 06:00)": (21, 6)
}

CIUDADES_TRADUCCION = {
    'londres': 'LON', 'nueva york': 'NYC', 'roma': 'ROM', 
    'paris': 'PAR', 'ginebra': 'GVA', 'berlin': 'BER', 
    'tokio': 'TYO', 'milan': 'MIL', 'estambul': 'IST',
    'madrid': 'MAD', 'barcelona': 'BCN', 'bilbao': 'BIO',
    'lisboa': 'LIS', 'oporto': 'OPO', 'burdeos': 'BOD', 'tours': 'TUF'
}

@st.cache_resource
def iniciar_servicios():
    try:
        am_client = Client(client_id=os.getenv("AMADEUS_KEY"), client_secret=os.getenv("AMADEUS_SECRET"))
        genai.configure(api_key=os.getenv("GEMINI_KEY"))
        modelo_disponible = next((m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods), "gemini-1.5-flash")
        return am_client, genai.GenerativeModel(modelo_disponible)
    except: return None, None

amadeus, model = iniciar_servicios()

# --- FUNCIONES NÚCLEO ---
@st.cache_data(show_spinner=False, ttl=3600)
def preguntar_ia_seguro(prompt_texto):
    if not model: return "⚠️ IA no disponible."
    for i in range(3):
        try:
            time.sleep(0.5)
            return model.generate_content(prompt_texto).text
        except Exception as e:
            if "429" in str(e).lower() or "quota" in str(e).lower():
                time.sleep(20)
                continue
            return f"❌ Error: {str(e)}"
    return "❌ Límite alcanzado."

@st.cache_data(show_spinner=False, ttl=86400)
def obtener_iata_dinamico(ciudad):
    if not ciudad: return "MAD"
    
    # 1. Comprobar diccionario local primero (Ultra rápido y sin gastar IA)
    ciudad_limpia = ciudad.strip().lower()
    if ciudad_limpia in CIUDADES_TRADUCCION:
        return CIUDADES_TRADUCCION[ciudad_limpia]
        
    # 2. Si es una ciudad rara, entonces sí le preguntamos a la IA
    prompt = f"Dime SOLO el código IATA de 3 letras del aeropuerto comercial más práctico para viajar a '{ciudad}'. Si es un pueblo sin aeropuerto, dime el aeropuerto principal más cercano. Solo las 3 letras mayúsculas."
    respuesta = preguntar_ia_seguro(prompt).strip().upper()
    match = re.search(r'\b[A-Z]{3}\b', respuesta)
    return match.group(0) if match else "MAD"

@st.cache_data(show_spinner=False, ttl=3600)
def buscar_vuelos_amadeus_cache(iata_o, iata_d, f_ida, f_vta, api_adults, api_children, api_infants):
    try:
        search_params = {
            'originLocationCode': iata_o, 'destinationLocationCode': iata_d,
            'departureDate': str(f_ida), 'returnDate': str(f_vta),
            'adults': api_adults, 'max': 50
        }
        if api_children > 0: search_params['children'] = api_children
        if api_infants > 0: search_params['infants'] = api_infants
        return amadeus.shopping.flight_offers_search.get(**search_params)
    except: return None

def calcular_fecha(mes, dias, tipo, semana=1, inicio=10):
    hoy = datetime.now()
    año = hoy.year if mes >= hoy.month else hoy.year + 1
    u = calendar.monthrange(año, mes)[1]
    p = datetime(año, mes, 1)
    if tipo == "puente":
        j = (3 - p.weekday() + 7) % 7
        ida = p + timedelta(days=j) + timedelta(weeks=(semana - 1))
        if dias == 3: ida += timedelta(days=1)
    else: ida = datetime(año, mes, min(inicio, u))
    return ida.date(), (ida + timedelta(days=dias)).date()

# --- BARRA LATERAL ---
if 'busqueda_iniciada' not in st.session_state:
    st.session_state.busqueda_iniciada = False

st.title("🌍 Travel Genius Pro: Roadtrip Universal")

MESES_FULL = [(1,"Enero"), (2,"Febrero"), (3,"Marzo"), (4,"Abril"), (5,"Mayo"), (6,"Junio"),
              (7,"Julio"), (8,"Agosto"), (9,"Septiembre"), (10,"Octubre"), (11,"Noviembre"), (12,"Diciembre")]

with st.sidebar:
    st.header("1. Perfil del Viaje")
    tipo_viaje = st.radio("Modo de Inteligencia:", ["🏙️ Ciudad Única", "🚗 Roadtrip / Ruta"])
    
    c_orig = st.text_input("Origen:", "Bilbao")
    
    if tipo_viaje == "🏙️ Ciudad Única":
        c_dest = st.text_input("Destino:", "")
        pref_trans = "Cualquiera"
        ritmo_ruta = "N/A"
    else:
        c_dest = st.text_area("Ruta (ciudades separadas por coma):", "")
        pref_trans = st.selectbox("Preferencia de Transporte:", ["🚗 Coche Propio / Alquiler", "🚆 Transporte Público"])
        ritmo_ruta = st.select_slider("Ritmo:", options=["Relajado", "Equilibrado", "Intenso"], value="Equilibrado")

    num_adultos = st.number_input("👥 Adultos", 1, 9, 2)
    viajan_ninos = st.checkbox("👶 ¿Niños/Bebés?")
    edades_ninos = []
    if viajan_ninos:
        num_ninos = st.number_input("¿Cuántos niños?", 1, 5, 1)
        cols_edades = st.columns(num_ninos)
        for i in range(num_ninos):
            with cols_edades[i]: edades_ninos.append(st.number_input(f"Edad {i+1}", 0, 17, 5, key=f"e_{i}"))

    num_viajeros = num_adultos + len(edades_ninos)
    grupo_texto = f"{num_adultos} adultos" + (f" y {len(edades_ninos)} niños" if edades_ninos else "")
    api_adults = num_adultos + sum(1 for e in edades_ninos if e >= 12)
    api_children = sum(1 for e in edades_ninos if 2 <= e < 12)
    api_infants = sum(1 for e in edades_ninos if e < 2)

    estilo_viaje = st.selectbox("🎒 Plan:", ["Solo/Mochilero", "Escapada Romántica", "Familia con Niños", "Grupo de Amigos/Fiesta"])
    
    st.header("2. Fechas")
    modo = st.radio("Modo:", ["Exactas", "Puente (Selector Semanal)", "Mes Flexible"])
    if modo == "Exactas":
        r = st.date_input("Días:", [])
        if len(r) == 2:
            f_ida, f_vta = r[0], r[1]
            num_dias = (f_vta - f_ida).days
        else: f_ida = f_vta = num_dias = 0
    elif modo == "Puente (Selector Semanal)":
        m_sel = st.selectbox("Mes:", MESES_FULL, format_func=lambda x: x[1])
        sem = st.radio("Semana:", [1, 2, 3, 4], horizontal=True)
        num_dias = st.slider("Días:", 3, 5, 4)
        f_ida, f_vta = calcular_fecha(m_sel[0], num_dias, "puente", sem)
    else:
        m_sel = st.selectbox("Mes:", MESES_FULL, format_func=lambda x: x[1])
        d_i = st.slider("Salida aprox:", 1, 28, 10)
        num_dias = st.number_input("Noches:", min_value=2, value=7)
        f_ida, f_vta = calcular_fecha(m_sel[0], num_dias, "flexible", inicio=d_i)

    st.header("3. Filtros de Vuelo")
    pref_ida = st.selectbox("🛫 Horario de IDA:", list(BLOQUES_HORARIOS.keys()))
    pref_vta = st.selectbox("🛬 Horario de VUELTA:", list(BLOQUES_HORARIOS.keys()))
    solo_d = st.checkbox("✈️ Solo vuelos directos", value=True)
    
    if st.button("🚀 Planificar", type="primary"):
        if c_orig and c_dest:
            st.session_state.busqueda_iniciada = True
            for k in ['mapa_gen', 'hoteles_gen', 'semaforo_vuelo', 'analisis_transporte', 'guia_p1', 'guia_p2', 'guia_p3', 'iata_origen', 'iata_destino', 'barrios_gen', 'coches_gen']:
                if k in st.session_state: del st.session_state[k]
        else:
            st.warning("⚠️ Por favor, rellena el Origen y el Destino para comenzar.")

# --- LÓGICA DE RESULTADOS ---
if st.session_state.busqueda_iniciada and f_ida and c_orig and c_dest:
    # 🛡️ SOLUCIÓN: Aislar el destino real ignorando el origen si lo ponen al principio
    if tipo_viaje == "🚗 Roadtrip / Ruta":
        destinos_lista = [c.strip() for c in c_dest.split(',')]
        # Si el primer destino es igual al origen (ej. Bilbao a Bilbao), cogemos el segundo
        if len(destinos_lista) > 1 and destinos_lista[0].lower() == c_orig.lower():
            ciudad_1 = destinos_lista[1]
        else:
            ciudad_1 = destinos_lista[0]
    else:
        ciudad_1 = c_dest
        
    st.write("---")
    
    # 🧠 PASO 0: OBTENER IATAS Y DIAGNÓSTICO
    if 'iata_origen' not in st.session_state:
        with st.spinner("Mapeando aeropuertos más cercanos..."):
            st.session_state.iata_origen = obtener_iata_dinamico(c_orig)
            st.session_state.iata_destino = obtener_iata_dinamico(ciudad_1)

    if 'analisis_transporte' not in st.session_state:
        with st.spinner("Analizando logística del primer salto..."):
            prompt_dist = f"""Origen: '{c_orig}'. Primera parada: '{ciudad_1}'.
            Analiza ÚNICAMENTE la viabilidad de llegar desde el origen a la primera parada. Ignora el resto de la ruta.
            - Si están cerca (<600km) o es cómodo ir en coche/tren, responde 'VUELOS_NO' y explica.
            - Si están lejos (>600km) o en otro país, responde 'VUELOS_SI' y explica que es mejor volar al inicio.
            Responde empezando con la palabra clave."""
            st.session_state.analisis_transporte = preguntar_ia_seguro(prompt_dist)

    st.subheader("🏁 Diagnóstico de Salida")
    st.info(st.session_state.analisis_transporte)

    col_v, col_h = st.columns([1.1, 0.9])
    
    with col_v:
        if "VUELOS_SI" in st.session_state.analisis_transporte:
            st.subheader(f"🛫 Vuelos: {st.session_state.iata_origen} ➔ {st.session_state.iata_destino}")
            res = buscar_vuelos_amadeus_cache(st.session_state.iata_origen, st.session_state.iata_destino, f_ida, f_vta, api_adults, api_children, api_infants)
            
            if res and res.data:
                carriers = res.result.get('dictionaries', {}).get('carriers', {})
                v_vistos, v_unicos = set(), []
                for v in res.data:
                    huella = (v['itineraries'][0]['segments'][0]['departure']['at'], v['price']['total'])
                    if huella not in v_vistos:
                        v_vistos.add(huella)
                        v_unicos.append(v)
                
                v_directos = [v for v in v_unicos if all(len(it['segments'])==1 for it in v['itineraries'])]
                
                if solo_d:
                    if v_directos:
                        st.success("✅ Vuelos directos encontrados.")
                        v_base = v_directos
                    else:
                        st.warning("⚠️ No hay vuelos directos disponibles. Mostrando opciones con escala:")
                        v_base = v_unicos
                else:
                    v_base = v_unicos

                v_filtrados = []
                for v in v_base:
                    h_ida = int(v['itineraries'][0]['segments'][0]['departure']['at'][11:13])
                    h_vta = int(v['itineraries'][1]['segments'][0]['departure']['at'][11:13])
                    s_ida, e_ida = BLOQUES_HORARIOS[pref_ida]
                    ida_ok = (s_ida <= h_ida < e_ida) if s_ida < e_ida else (h_ida >= s_ida or h_ida < e_ida)
                    s_vta, e_vta = BLOQUES_HORARIOS[pref_vta]
                    vta_ok = (s_vta <= h_vta < e_vta) if s_vta < e_vta else (h_vta >= s_vta or h_vta < e_vta)
                    if ida_ok and vta_ok: v_filtrados.append(v)

                v_finales = v_filtrados if v_filtrados else v_base
                if not v_filtrados: st.warning("⚠️ Sin vuelos exactos para tu horario. Mostrando otras opciones:")

                if v_finales and 'semaforo_vuelo' not in st.session_state:
                    mejor_p = float(v_finales[0]['price']['total']) / num_viajeros
                    st.session_state.semaforo_vuelo = preguntar_ia_seguro(f"Vuelo a {st.session_state.iata_destino} por {mejor_p:.2f}€/pax. Responde: 🟢 Chollo, 🟡 Normal o 🔴 Caro.")
                if 'semaforo_vuelo' in st.session_state: st.info(f"**Semáforo IA:** {st.session_state.semaforo_vuelo}")

                for v in v_finales[:10]:
                    precio_t = float(v['price']['total'])
                    carrier = v['validatingAirlineCodes'][0]
                    nombre_a = carriers.get(carrier, carrier)
                    it_i, it_v = v['itineraries'][0]['segments'], v['itineraries'][1]['segments']
                    o_iata, d_iata = it_i[0]['departure']['iataCode'], it_i[-1]['arrival']['iataCode']
                    try: bags = v['travelerPricings'][0]['fareDetailsBySegment'][0].get('includedCheckedBags', {}).get('quantity', 0)
                    except: bags = 0

                    with st.expander(f"💰 {precio_t:.2f}€ Total ({precio_t/num_viajeros:.2f}€/pax) | {nombre_a}"):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.write(f"🛫 **Ida:** {it_i[0]['departure']['at'][11:16]} ({o_iata})")
                            st.write(f"🛬 **Vta:** {it_v[0]['departure']['at'][11:16]} ({it_v[0]['departure']['iataCode']})")
                        with c2:
                            st.write(f"🎒 Mano: {'✅' if bags > 0 or carrier not in ['FR', 'VY', 'U2', 'W6'] else '❌'}")
                            st.write(f"🧳 Facturada: {'✅' if bags > 0 else '❌'} ({bags})")
                        with c3:
                            st.markdown(f"[🛒 Buscar en Google Flights](https://www.google.es/travel/flights?q=Flights%20from%20{st.session_state.iata_origen}%20to%20{st.session_state.iata_destino})")
            else: 
                st.error("❌ No hay vuelos para esas fechas exactas en Amadeus. Prueba a cambiar el día.")
        else:
            st.success("🚙 Es más inteligente ir por tierra al primer destino. Vuelos desactivados.")

    with col_h:
        st.subheader("🏨 Conserje de Alojamiento")
        h_ubicacion = st.radio("Ubicación:", ["📍 Centro", "🚶 Zona Intermedia", "🚇 Periferia"], horizontal=True)
        if st.button("🗺️ Recomendar Barrios"):
            prompt_b = f"3 zonas en {c_dest} para {grupo_texto}. Zonas tipo '{h_ubicacion}'." if tipo_viaje == "🏙️ Ciudad Única" else f"Para la ruta '{c_dest}', dime 1 zona ideal (tipo '{h_ubicacion}') en CADA parada para {grupo_texto}."
            st.session_state.barrios_gen = preguntar_ia_seguro(prompt_b)
            
        if 'barrios_gen' in st.session_state: st.info(st.session_state.barrios_gen)

        st.markdown("---")
        c_h1, c_h2 = st.columns(2)
        with c_h1: h_tipo = st.selectbox("Tipo:", ["Hotel", "Apartamento", "Hostal"])
        with c_h2: h_presupuesto = st.slider("Presupuesto Max/noche (€):", 50, 1000, 150)
        h_barrio_manual = st.text_input("Barrio específico (Opcional):")

        if st.button("🪄 Buscar Alojamientos Ideales"):
            zona_texto = f"en el barrio de {h_barrio_manual}" if h_barrio_manual else f"en la zona {h_ubicacion}"
            prompt_hoteles = f"Conserje para {c_dest}. Busco {h_tipo} {zona_texto} para {grupo_texto}. Plan {estilo_viaje}. Presupuesto max {h_presupuesto}€. Dame opciones reales."
            st.session_state.hoteles_gen = preguntar_ia_seguro(prompt_hoteles)
        
        if 'hoteles_gen' in st.session_state:
            st.markdown(st.session_state.hoteles_gen)
            ciudades_rutas = [c_dest] if tipo_viaje == "🏙️ Ciudad Única" else [c.strip() for c in c_dest.split(',')]
            for ciud in ciudades_rutas:
                termino = f"{h_barrio_manual} {ciud}" if h_barrio_manual else f"{h_ubicacion.replace('📍', '').replace('🚶', '').replace('🚇', '').strip()} {ciud}"
                dest_url = urllib.parse.quote(termino)
                with st.expander(f"🛒 Ver opciones en {ciud}"):
                    c_b1, c_b2, c_b3 = st.columns(3)
                    c_b1.markdown(f'<a href="https://www.booking.com/searchresults.html?ss={dest_url}" target="_blank"><button style="width:100%; background-color:#003580; color:white; border:none; padding:8px; border-radius:5px;">Booking</button></a>', unsafe_allow_html=True)
                    c_b2.markdown(f'<a href="https://www.airbnb.es/s/{dest_url}/homes" target="_blank"><button style="width:100%; background-color:#FF5A5F; color:white; border:none; padding:8px; border-radius:5px;">Airbnb</button></a>', unsafe_allow_html=True)
                    c_b3.markdown(f'<a href="https://es.hotels.com/Hotel-Search?destination={dest_url}" target="_blank"><button style="width:100%; background-color:#D32F2F; color:white; border:none; padding:8px; border-radius:5px;">Hotels</button></a>', unsafe_allow_html=True)

    # --- EXTRAS: MAPA Y GUÍA ---
    st.divider()
    cm, cg = st.columns([0.4, 0.6])
    with cm:
        st.subheader(f"📍 Radar Turístico de {ciudad_1}")
        if st.button("🌍 Cargar Radar Inteligente"):
            prompt_mapa = f"Identifica 15-20 puntos imperdibles de {ciudad_1}. Clasifica en 'monumento', 'naturaleza' o 'cultura'. Devuelve SOLO JSON: [{{'nombre':'...','lat':0.0,'lon':0.0,'tipo':'monumento'}}]"
            res_m = preguntar_ia_seguro(prompt_mapa)
            try:
                match = re.search(r'\[.*\]', res_m, re.DOTALL)
                if match:
                    pts = json.loads(match.group())
                    for p in pts:
                        t = p.get('tipo', '')
                        if t == 'naturaleza': p['color'] = [50, 200, 50, 200]
                        elif t == 'cultura': p['color'] = [50, 100, 255, 200]
                        else: p['color'] = [255, 75, 75, 200]
                    st.session_state.mapa_gen = pts
                else:
                    st.error("⚠️ La IA no devolvió las coordenadas correctamente. Reintenta.")
            except Exception as e:
                st.error("❌ Error procesando el mapa. Por favor, reintenta.")

        if 'mapa_gen' in st.session_state and isinstance(st.session_state.mapa_gen, list):
            pts = st.session_state.mapa_gen
            if pts: # Asegurarnos de que la lista no esté vacía
                lat_c = sum(p['lat'] for p in pts)/len(pts)
                lon_c = sum(p['lon'] for p in pts)/len(pts)
                st.markdown("🔴 *Monumentos* | 🟢 *Naturaleza* | 🔵 *Cultura*")
                st.pydeck_chart(pdk.Deck(initial_view_state=pdk.ViewState(latitude=lat_c, longitude=lon_c, zoom=12, pitch=45),
                    layers=[pdk.Layer("ScatterplotLayer", data=pts, get_position=["lon", "lat"], get_fill_color="color", get_radius=180, pickable=True)], tooltip={"text": "{nombre}"}))
    with cg:
        st.subheader("👑 Guía Maestra de Viaje")
        if st.button("📝 Generar Itinerario y Logística"):
            with st.spinner("Construyendo guía..."):
                mes_n = MESES_FULL[f_ida.month-1][1]
                
                p1_c = f"Guía de {c_dest}. {num_dias} días para {grupo_texto}. Plan: {estilo_viaje}." if tipo_viaje == "🏙️ Ciudad Única" else f"Roadtrip por: {c_dest}. Transporte: {pref_trans}. Ritmo: {ritmo_ruta}."
                p1 = p1_c + """ Usa Markdown. Añade Google Maps.
                🌟 Desvíos Genius: Recomienda joya oculta cercana a la ruta.
                🎧 Playlist de Carretera: 3 canciones.
                🍽️ Restaurantes Top (Económicos, Calidad-Precio, Premium).
                🎬 Cultura Pop y Trampas para Turistas."""
                st.session_state.guia_p1 = preguntar_ia_seguro(p1)
                
                p2 = f"Logística para {c_dest} en {mes_n}. Movilidad, estimación de gasolina/peajes (si es coche), clima, presupuesto y manual de supervivencia (enchufes, farmacias)."
                st.session_state.guia_p2 = preguntar_ia_seguro(p2)
                
                p3 = f"Maleta 10 objetos para {c_dest} en {mes_n}. SOLO array JSON de strings."
                res_maleta = preguntar_ia_seguro(p3)
                try: st.session_state.guia_p3 = json.loads(re.search(r'\[.*\]', res_maleta, re.DOTALL).group())
                except: st.session_state.guia_p3 = ["Pasaporte", "Cargador", "Ropa cómoda"]

        # SEGURO DE VIDA PARA TABS
        if 'guia_p1' in st.session_state and 'guia_p2' in st.session_state:
            tab1, tab2, tab3 = st.tabs(["🗺️ Itinerario & Secretos", "🚇 Logística & Supervivencia", "🎒 Maleta"])
            with tab1: st.markdown(st.session_state.guia_p1)
            with tab2: st.markdown(st.session_state.guia_p2)
            with tab3:
                for item in st.session_state.guia_p3: st.checkbox(item, key=item)
            
            st.divider()
            texto_descarga = st.session_state.guia_p1 + "\n\n---\n\n" + st.session_state.guia_p2
            st.download_button("⬇️ Descargar Guía Escrita", texto_descarga, f"Guia_{ciudad_1.replace(' ', '_')}.md", type="primary")