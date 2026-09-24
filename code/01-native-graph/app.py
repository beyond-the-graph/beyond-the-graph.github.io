import folium
import itertools
import numpy as np
import os
import pandas as pd
import streamlit as st

from neo4j import GraphDatabase
from scipy.spatial import ConvexHull

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="London Underground Explorer",
    page_icon="🚇",
    layout="wide"
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
CARTO_API_KEY  = os.environ.get("CARTO_API_KEY", "")

MAP_TILES = (
    f"https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png?key={CARTO_API_KEY}"
    if CARTO_API_KEY
    else "CartoDB positron"
)
MAP_ATTR = (
    "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>, "
    "&copy; <a href='https://carto.com/attributions'>CARTO</a>"
)

HOP_COLORS = {
    1: "#00429d",
    2: "#3a6db0",
    3: "#6896c3",
    4: "#96bed6",
    5: "#c9dfe8",
    6: "#f4c89b",
    7: "#e8844a",
    8: "#c0391b",
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
def load_data():
    stations_df    = pd.read_csv("data/london_stations.csv")
    connections_df = pd.read_csv("data/london_connections.csv")
    lines_df       = pd.read_csv("data/london_lines.csv")

    for df in [stations_df, connections_df, lines_df]:
        df.columns = df.columns.str.strip()
        df.update(df.select_dtypes(include="object").apply(lambda c: c.str.strip()))

    connections_df = connections_df.merge(lines_df, on="Tube Line", how="inner")

    connected_stations = (
        set(connections_df["From Station"]) | set(connections_df["To Station"])
    )
    stations_df = stations_df[
        stations_df["Station"].isin(connected_stations)
    ].copy()

    coord_lookup = (
        stations_df
        .set_index("Station")[["Latitude", "Longitude"]]
        .to_dict("index")
    )

    return stations_df, connections_df, coord_lookup

# ---------------------------------------------------------------------------
# Cypher queries
# ---------------------------------------------------------------------------

def run_shortest_path(driver, origin, destination):
    cypher = """
    MATCH p = shortestPath(
        (a:Station {name: $origin})-[:CONNECTS_TO*]-(b:Station {name: $dest})
    )
    RETURN [s IN nodes(p) | s.name]          AS stations,
           [r IN relationships(p) | r.line]  AS lines,
           [r IN relationships(p) | r.color] AS colors,
           length(p)                         AS hops
    """
    with driver.session() as session:
        result = session.run(cypher, origin=origin, dest=destination)
        return result.single()


def run_isochrone(driver, origin, max_hops):
    cypher = f"""
    MATCH p = (origin:Station {{name: $origin}})-[:CONNECTS_TO*1..{max_hops}]->(s:Station)
    WITH s, min(length(p)) AS hops
    RETURN s.name AS name,
           s.lat  AS lat,
           s.lon  AS lon,
           s.zone AS zone,
           hops
    ORDER BY hops
    """
    with driver.session() as session:
        result = session.run(cypher, origin=origin)
        df = pd.DataFrame([r.data() for r in result])
    if not df.empty:
        df = df[df["name"] != origin].reset_index(drop=True)
    return df

# ---------------------------------------------------------------------------
# Map builders
# ---------------------------------------------------------------------------

def build_shortest_path_map(record, interchanges, connections_df,
                             coord_lookup, origin, destination):
    path_stations = record["stations"]
    path_lines    = record["lines"]
    path_colors   = record["colors"]
    path_hops     = record["hops"]

    path_coords = [coord_lookup[s] for s in path_stations if s in coord_lookup]
    center_lat  = np.mean([c["Latitude"]  for c in path_coords])
    center_lon  = np.mean([c["Longitude"] for c in path_coords])

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles=MAP_TILES,
        attr=MAP_ATTR
    )

    # Background tube network
    for _, row in connections_df.iterrows():
        fc = coord_lookup.get(row["From Station"])
        tc = coord_lookup.get(row["To Station"])
        if fc and tc:
            folium.PolyLine(
                locations=[
                    [fc["Latitude"], fc["Longitude"]],
                    [tc["Latitude"], tc["Longitude"]]
                ],
                color=row["Color"],
                weight=2,
                opacity=0.25
            ).add_to(m)

    # Route segments
    for i in range(len(path_stations) - 1):
        a = coord_lookup.get(path_stations[i])
        b = coord_lookup.get(path_stations[i + 1])
        if a and b:
            folium.PolyLine(
                locations=[
                    [a["Latitude"], a["Longitude"]],
                    [b["Latitude"], b["Longitude"]]
                ],
                color=path_colors[i],
                weight=5,
                opacity=0.9,
                tooltip=path_lines[i]
            ).add_to(m)

    # Station markers
    for i, station in enumerate(path_stations):
        c = coord_lookup.get(station)
        if not c:
            continue

        is_origin      = station == origin
        is_destination = station == destination
        is_interchange = station in interchanges

        if is_origin:
            folium.Marker(
                location=[c["Latitude"], c["Longitude"]],
                tooltip=f"<b>{station}</b><br>Origin",
                icon=folium.Icon(color="green", icon="play", prefix="fa")
            ).add_to(m)
        elif is_destination:
            folium.Marker(
                location=[c["Latitude"], c["Longitude"]],
                tooltip=f"<b>{station}</b><br>Destination",
                icon=folium.Icon(color="red", icon="flag", prefix="fa")
            ).add_to(m)
        elif is_interchange:
            folium.CircleMarker(
                location=[c["Latitude"], c["Longitude"]],
                radius=8,
                color="white",
                weight=1.5,
                fill=True,
                fill_color="#f4a261",
                fill_opacity=0.95,
                tooltip=f"<b>{station}</b><br>Interchange"
            ).add_to(m)
        else:
            seg_color  = path_colors[i] if i < len(path_colors) else path_colors[-1]
            line_label = path_lines[i]  if i < len(path_lines)  else path_lines[-1]
            folium.CircleMarker(
                location=[c["Latitude"], c["Longitude"]],
                radius=6,
                color="white",
                weight=1,
                fill=True,
                fill_color=seg_color,
                fill_opacity=0.9,
                tooltip=f"<b>{station}</b><br>{line_label}"
            ).add_to(m)

    # Legend
    legend_items = ""
    seen_lines = []
    for line, color in zip(path_lines, path_colors):
        if line not in seen_lines:
            legend_items += (
                f'<span style="display:inline-block;width:24px;height:4px;'
                f'background:{color};margin-right:6px;vertical-align:middle;"></span>'
                f'{line}<br>'
            )
            seen_lines.append(line)

    legend_html = f"""
    <div style="
        position:fixed;bottom:40px;left:40px;z-index:1000;
        background:white;padding:12px 16px;border-radius:8px;
        box-shadow:0 2px 6px rgba(0,0,0,0.3);font-family:sans-serif;
        font-size:13px;line-height:2;
    ">
      <b>{origin} to {destination}</b><br>
      {path_hops} stops<br><br>
      {legend_items}
      <span style="display:inline-block;width:12px;height:12px;
        border-radius:50%;background:#f4a261;margin-right:6px;
        vertical-align:middle;"></span>Interchange<br>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m, path_stations, path_lines, path_hops, interchanges


def build_isochrone_map(iso_df, iso_origin, origin_lat, origin_lon,
                         connections_df, stations_df, coord_lookup):

    m = folium.Map(
        location=[origin_lat, origin_lon],
        zoom_start=12,
        tiles=MAP_TILES,
        attr=MAP_ATTR
    )

    # Background tube lines
    for _, row in connections_df.iterrows():
        fc = coord_lookup.get(row["From Station"])
        tc = coord_lookup.get(row["To Station"])
        if fc and tc:
            folium.PolyLine(
                locations=[
                    [fc["Latitude"], fc["Longitude"]],
                    [tc["Latitude"], tc["Longitude"]]
                ],
                color=row["Color"],
                weight=3,
                opacity=0.4
            ).add_to(m)

    # Convex hull rings
    for hop in sorted(iso_df["hops"].unique(), reverse=True):
        tier = iso_df[iso_df["hops"] <= hop]
        coords = np.array([
            (float(lon), float(lat))
            for lon, lat in zip(tier["lon"], tier["lat"])
        ])
        if len(coords) >= 3:
            try:
                hull = ConvexHull(coords)
                hull_pts = coords[hull.vertices].tolist()
                hull_pts.append(hull_pts[0])
                color = HOP_COLORS.get(hop, "#888888")
                folium.Polygon(
                    locations=[[p[1], p[0]] for p in hull_pts],
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.12,
                    weight=1.5
                ).add_to(m)
            except Exception:
                pass

    # Unreachable stations
    reachable_names = set(iso_df["name"])
    for _, row in stations_df.iterrows():
        if row["Station"] not in reachable_names and row["Station"] != iso_origin:
            folium.CircleMarker(
                location=[row["Latitude"], row["Longitude"]],
                radius=3,
                color="#aaaaaa",
                fill=True,
                fill_opacity=0.5,
                tooltip=row["Station"]
            ).add_to(m)

    # Reachable stations
    for _, row in iso_df.iterrows():
        color = HOP_COLORS.get(row["hops"], "#888888")
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=7,
            color="white",
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=(
                f"<b>{row['name']}</b><br>"
                f"Stops from {iso_origin}: {row['hops']}<br>"
                f"Zone: {row['zone']}"
            )
        ).add_to(m)

    # Origin marker
    folium.Marker(
        location=[origin_lat, origin_lon],
        tooltip=f"<b>{iso_origin}</b> (origin)",
        icon=folium.Icon(color="red", icon="circle", prefix="fa")
    ).add_to(m)

    # Legend
    legend_rows = "".join(
        f'<span style="display:inline-block;width:14px;height:14px;'
        f'border-radius:50%;background:{HOP_COLORS[h]};margin-right:6px;"></span>'
        f'{h} stop{"s" if h > 1 else ""}<br>'
        for h in sorted(HOP_COLORS)
        if h in iso_df["hops"].values
    )
    legend_html = f"""
    <div style="
        position:fixed;bottom:40px;left:40px;z-index:1000;
        background:white;padding:12px 16px;border-radius:8px;
        box-shadow:0 2px 6px rgba(0,0,0,0.3);font-family:sans-serif;
        font-size:13px;line-height:1.8;
    ">
      <b>Stops from {iso_origin}</b><br>
      {legend_rows}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("London Underground Explorer")
st.caption(
    "Shortest path and isochrone queries on the London Underground graph, "
    "powered by Neo4j."
)

driver         = get_driver()
stations_df, connections_df, coord_lookup = load_data()
station_names  = sorted(stations_df["Station"].tolist())

tab1, tab2 = st.tabs(["Shortest Path", "Isochrone"])

# ---------------------------------------------------------------------------
# Tab 1: Shortest path
# ---------------------------------------------------------------------------

with tab1:
    st.subheader("Find a route")
    st.write(
        "Select an origin and destination to find the minimum-stop route "
        "and any line changes along the way."
    )

    col1, col2 = st.columns(2)
    with col1:
        origin = st.selectbox(
            "Origin",
            station_names,
            index=station_names.index("Kings Cross St. Pancras")
        )
    with col2:
        destination = st.selectbox(
            "Destination",
            station_names,
            index=station_names.index("Waterloo")
        )

    if st.button("Find route", type="primary"):
        if origin == destination:
            st.warning("Origin and destination must be different stations.")
        else:
            with st.spinner("Finding shortest path..."):
                record = run_shortest_path(driver, origin, destination)

            if record is None:
                st.error(f"No path found between {origin} and {destination}.")
            else:
                path_stations = record["stations"]
                path_lines    = record["lines"]
                path_colors   = record["colors"]
                path_hops     = record["hops"]

                # Identify interchanges
                interchanges = []
                for i in range(1, len(path_lines)):
                    if path_lines[i] != path_lines[i - 1]:
                        interchanges.append(path_stations[i])

                # Route summary
                st.markdown(f"### {origin} to {destination}")
                mcol1, mcol2, mcol3 = st.columns(3)
                mcol1.metric("Stops", path_hops)
                mcol2.metric("Lines", len(set(path_lines)))
                mcol3.metric("Interchanges", len(interchanges))

                # Route detail
                with st.expander("Route detail", expanded=True):
                    for i, station in enumerate(path_stations):
                        if i < len(path_lines):
                            marker = " -- change here" if station in interchanges else ""
                            st.write(f"**{station}** via {path_lines[i]}{marker}")
                        else:
                            st.write(f"**{station}**")

                # Map
                m, *_ = build_shortest_path_map(
                    record, interchanges, connections_df,
                    coord_lookup, origin, destination
                )
                st.iframe(m._repr_html_(), height=600)

# ---------------------------------------------------------------------------
# Tab 2: Isochrone
# ---------------------------------------------------------------------------

with tab2:
    st.subheader("Reachability explorer")
    st.write(
        "Select an origin station and a maximum number of stops "
        "to see which stations you can reach."
    )

    col3, col4 = st.columns([2, 1])
    with col3:
        iso_origin = st.selectbox(
            "Origin station",
            station_names,
            index=station_names.index("Oxford Circus")
        )
    with col4:
        max_hops = st.slider("Maximum stops", min_value=1, max_value=8, value=8)

    if st.button("Explore reachability", type="primary"):
        with st.spinner("Running isochrone query..."):
            iso_df = run_isochrone(driver, iso_origin, max_hops)

        if iso_df.empty:
            st.error(f"No reachable stations found from {iso_origin}.")
        else:
            origin_row = stations_df[stations_df["Station"] == iso_origin].iloc[0]
            origin_lat = origin_row["Latitude"]
            origin_lon = origin_row["Longitude"]

            st.markdown(f"### From {iso_origin}")
            icol1, icol2 = st.columns(2)
            icol1.metric("Reachable stations", len(iso_df))
            icol2.metric("Maximum stops", max_hops)

            # Map
            m2 = build_isochrone_map(
                iso_df, iso_origin, origin_lat, origin_lon,
                connections_df, stations_df, coord_lookup
            )
            st.iframe(m2._repr_html_(), height=500)

            # Reachable stations table
            with st.expander("Reachable stations by stop count"):
                hop_counts = (
                    iso_df
                    .groupby("hops")
                    .size()
                    .reset_index(name="stations")
                    .rename(columns={"hops": "Stops", "stations": "Stations reached"})
                )
                st.dataframe(hop_counts, width="stretch", hide_index=True)
