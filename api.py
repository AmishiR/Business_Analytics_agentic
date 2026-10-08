# --- api.py ---
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import plotly.io as pio
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from plotly.graph_objs import Figure

from agent import analytics_agent

app = FastAPI(title="AI Business Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def df_to_records(df: pd.DataFrame):
    # Round-trips through pandas' own JSON encoder so NaN/NaT/numpy
    # dtypes come out as valid JSON instead of raising or emitting
    # non-standard tokens like `NaN`.
    return json.loads(df.to_json(orient="records"))


def serialize_figure(fig):
    # figures entries from plot_result are one of: a Plotly Figure,
    # the string "table" (render as table instead), or None (failed).
    if isinstance(fig, Figure):
        return json.loads(pio.to_json(fig))
    return fig


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    # upload_to_db derives the SQL table name from this path's basename,
    # so keep the user's original filename (table name stays readable,
    # e.g. "leads.csv" -> table "leads") and get uniqueness from a
    # per-upload UUID subdirectory instead of renaming the file itself.
    upload_dir = UPLOAD_DIR / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / file.filename

    with open(saved_path, "wb") as f:
        f.write(await file.read())

    result = analytics_agent.invoke({"file_path": str(saved_path)})

    query_results = {
        title: df_to_records(df)
        for title, df in result.get("query_results", {}).items()
    }

    figures = [serialize_figure(fig) for fig in result.get("figures", [])]

    return {
        "data_report": result.get("data_report"),
        "database_name": result.get("database_name"),
        "table_name": result.get("table_name"),
        "upload_status": result.get("upload_status"),
        "generated_queries": result.get("generated_queries"),
        "chart_info": result.get("chart_info"),
        "errors": result.get("errors"),
        "query_results": query_results,
        "figures": figures,
    }
