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

    # Inicializar estado si no existe
    if "ruta_datos" not in st.session_state:
        st.session_state.ruta_datos = None
        st.session_state.mapa_guardado = None

    # Formulario
    with st.form("plan_ruta"):
        col1, col2 = st.columns(2)
        with col1:
            origen_txt = st.text_input("Origen", key="origen_input")
        with col2:
            destino_txt = st.text_input("Destino", key="destino_input")
        submit = st.form_submit_button("Calcular ruta")

    # Función auxiliar: geolocalizar dirección
    def geolocalizar(direccion):
        params = {
            "q": direccion + ", Valencia, España",
            "format": "json",
            "countrycodes": "es",
            "limit": 1
        }
        r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers={"User-Agent": "valenbisi-app"})
        if r.status_code != 200 or not r.json():
            return None
        p = r.json()[0]
        return float(p["lat"]), float(p["lon"])

    # Función: generar mapa
    def generar_mapa_con_ruta(data):
        coords = [
            (data["lon_ori"], data["lat_ori"]),
            (data["lon_coger"], data["lat_coger"]),
            (data["lon_dejar"], data["lat_dejar"]),
            (data["lon_dest"], data["lat_dest"])
        ]

        cliente = openrouteservice.Client(key="5b3ce3597851110001cf62481ad5ef9841524536bfdf7b57c64ba51e")
        ruta = cliente.directions(coords, profile="cycling-regular", format="geojson")

        mapa = folium.Map(location=[data["lat_ori"], data["lon_ori"]], zoom_start=13)
        folium.Marker([data["lat_ori"], data["lon_ori"]], tooltip="Inicio", icon=folium.Icon(color="green")).add_to(mapa)
        folium.Marker([data["lat_dest"], data["lon_dest"]], tooltip="Destino", icon=folium.Icon(color="red")).add_to(mapa)
        folium.Marker([data["lat_coger"], data["lon_coger"]], tooltip="Estación origen", icon=folium.Icon(color="blue")).add_to(mapa)
        folium.Marker([data["lat_dejar"], data["lon_dejar"]], tooltip="Estación destino", icon=folium.Icon(color="purple")).add_to(mapa)

        puntos_ruta = [[lat, lon] for lon, lat in ruta["features"][0]["geometry"]["coordinates"]]
        folium.PolyLine(locations=puntos_ruta, color="blue", weight=5, opacity=0.8).add_to(mapa)
        return mapa

    # Si se pulsa el botón, calcular la ruta y guardar mapa
    if submit:
        ori_coords = geolocalizar(origen_txt)
        dest_coords = geolocalizar(destino_txt)
        if not ori_coords or not dest_coords:
            st.error("Direcciones no encontradas.")
        else:
            lat_ori, lon_ori = ori_coords
            lat_dest, lon_dest = dest_coords

            est_origen = df[df["Bicis_disponibles"] > 0].copy()
            est_origen["dist"] = est_origen.apply(lambda row: geodesic((lat_ori, lon_ori), (row["latitud"], row["longitud"])).km, axis=1)
            est_coger = est_origen.sort_values("dist").iloc[0]

            est_dest = df[df["Espacios_libres"] > 0].copy()
            est_dest["dist"] = est_dest.apply(lambda row: geodesic((lat_dest, lon_dest), (row["latitud"], row["longitud"])).km, axis=1)
            est_dejar = est_dest.sort_values("dist").iloc[0]

            datos = {
                "lat_ori": lat_ori, "lon_ori": lon_ori,
                "lat_dest": lat_dest, "lon_dest": lon_dest,
                "lat_coger": est_coger["latitud"], "lon_coger": est_coger["longitud"],
                "lat_dejar": est_dejar["latitud"], "lon_dejar": est_dejar["longitud"],
                "dir_coger": est_coger["Direccion"],
                "dir_dejar": est_dejar["Direccion"],
                "dist_ori": est_coger["dist"],
                "dist_dest": est_dejar["dist"]
            }
            st.session_state.ruta_datos = datos
            st.session_state.mapa_guardado = generar_mapa_con_ruta(datos)

    # Mostrar resultado guardado
    if st.session_state.ruta_datos and st.session_state.mapa_guardado:
        datos = st.session_state.ruta_datos
        st.success("✅ Ruta calculada correctamente")
        st.markdown(f"""
        - 🚲 **Coge la bici en:** {datos['dir_coger']} _(a {datos['dist_ori']:.2f} km)_
        - 📍 **Déjala en:** {datos['dir_dejar']} _(a {datos['dist_dest']:.2f} km)_
        """)
        st_folium(st.session_state.mapa_guardado, width=1000, height=600)