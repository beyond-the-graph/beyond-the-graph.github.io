import folium
import os
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AQI Geospatial Explorer",
    page_icon="🌍",
    layout="wide"
)

pio.renderers.default = "browser"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ["NEO4J_DATABASE"]
CARTO_API_KEY  = os.environ["CARTO_API_KEY"]

MAP_TILES = (
    f"https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png"
    f"?key={CARTO_API_KEY}"
)
MAP_ATTR = (
    "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>, "
    "&copy; <a href='https://carto.com/attributions'>CARTO</a>"
)

AQI_COLORS = {
    "Good":                           "#00E400",
    "Moderate":                       "#FFFF00",
    "Unhealthy for Sensitive Groups": "#FF7E00",
    "Unhealthy":                      "#FF0000",
    "Very Unhealthy":                 "#8F3F97",
    "Hazardous":                      "#7E0023",
}

# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()
    return driver

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_cities(_driver):
    with _driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (c:City)-[:HAS_READING]->(r:Reading)
            WITH c, r ORDER BY r.timestamp DESC
            WITH c, collect(r)[0] AS latest
            RETURN c.name               AS city,
                   c.country            AS country,
                   c.location.latitude  AS lat,
                   c.location.longitude AS lon,
                   latest.aqi_us        AS aqi_us,
                   latest.aqi_category  AS aqi_category
            ORDER BY c.name
        """)
        return pd.DataFrame([r.data() for r in result])

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def find_nearby(driver, city, country, radius_km, min_aqi):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (ref:City {name: $city, country: $country})
            MATCH (c:City)-[:HAS_READING]->(r:Reading)
            WITH ref, c, r ORDER BY r.timestamp DESC
            WITH ref, c, collect(r)[0] AS latest
            WHERE c <> ref
              AND point.distance(ref.location, c.location) / 1000 <= $radius_km
              AND latest.aqi_us >= $min_aqi
            RETURN c.name                AS city,
                   c.country             AS country,
                   c.location.latitude   AS lat,
                   c.location.longitude  AS lon,
                   round(point.distance(ref.location, c.location) / 1000, 1) AS distance_km,
                   latest.aqi_us         AS aqi_us,
                   latest.aqi_category   AS aqi_category,
                   latest.main_pollutant AS main_pollutant,
                   latest.temperature    AS temperature,
                   latest.humidity       AS humidity,
                   latest.wind_speed     AS wind_speed
            ORDER BY distance_km
        """, city=city, country=country,
             radius_km=radius_km, min_aqi=min_aqi)
        return pd.DataFrame([r.data() for r in result])


def get_ref_city(driver, city, country):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (c:City {name: $city, country: $country})-[:HAS_READING]->(r:Reading)
            WITH c, r ORDER BY r.timestamp DESC
            WITH c, collect(r)[0] AS latest
            RETURN c.location.latitude   AS lat,
                   c.location.longitude  AS lon,
                   latest.aqi_us         AS aqi_us,
                   latest.aqi_category   AS aqi_category
        """, city=city, country=country)
        return result.single()

# ---------------------------------------------------------------------------
# Map builder
# ---------------------------------------------------------------------------

def build_map(ref_city, ref_country, ref_lat, ref_lon,
              ref_aqi, ref_category, nearby_df, radius_km):

    m = folium.Map(
        location=[ref_lat, ref_lon],
        zoom_start=8,
        tiles=MAP_TILES,
        attr=MAP_ATTR
    )

    # Radius circle
    folium.Circle(
        location=[ref_lat, ref_lon],
        radius=radius_km * 1000,
        color="#636EFA",
        fill=True,
        fill_color="#636EFA",
        fill_opacity=0.05,
        weight=1.5,
        dash_array="6"
    ).add_to(m)

    # Lines to nearby cities
    for _, row in nearby_df.iterrows():
        folium.PolyLine(
            locations=[
                [ref_lat, ref_lon],
                [row["lat"], row["lon"]]
            ],
            color=AQI_COLORS.get(row["aqi_category"], "#888888"),
            weight=1.5,
            opacity=0.5,
            tooltip=f"{row['city']}: {row['distance_km']} km"
        ).add_to(m)

    # Nearby city markers
    for _, row in nearby_df.iterrows():
        color = AQI_COLORS.get(row["aqi_category"], "#888888")
        popup = (
            f"<b>{row['city']}, {row['country']}</b><br>"
            f"AQI: {row['aqi_us']} ({row['aqi_category']})<br>"
            f"Distance: {row['distance_km']} km<br>"
            f"Main pollutant: {row['main_pollutant']}<br>"
            f"Temperature: {row['temperature']}°C<br>"
            f"Humidity: {row['humidity']}%<br>"
            f"Wind: {row['wind_speed']} m/s"
        )
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=8,
            color="white",
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=f"{row['city']}: AQI {row['aqi_us']}",
            popup=folium.Popup(popup, max_width=250)
        ).add_to(m)

    # Reference city marker
    ref_color = AQI_COLORS.get(ref_category, "#888888")
    folium.Marker(
        location=[ref_lat, ref_lon],
        tooltip=f"<b>{ref_city}</b> (selected) AQI: {ref_aqi}",
        icon=folium.Icon(color="blue", icon="circle", prefix="fa")
    ).add_to(m)

    # Legend
    legend_items = "".join(
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
        f'background:{color};margin-right:6px;"></span>{label}<br>'
        for label, color in AQI_COLORS.items()
    )
    legend_html = f"""
    <div style="
        position:fixed;bottom:40px;left:40px;z-index:1000;
        background:white;padding:12px 16px;border-radius:8px;
        box-shadow:0 2px 6px rgba(0,0,0,0.3);font-family:sans-serif;
        font-size:13px;line-height:1.8;
    ">
      <b>US AQI</b><br>
      {legend_items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("AQI Geospatial Explorer")
st.caption(
    "Spatial queries on air quality data for the Pyrenees corridor, "
    "powered by Neo4j native point types and point.distance()."
)

driver    = get_driver()
cities_df = load_cities(driver)

# Build city label list for dropdown
cities_df["label"] = cities_df["city"] + ", " + cities_df["country"]
city_labels = sorted(cities_df["label"].tolist())
default_idx = city_labels.index("Barcelona, Spain") if "Barcelona, Spain" in city_labels else 0

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Controls")

    selected_label = st.selectbox("Reference city", city_labels, index=default_idx)
    selected_city    = cities_df[cities_df["label"] == selected_label].iloc[0]
    ref_city         = selected_city["city"]
    ref_country      = selected_city["country"]

    radius_km = st.slider(
        "Radius (km)", min_value=50, max_value=500, value=150, step=25
    )

    min_aqi = st.slider(
        "Minimum AQI", min_value=0, max_value=200, value=0, step=5
    )

    find_btn = st.button("Find nearby cities", type="primary")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

if find_btn:
    with st.spinner("Running spatial query..."):
        ref_row  = get_ref_city(driver, ref_city, ref_country)
        nearby   = find_nearby(driver, ref_city, ref_country, radius_km, min_aqi)

    st.session_state["nearby"]      = nearby
    st.session_state["ref_city"]    = ref_city
    st.session_state["ref_country"] = ref_country
    st.session_state["ref_row"]     = dict(ref_row)
    st.session_state["radius_km"]   = radius_km

if "nearby" in st.session_state:
    nearby      = st.session_state["nearby"]
    ref_city    = st.session_state["ref_city"]
    ref_country = st.session_state["ref_country"]
    ref_row     = st.session_state["ref_row"]
    radius_km   = st.session_state["radius_km"]

    ref_lat      = ref_row["lat"]
    ref_lon      = ref_row["lon"]
    ref_aqi      = ref_row["aqi_us"]
    ref_category = ref_row["aqi_category"]

    # Summary metrics
    st.markdown(f"### {ref_city}, {ref_country}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Reference AQI", ref_aqi)
    col2.metric("Nearby cities", len(nearby))

    if not nearby.empty:
        col3.metric("Average AQI nearby", round(nearby["aqi_us"].mean(), 1))
        worst = nearby.loc[nearby["aqi_us"].idxmax()]
        col4.metric("Highest AQI nearby", worst["aqi_us"], delta=worst["city"], delta_color="off")

        # Map
        m = build_map(
            ref_city, ref_country, ref_lat, ref_lon,
            ref_aqi, ref_category, nearby, radius_km
        )
        st.iframe(m._repr_html_(), height=520)

        # Bar chart
        nearby_sorted = nearby.sort_values("aqi_us", ascending=False)
        nearby_sorted["label"] = nearby_sorted["city"] + ", " + nearby_sorted["country"]
        nearby_sorted["color"] = nearby_sorted["aqi_category"].map(AQI_COLORS)

        fig = go.Figure(go.Bar(
            x=nearby_sorted["aqi_us"],
            y=nearby_sorted["label"],
            orientation="h",
            marker_color=nearby_sorted["color"].tolist(),
            customdata=nearby_sorted[["distance_km", "aqi_category"]],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "AQI: %{x}<br>"
                "Category: %{customdata[1]}<br>"
                "Distance: %{customdata[0]} km<extra></extra>"
            )
        ))
        fig.update_layout(
            title=f"Nearby cities by AQI (within {radius_km} km of {ref_city})",
            xaxis_title="AQI (US)",
            yaxis=dict(autorange="reversed"),
            height=max(300, len(nearby) * 28),
            margin=dict(l=10, r=10, t=40, b=40)
        )
        st.plotly_chart(fig, width="stretch")

        # Data table
        with st.expander("Full results table"):
            st.dataframe(
                nearby[[
                    "city", "country", "distance_km",
                    "aqi_us", "aqi_category", "main_pollutant",
                    "temperature", "humidity", "wind_speed"
                ]].reset_index(drop=True),
                width="stretch",
                hide_index=True
            )
    else:
        st.info(f"No cities found within {radius_km} km with AQI >= {min_aqi}.")
        ref_row_df = pd.DataFrame([{
            "lat": ref_lat, "lon": ref_lon,
            "aqi_us": ref_aqi, "aqi_category": ref_category
        }])
        m = build_map(
            ref_city, ref_country, ref_lat, ref_lon,
            ref_aqi, ref_category,
            pd.DataFrame(columns=nearby.columns), radius_km
        )
        st.iframe(m._repr_html_(), height=520)
