import streamlit as st
import pandas as pd
import requests
import folium
from folium.plugins import MarkerCluster, HeatMap
import plotly.express as px
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import openrouteservice
from fuzzywuzzy import fuzz
import urllib.parse
import joblib
from datetime import datetime

# --- Configuración inicial
st.set_page_config(layout="wide")

# --- Inicializar EcoPuntos
if "eco_puntos_totales" not in st.session_state:
    st.session_state.eco_puntos_totales = 0


# --- Viewbox que delimita Valencia ciudad
VALENCIA_VIEWBOX = [(-0.41, 39.43), (-0.33, 39.52)]  # Coordenadas que engloban toda València ciudad


# --- Función para cargar datos desde la API
@st.cache_data(ttl=300)
def cargar_datos_api():
    url = "https://valencia.opendatasoft.com/api/explore/v2.1/catalog/datasets/valenbisi-disponibilitat-valenbisi-dsiponibilidad/records?limit=50"
    r = requests.get(url)
    if r.status_code != 200:
        st.error(f"Error al obtener datos de la API. Código: {r.status_code}")
        st.stop()

    try:
        data = r.json()["results"]
    except KeyError:
        st.error("La respuesta de la API no contiene la clave 'results':")
        st.json(r.json())
        st.stop()

    df = pd.json_normalize(data)
    df["latitud"] = df["geo_point_2d.lat"]
    df["longitud"] = df["geo_point_2d.lon"]

    df = df.rename(columns={
        "address": "Direccion",
        "available": "Bicis_disponibles",
        "free": "Espacios_libres",
        "total": "Espacios_totales",
        "updated_at": "Fecha"
    })

    return df

# --- Clima actual en Valencia desde wttr.in (sin API key)
def obtener_clima_wttr():
    try:
        url = "https://wttr.in/Valencia?format=3"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.text
        else:
            return "No disponible."
    except:
        return "Error al obtener el clima."


# --- Cargar datos
df = cargar_datos_api()

# --- Título principal fijo
st.markdown("<h1 style='text-align: left;'>EcoBici Valencia: Tu guía inteligente para moverte mejor</h1>", unsafe_allow_html=True)


# Cargar modelo entrenado y columnas
modelo = joblib.load("modelo_valenbisi.pkl")
columnas_modelo = joblib.load("columnas_features.pkl")

def predecir_bicis_disponibles(df_actual):
    ahora = datetime.now()
    hora = ahora.hour
    dia = ahora.weekday()

    df_pred = df_actual.copy()
    df_pred["hora"] = hora
    df_pred["dia"] = dia

    # One-hot de dirección como en entrenamiento
    df_pred = pd.get_dummies(df_pred, columns=["Direccion"])
    
    # Asegurar que están todas las columnas del entrenamiento
    for col in columnas_modelo:
        if col not in df_pred.columns:
            df_pred[col] = 0
    df_pred = df_pred[columnas_modelo]

    predicciones = modelo.predict(df_pred)
    return predicciones


# --- Predicción real usando el modelo
df_features = df[["Direccion", "Bicis_disponibles", "Espacios_libres", "Espacios_totales"]].copy()
df["Prediccion_1h"] = predecir_bicis_disponibles(df_features).astype(int)
df["Prediccion_libres_1h"] = df["Espacios_totales"] - df["Prediccion_1h"]

df["Diferencia"] = df["Prediccion_1h"] - df["Bicis_disponibles"]
df["Ocupacion_%"] = (df["Bicis_disponibles"] / df["Espacios_totales"]) * 100



# --- Página inicial con info, simulación e interacción ciudadana
st.markdown(
    """
    Imagina el impacto si más gente usara la bici cada día. Aquí puedes ver simulaciones, problemas en la red y proponer mejoras.
    """
)

# 1. SIMULACIÓN DE IMPACTO COLECTIVO
with st.expander("💥 ¿Y si más gente usara Valenbisi?"):    
    personas = st.slider("¿Cuántas personas lo usarían?", min_value=100, max_value=10000, step=100, value=1000)
    km_por_persona = st.slider("¿Cuántos km por persona al día?", 1, 20, value=5)

    co2_total = personas * km_por_persona * 0.21 / 1000  # en toneladas
    gasolina_total = personas * km_por_persona * 0.06  # en litros

    st.success(f"🌍 Se evitarían {co2_total:.2f} toneladas de CO₂ al día y se ahorrarían {gasolina_total:.0f} litros de gasolina.")

# 3. SUGERENCIAS CIUDADANAS
with st.expander("💬 ¿Tienes alguna sugerencia para mejorar Valenbisi?"):
    sugerencia = st.text_area("Propuesta para nuevas estaciones, mejoras o ideas")
    if st.button("Enviar sugerencia"):
        # Aquí podrías guardarlo en un CSV, base de datos o email
        st.success("¡Gracias por tu aporte!")

# --- Sidebar de filtros
st.sidebar.header("Filtros")

# Clima en el sidebar
st.sidebar.markdown("### ☁ Clima actual")
st.sidebar.info(obtener_clima_wttr())

min_bicis = st.sidebar.slider("Mínimo de bicicletas disponibles", 0, 30, 5)
min_huecos = st.sidebar.slider("Mínimo de anclajes libres", 0, 30, 0)

criterio_color = st.sidebar.selectbox(
    "Colorear puntos según:",
    ["Bicis disponibles", "Huecos libres"]
)

df_filtrado = df[
    (df["Bicis_disponibles"] >= min_bicis) &
    (df["Espacios_libres"] >= min_huecos)
]

st.sidebar.markdown("---")
favoritas = st.sidebar.multiselect(
    "Elige tus estaciones favoritas",
    options=df["Direccion"].unique().tolist(),
    help="Selecciona 1 a 3 estaciones que quieras seguir de cerca"
)


# --- PESTAÑAS PRINCIPALES
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🗺 Mapa Interactivo", 
    "📊 Top Estaciones", 
    "📈 Análisis Avanzado", 
    "🚴 Planificar Ruta",
    "🏅 EcoPuntos"
])

# --- TAB 1: MAPA
with tab1:
    st.subheader("Mapa interactivo de estaciones Valenbisi")
    st.markdown(f"Se muestran {len(df_filtrado)} estaciones con al menos {min_bicis} bicis y {min_huecos} huecos libres.")

    m = folium.Map(location=[39.47, -0.38], zoom_start=13)
    cluster = MarkerCluster().add_to(m)

    for _, row in df_filtrado.iterrows():
        if criterio_color == "Bicis disponibles":
            porcentaje = row["Bicis_disponibles"] / row["Espacios_totales"] * 100
        else:
            porcentaje = row["Espacios_libres"] / row["Espacios_totales"] * 100

        if criterio_color == "Bicis disponibles":
            if row["Bicis_disponibles"] <= 3:
                color = "red"
            elif row["Bicis_disponibles"] / row["Espacios_totales"] < 0.4:
                color = "orange"
            else:
                color = "green"
        else:
            if row["Espacios_libres"] <= 3:
                color = "red"
            elif row["Espacios_libres"] / row["Espacios_totales"] < 0.4:
                color = "orange"
            else:
                color = "green"


        popup_html = f"""
        <b>{row['Direccion']}</b><br>
        Bicis disponibles: {row['Bicis_disponibles']}<br>
        Anclajes libres: {row['Espacios_libres']}<br>
        Total anclajes: {row['Espacios_totales']}<br>
        Última actualización: {row['Fecha']}<br>
        Predicción (1h): {row['Prediccion_1h']}
        """
        folium.CircleMarker(
            location=[row["latitud"], row["longitud"]],
            radius=8,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=popup_html
        ).add_to(cluster)

    # Marcar estaciones favoritas
    if favoritas:
        df_fav = df[df["Direccion"].isin(favoritas)]
        for _, row in df_fav.iterrows():
            popup = f"⭐ <b>{row['Direccion']}</b><br>🚲 {row['Bicis_disponibles']} bicis"
            folium.Marker(
                location=[row["latitud"], row["longitud"]],
                popup=popup,
                icon=folium.Icon(color="darkblue", icon="star", prefix="fa")
            ).add_to(m)

    leyenda_titulo = f"Leyenda - {criterio_color}"
    legend_html = f"""
    <div style='position: fixed; 
         bottom: 40px; left: 40px; width: 260px; height: 140px; 
         background-color: white; z-index:9999; font-size:14px;
         border:2px solid grey; border-radius:10px; padding: 10px; box-shadow: 2px 2px 6px rgba(0,0,0,0.2);'>
    <b>{leyenda_titulo}</b><br>
    🟥 Rojo: 3 o menos disponibles<br>
    🟧 Naranja: menos del 40% del total<br>
    🟩 Verde: 40% o más disponibles<br>
    </div>
    """

    m.get_root().html.add_child(folium.Element(legend_html))


    st_folium(m, width=1000, height=600)
    

    
# --- TAB 2: TOP ESTACIONES
with tab2:
    st.subheader("Estaciones con más bicicletas disponibles")
    df_top = df.sort_values(by="Bicis_disponibles", ascending=False).reset_index(drop=True)
    st.dataframe(df_top[["Direccion", "Bicis_disponibles", "Espacios_libres", "Espacios_totales"]].head(10))

    if favoritas:
        st.markdown("⭐ Tus estaciones favoritas:")
        df_fav = df[df["Direccion"].isin(favoritas)]
        st.dataframe(df_fav[["Direccion", "Bicis_disponibles", "Espacios_libres", "Espacios_totales"]])

    st.subheader("Estaciones con más ocupación")
    top_ocupadas = df.sort_values("Ocupacion_%", ascending=False).head(10)
    fig_ocup = px.bar(top_ocupadas, x="Direccion", y="Ocupacion_%", title="Top 10 estaciones más ocupadas (%)")
    st.plotly_chart(fig_ocup, use_container_width=True)

    # --- Ranking por eficiencia
    st.subheader("Estaciones con mayor porcentaje de ocupación")
    df_ranking = df.sort_values(by="Ocupacion_%", ascending=False).reset_index(drop=True)
    st.dataframe(df_ranking[["Direccion", "Bicis_disponibles", "Espacios_totales", "Ocupacion_%"]].head(10))
    
    st.divider()
    st.subheader("Ocupación media por hora")
    
    df_hist = df.copy()
    df_hist["Hora"] = pd.to_datetime(df_hist["Fecha"]).dt.hour
    graf = df_hist.groupby("Hora")["Bicis_disponibles"].mean().reset_index()
    
    fig = px.line(
        graf,
        x="Hora",
        y="Bicis_disponibles",
        markers=True,
        title="Ocupación media de bicicletas por hora",
        labels={"Hora": "Hora del día", "Bicis_disponibles": "Bicis disponibles (media)"},
    )
    fig.update_layout(xaxis=dict(dtick=1))  # Para que se vean todas las horas
    
    st.plotly_chart(fig, use_container_width=True)

    


# --- TAB 3: ANÁLISIS AVANZADO
with tab3:
    # --- Comparador de estaciones
    st.subheader("Comparador de estaciones")
    
    cols = st.columns(2)
    est1 = cols[0].selectbox("Estación A", df["Direccion"].unique(), key="est1")
    est2 = cols[1].selectbox("Estación B", df["Direccion"].unique(), key="est2")
    
    df_est1 = df[df["Direccion"] == est1].iloc[0]
    df_est2 = df[df["Direccion"] == est2].iloc[0]
    
    # Mostrar tablas comparativas en paralelo
    tabla1 = pd.DataFrame({
        "Actual": [df_est1["Bicis_disponibles"], df_est1["Espacios_libres"]],
        "Predicción 1h": [df_est1["Prediccion_1h"], df_est1["Prediccion_libres_1h"]]
    }, index=["Bicis disponibles", "Huecos disponibles"])
    
    tabla2 = pd.DataFrame({
        "Actual": [df_est2["Bicis_disponibles"], df_est2["Espacios_libres"]],
        "Predicción 1h": [df_est2["Prediccion_1h"], df_est2["Prediccion_libres_1h"]]
    }, index=["Bicis disponibles", "Huecos disponibles"])
    
    cols_tabla = st.columns(2)
    with cols_tabla[0]:
        st.table(tabla1)
    
    with cols_tabla[1]:
        st.table(tabla2)


    # --- Predicción crítica 
    st.subheader("Predicción de bicicletas disponibles en 1 hora")
    estaciones_criticas = df[df["Prediccion_1h"] <= 0]
    if not estaciones_criticas.empty:
        st.warning(f"⚠ {len(estaciones_criticas)} estaciones podrían quedarse sin bicis en 1 hora:")
        st.dataframe(estaciones_criticas[["Direccion", "Bicis_disponibles", "Prediccion_1h"]])

    st.markdown("Top 5 estaciones con mayor caída estimada:")
    top_caida = df.sort_values(by="Diferencia").head(5)
    st.dataframe(top_caida[["Direccion", "Bicis_disponibles", "Prediccion_1h", "Diferencia"]])

    st.divider()

    

    
    
    
with tab4:
    st.subheader("Planificar trayecto por dirección")

    with st.expander("ℹ ¿Cómo se eligen las estaciones para tu ruta?"):
        st.markdown("""
        - Se elige la estación más cercana al origen que tenga bicicletas disponibles.
        - Se elige la más cercana al destino con huecos libres.
        - Además, se considera la predicción de disponibilidad en 1 hora.
        - ⚠ Si hay riesgo de quedarse sin bicis o huecos, se sugiere una alternativa cercana.
        """)

    # Inicializar claves si no existen
    for key in ["direccion_origen", "direccion_destino", "ruta_resultado", "ruta_listo", "mapa_ruta_key", "ultima_ruta_puntuada", "eco_puntos_totales"]:
        if key not in st.session_state:
            st.session_state[key] = "" if "direccion" in key else None if key == "ruta_resultado" else False if key == "ruta_listo" else 0

    # Formulario de entrada
    with st.form("planificador_ruta"):
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.direccion_origen = st.text_input(
                "Dirección de salida",
                value=st.session_state.direccion_origen,
                placeholder="Ej: Calle Chile 4",
                key="origen_input"
            )        

        with col2:
            st.session_state.direccion_destino = st.text_input(
                "Dirección de destino",
                value=st.session_state.direccion_destino,
                placeholder="Ej: Calle Colón 20",
                key="destino_input"
            )
        submitted = st.form_submit_button("Calcular ruta")

    # FUNCIONES AUXILIARES
    def dentro_de_valencia(lat, lon):
        return 39.40 <= lat <= 39.55 and -0.50 <= lon <= -0.30

    def geolocalizar_valencia(direccion_usuario):
        direccion_usuario = direccion_usuario.strip().replace("Av.", "Avenida").replace("Avda.", "Avenida")
        params = {
            "street": direccion_usuario,
            "city": "Valencia",
            "state": "Comunidad Valenciana",
            "country": "España",
            "format": "json",
            "limit": 10,
            "countrycodes": "es",
            "accept-language": "es",
            "viewbox": "-0.41,39.43,-0.33,39.52",
            "bounded": 1,
        }
        headers = {"User-Agent": "valenbisi-edm-app"}
        resp = requests.get("https://nominatim.openstreetmap.org/search", headers=headers, params=params)
        if resp.status_code != 200 or not resp.json():
            return []
        resultados = []
        for r in resp.json():
            lat, lon = float(r["lat"]), float(r["lon"])
            if dentro_de_valencia(lat, lon):
                score = fuzz.partial_ratio(direccion_usuario.lower(), r["display_name"].split(",")[0].lower())
                resultados.append({"lat": lat, "lon": lon, "score": score})
        return sorted(resultados, key=lambda x: -x["score"])[:5]

    def mostrar_ruta_en_mapa(data):
        ruta_map = folium.Map(location=[data["lat_ori"], data["lon_ori"]], zoom_start=13, control_scale=True)
        puntos = [
            (data["lat_ori"], data["lon_ori"], "Tu ubicación", "green", "home"),
            (data["est_coger"]["latitud"], data["est_coger"]["longitud"], "Estación para coger bici", "blue", "bicycle"),
            (data["est_dejar"]["latitud"], data["est_dejar"]["longitud"], "Estación para dejar bici", "purple", "anchor"),
            (data["lat_dest"], data["lon_dest"], "Tu destino", "red", "flag")
        ]
        for lat, lon, tip, color, icono in puntos:
            folium.Marker([lat, lon], tooltip=tip, icon=folium.Icon(color=color, icon=icono, prefix="fa")).add_to(ruta_map)
        try:
            ors_client = openrouteservice.Client(key="5b3ce3597851110001cf62481ad5ef9841524536bfdf7b57c64ba51e", timeout=10)
            coords = [
                (data["lon_ori"], data["lat_ori"]),
                (data["est_coger"]["longitud"], data["est_coger"]["latitud"]),
                (data["est_dejar"]["longitud"], data["est_dejar"]["latitud"]),
                (data["lon_dest"], data["lat_dest"])
            ]
            route = ors_client.directions(coords, profile='cycling-regular', format='geojson')
            folium.GeoJson(route, name="Ruta_en_bici", tooltip="Ruta sugerida").add_to(ruta_map)
            folium.LayerControl(collapsed=False).add_to(ruta_map)
        except Exception as e:
            st.error(f"❌ Error al obtener la ruta: {e}")
        return ruta_map

    # PROCESAMIENTO SI SE ENVÍA EL FORMULARIO
    if submitted:
        origen = geolocalizar_valencia(st.session_state.direccion_origen)
        destino = geolocalizar_valencia(st.session_state.direccion_destino)
        if not origen or not destino:
            st.error("❌ No se han encontrado coordenadas válidas para alguna dirección.")
        else:
            lat_ori, lon_ori = origen[0]["lat"], origen[0]["lon"]
            lat_dest, lon_dest = destino[0]["lat"], destino[0]["lon"]

            df_bicis = df[df["Bicis_disponibles"] > 0].copy()
            df_bicis["Distancia_origen"] = df_bicis.apply(lambda row: geodesic((lat_ori, lon_ori), (row["latitud"], row["longitud"])).km, axis=1)
            est_coger = df_bicis.sort_values("Distancia_origen").iloc[0]

            df_huecos = df[df["Espacios_libres"] > 0].copy()
            df_huecos["Distancia_destino"] = df_huecos.apply(lambda row: geodesic((lat_dest, lon_dest), (row["latitud"], row["longitud"])).km, axis=1)
            est_dejar = df_huecos.sort_values("Distancia_destino").iloc[0]

            st.session_state.ruta_resultado = {
                "lat_ori": lat_ori, "lon_ori": lon_ori,
                "lat_dest": lat_dest, "lon_dest": lon_dest,
                "est_coger": est_coger,
                "est_dejar": est_dejar
            }
            st.session_state.ruta_listo = True

            clave_ruta = f"{lat_ori}{lon_ori}{lat_dest}_{lon_dest}"
            st.session_state.mapa_ruta_key = clave_ruta

            distancia_total_km = est_coger["Distancia_origen"] + est_dejar["Distancia_destino"]
            co2_kg = distancia_total_km * 0.21
            puntos = int(co2_kg * 100)

            if clave_ruta != st.session_state.ultima_ruta_puntuada:
                st.session_state.eco_puntos_totales += puntos
                st.session_state.ultima_ruta_puntuada = clave_ruta
                st.session_state.ecopuntos_ganados = puntos
            else:
                st.session_state.ecopuntos_ganados = 0

            st.session_state.mapa_ruta = mostrar_ruta_en_mapa(st.session_state.ruta_resultado)

    # MOSTRAR RESULTADOS SI HAY RUTA
    if st.session_state.ruta_listo and st.session_state.ruta_resultado:
        data = st.session_state.ruta_resultado
        est_coger = data["est_coger"]
        est_dejar = data["est_dejar"]

        st.markdown(f"""
        - 🚲 Coge la bici en: {est_coger['Direccion']}  
          (a {est_coger['Distancia_origen']:.2f} km del origen)  
          Bicis ahora: {est_coger['Bicis_disponibles']}  
          Predicción en 1h: {est_coger['Prediccion_1h']}

        - 📍 Déjala en: {est_dejar['Direccion']}  
          (a {est_dejar['Distancia_destino']:.2f} km del destino)  
          Huecos ahora: {est_dejar['Espacios_libres']}  
          Predicción en 1h: {est_dejar['Prediccion_libres_1h']}
        """)

        co2_kg = (est_coger["Distancia_origen"] + est_dejar["Distancia_destino"]) * 0.21
        st.info(f"🌍 Gracias a este trayecto estás evitando aproximadamente {co2_kg:.2f} kg de CO₂.")

        puntos_ganados = st.session_state.get("ecopuntos_ganados", 0)
        if puntos_ganados > 0:
            st.success(f"🌱 Has ganado {puntos_ganados} EcoPuntos con este trayecto.")
        else:
            st.info("ℹ Esta ruta ya ha sido registrada. No se suman más EcoPuntos.")

        st.markdown(f"EcoPuntos acumulados: {st.session_state.eco_puntos_totales}")

        if st.session_state.mapa_ruta:
            st_folium(st.session_state.mapa_ruta, key=st.session_state.mapa_ruta_key, width=1000, height=600)

    
with tab5:
    st.subheader("🏅 Tus EcoPuntos")
    
    puntos = st.session_state.eco_puntos_totales
    co2_total = puntos / 100  # porque 100 puntos = 1 kg CO2

    st.metric("EcoPuntos", value=puntos)
    
    # --- Sistema de niveles por EcoPuntos
    def calcular_nivel(puntos):
        niveles = [
            {"nivel": 1, "min": 0, "max": 499, "nombre": " Principiante"},
            {"nivel": 2, "min": 500, "max": 999, "nombre": " EcoExplorador"},
            {"nivel": 3, "min": 1000, "max": 1999, "nombre": " EcoAvanzado"},
            {"nivel": 4, "min": 2000, "max": 4999, "nombre": " EcoHéroe"},
            {"nivel": 5, "min": 5000, "max": float("inf"), "nombre": "Leyenda Sostenible"},
        ]
        for n in niveles:
            if n["min"] <= puntos <= n["max"]:
                progreso = (puntos - n["min"]) / (n["max"] - n["min"])
                return n["nivel"], n["nombre"], progreso, n["max"]
        return 1, "🌱 Principiante", 0, 500
    
    nivel_actual, nombre_nivel, progreso_nivel, puntos_max = calcular_nivel(puntos)
    
    st.markdown(f"### Nivel actual: {nombre_nivel}")
    st.progress(progreso_nivel, text=f"{puntos}/{puntos_max} EcoPuntos")

    
    st.markdown(f"""
    - Has evitado {co2_total:.2f} kg de CO₂ con tus trayectos.
    - Eso equivale a:
        - 🌳 {co2_total / 21:.2f} árboles absorbiendo CO₂ un día.
        - 🚗 {co2_total / 0.21:.1f} km que no se han hecho en coche.
    """)

    st.divider()
    
    # --- Reto semanal
    RETO_OBJETIVO_CO2 = 2.0  # en kg
    progreso_reto = min(co2_total / RETO_OBJETIVO_CO2, 1.0)
    
    st.markdown("### 🏆 Reto semanal: Evita 2 kg de CO₂")
    st.progress(progreso_reto, text=f"{co2_total:.2f} / {RETO_OBJETIVO_CO2} kg de CO₂ evitado")

    
    with st.expander("ℹ ¿Qué son los EcoPuntos?"):
        st.markdown("""
        Los EcoPuntos son una forma divertida de mostrar el impacto ambiental positivo que generas usando Valenbisi.

        - Cada vez que evitas usar el coche, ganas puntos.
        - Por cada 0.01 kg de CO₂ evitado, ganas 1 EcoPunto.
        - Puedes ver tu impacto total en esta pestaña.

         ¡Gracias por moverte de forma sostenible!
        """)