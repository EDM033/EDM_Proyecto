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
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
import joblib
from datetime import datetime

# --- Configuración inicial
st.set_page_config(layout="wide")
st.title("Valenbisi Valencia - Estaciones y Disponibilidad")

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

# --- Cargar datos
df = cargar_datos_api()

# --- Simulación de predicción
df["Prediccion_1h"] = (df["Bicis_disponibles"] * 0.95).astype(int)
df["Prediccion_libres_1h"] = (df["Espacios_libres"] * 0.95).astype(int)
df["Diferencia"] = df["Prediccion_1h"] - df["Bicis_disponibles"]
df["Ocupacion_%"] = (df["Bicis_disponibles"] / df["Espacios_totales"]) * 100

# --- Sidebar de filtros
st.sidebar.header("Filtros")
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
tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Mapa Interactivo", "📊 Top Estaciones", "📈 Análisis Avanzado", "🚴 Planificar Ruta"])

# --- TAB 1: MAPA
with tab1:
    st.subheader("Mapa interactivo de estaciones Valenbisi")
    st.markdown(f"Se muestran **{len(df_filtrado)}** estaciones con al menos **{min_bicis}** bicis y **{min_huecos}** huecos libres.")

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
        st.markdown("⭐ **Tus estaciones favoritas:**")
        df_fav = df[df["Direccion"].isin(favoritas)]
        st.dataframe(df_fav[["Direccion", "Bicis_disponibles", "Espacios_libres", "Espacios_totales"]])

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
    st.subheader("Predicción de bicicletas disponibles en 1 hora (simulada)")
    estaciones_criticas = df[df["Prediccion_1h"] <= 0]
    if not estaciones_criticas.empty:
        st.warning(f"⚠️ {len(estaciones_criticas)} estaciones podrían quedarse sin bicis en 1 hora:")
        st.dataframe(estaciones_criticas[["Direccion", "Bicis_disponibles", "Prediccion_1h"]])

    st.markdown("**Top 5 estaciones con mayor caída estimada:**")
    top_caida = df.sort_values(by="Diferencia").head(5)
    st.dataframe(top_caida[["Direccion", "Bicis_disponibles", "Prediccion_1h", "Diferencia"]])

    st.divider()

    # --- Ranking por eficiencia
    st.subheader("Estaciones con mayor porcentaje de ocupación")
    df_ranking = df.sort_values(by="Ocupacion_%", ascending=False).reset_index(drop=True)
    st.dataframe(df_ranking[["Direccion", "Bicis_disponibles", "Espacios_totales", "Ocupacion_%"]].head(10))
    
    
with tab4:
    st.subheader("🧭 Planificar trayecto por dirección")

    if "ruta_resultado" not in st.session_state:
        st.session_state.ruta_resultado = None

    if "mapa_ruta" not in st.session_state:
        st.session_state.mapa_ruta = None

    def dentro_de_valencia(lat, lon):
        return 39.40 <= lat <= 39.55 and -0.50 <= lon <= -0.30

    def geolocalizar_valencia(direccion_usuario):
        direccion_usuario = direccion_usuario.strip().replace("Av.", "Avenida").replace("Avda.", "Avenida")
        params = {
            "street": direccion_usuario,
            "city": "Valencia",
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
                resultados.append({"lat": lat, "lon": lon, "score": score, "display_name": r["display_name"]})

        return sorted(resultados, key=lambda x: -x["score"])[:5]

    def mostrar_ruta_en_mapa(data):
        mapa = folium.Map(location=[data["lat_ori"], data["lon_ori"]], zoom_start=13)
        puntos = [
            (data["lat_ori"], data["lon_ori"], "Tu ubicación", "green", "home"),
            (data["est_coger"]["latitud"], data["est_coger"]["longitud"], "Estación para coger bici", "blue", "bicycle"),
            (data["est_dejar"]["latitud"], data["est_dejar"]["longitud"], "Estación para dejar bici", "purple", "anchor"),
            (data["lat_dest"], data["lon_dest"], "Tu destino", "red", "flag")
        ]
        for lat, lon, tip, color, icon in puntos:
            folium.Marker([lat, lon], tooltip=tip, icon=folium.Icon(color=color, icon=icon, prefix="fa")).add_to(mapa)

        try:
            client = openrouteservice.Client(key="5b3ce3597851110001cf62481ad5ef9841524536bfdf7b57c64ba51e")
            coords = [
                (data["lon_ori"], data["lat_ori"]),
                (data["est_coger"]["longitud"], data["est_coger"]["latitud"]),
                (data["est_dejar"]["longitud"], data["est_dejar"]["latitud"]),
                (data["lon_dest"], data["lat_dest"])
            ]
            for perfil in ['cycling-regular', 'foot-walking', 'driving-car']:
                try:
                    ruta = client.directions(coords, profile=perfil, format='geojson')
                    if ruta.get("features"):
                        coords_ruta = ruta["features"][0]["geometry"]["coordinates"]
                        folium.PolyLine(
                            locations=[[lat, lon] for lon, lat in coords_ruta],
                            color="blue", weight=4, opacity=0.8
                        ).add_to(mapa)
                        mapa.fit_bounds([[lat, lon] for lon, lat in coords_ruta])
                        break
                except Exception:
                    continue
        except Exception as e:
            st.warning(f"Error al calcular la ruta: {e}")

        return mapa

    with st.form("planificador_ruta"):
        col1, col2 = st.columns(2)
        with col1:
            direccion_origen = st.text_input("Dirección de salida", placeholder="Ej: Calle Chile 4", key="origen")
        with col2:
            direccion_destino = st.text_input("Dirección de destino", placeholder="Ej: Calle Colón 20", key="destino")
        submitted = st.form_submit_button("Calcular ruta")

    if submitted:
        origen = geolocalizar_valencia(direccion_origen)
        destino = geolocalizar_valencia(direccion_destino)
        if not origen or not destino:
            st.error("❌ No se han encontrado coordenadas válidas.")
        else:
            lat_ori, lon_ori = origen[0]["lat"], origen[0]["lon"]
            lat_dest, lon_dest = destino[0]["lat"], destino[0]["lon"]
            df_bicis = df[df["Bicis_disponibles"] > 0].copy()
            df_bicis["Distancia_origen"] = df_bicis.apply(
                lambda r: geodesic((lat_ori, lon_ori), (r["latitud"], r["longitud"])).km, axis=1
            )
            est_coger = df_bicis.sort_values(by="Distancia_origen").iloc[0]
            df_huecos = df[df["Espacios_libres"] > 0].copy()
            df_huecos["Distancia_destino"] = df_huecos.apply(
                lambda r: geodesic((lat_dest, lon_dest), (r["latitud"], r["longitud"])).km, axis=1
            )
            est_dejar = df_huecos.sort_values(by="Distancia_destino").iloc[0]
            st.session_state.ruta_resultado = {
                "lat_ori": lat_ori, "lon_ori": lon_ori,
                "lat_dest": lat_dest, "lon_dest": lon_dest,
                "est_coger": est_coger, "est_dejar": est_dejar
            }
            st.session_state.mapa_ruta = mostrar_ruta_en_mapa(st.session_state.ruta_resultado)

    if st.session_state.ruta_resultado and st.session_state.mapa_ruta:
        data = st.session_state.ruta_resultado
        st.success("✅ Ruta calculada correctamente")
        st.markdown(f"""
        - 🚲 **Coge la bici en:** {data['est_coger']['Direccion']}  
        _(a {data['est_coger']['Distancia_origen']:.2f} km del origen)_

        - 📍 **Déjala en:** {data['est_dejar']['Direccion']}  
        _(a {data['est_dejar']['Distancia_destino']:.2f} km del destino)_
        """)
        st_folium(st.session_state.mapa_ruta, width=1000, height=600)

# --- Cargar histórico y modelo
df_hist = pd.read_csv("valenbisi-2022-alquileres-y-devoluciones.csv")
modelo_bicis = joblib.load("modelo_bicis.joblib")

# --- Crear codificación de estación
codigos_estacion = {nombre: i for i, nombre in enumerate(df_hist["station_name"].unique())}

# --- Función de predicción del modelo para una estación
def predecir_bicis(estacion_nombre):
    ahora = datetime.now()
    hora = ahora.hour
    dia = ahora.weekday()
    codigo_est = codigos_estacion.get(estacion_nombre, -1)
    if codigo_est == -1:
        return None
    X_pred = pd.DataFrame([[codigo_est, hora, dia]], columns=["estacion", "hora", "dia_semana"])
    return int(modelo_bicis.predict(X_pred)[0])

# --- Aplicar predicción al dataframe actual
df["Prediccion_modelo"] = df["Direccion"].apply(lambda nombre: predecir_bicis(nombre))