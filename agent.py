# --- agent.py ---
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Any
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
import plotly.express as px
import os
import json

# Load environment variables
load_dotenv()

# Model and Database
model = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    temperature=0
)

DATABASE_NAME = "postgres"

engine = create_engine(
    os.getenv("SUPABASE_DB_URL"),
    connect_args={"sslmode": "require"}
)


# -----------------------------
# State Definition
# -----------------------------
class AnalyticsState(TypedDict):
    file_path: str
    df: Any
    data_report: dict
    database_name: str
    table_name: str
    upload_status: str
    generated_queries: str
    query_results: dict
    figures: list
    chart_info: list
    errors: dict


# -----------------------------
# Load Dataset
# -----------------------------
def load_file(state: AnalyticsState) -> AnalyticsState:

    file_path = state["file_path"]

    if file_path.endswith(".csv"):
        df = pd.read_csv(file_path)

    elif file_path.endswith(".json"):
        df = pd.read_json(file_path)

    else:
        raise ValueError("Unsupported file format")

    state["df"] = df

    return state


# -----------------------------
# Data Cleaning Report
# -----------------------------
def data_clean(state: AnalyticsState) -> AnalyticsState:

    df = state["df"]

    report = {
        "rows": len(df),
        "columns": len(df.columns),
        "missing_values": df.isnull().sum().to_dict(),
        "total_missing": int(df.isnull().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum())
    }

    state["data_report"] = report

    return state


# -----------------------------
# Upload Dataset to PostgreSQL
# -----------------------------
def upload_to_db(state: AnalyticsState) -> AnalyticsState:

    df = state["df"]

    filename = os.path.basename(state["file_path"])

    table_name = (
        os.path.splitext(filename)[0]
        .lower()
        .replace(" ", "_")
    )

    df.to_sql(
        table_name,
        con=engine,
        if_exists="replace",
        index=False
    )

    state["database_name"] = DATABASE_NAME
    state["table_name"] = table_name

    state["upload_status"] = (
        f"{len(df)} rows uploaded to "
        f"{DATABASE_NAME}.{table_name}"
    )

    return state


# -----------------------------
# LLM SQL Generation
# -----------------------------
def llm_layer(state: AnalyticsState) -> AnalyticsState:

    df = state["df"]

    prompt = f"""
You are an expert PostgreSQL Business Analyst.

Dataset Columns:
{list(df.columns)}

Dataset Schema:
{df.dtypes.astype(str).to_dict()}

Sample Rows:
{df.head(10).to_dict(orient="records")}

The PostgreSQL table name is:

data

Generate EXACTLY FIVE analytical SQL queries.

Requirements:

- Use ONLY the columns listed above.
- Never invent column names.
- Wrap every column name in DOUBLE QUOTES.

Example:

SELECT
"Lead Owner",
COUNT(*) AS value
FROM data
GROUP BY "Lead Owner";

Each query must answer a different business question.

Examples:
- Top categories
- Distribution
- Trends
- Rankings
- Comparisons
- Percentages
- Aggregations

Each query MUST return at least TWO columns.

Column 1:
Category / Label

Column 2:
Numeric Value

Return ONLY valid JSON.

Format:

[
    {{
        "title":"Insight Name",
        "query":"SELECT ...",
        "chart_type":"bar"
    }}
]

Allowed chart types:

bar
horizontal_bar
line
pie
scatter
table

Choose the most suitable visualization.

Database:
PostgreSQL
"""

    response = model.invoke(prompt)

    content = response.content

    # Some Gemini responses come back as a list of content blocks
    # instead of a plain string; normalize to a string either way.
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    print("\n========== GEMINI RESPONSE ==========\n")
    print(content)

    state["generated_queries"] = content

    return state
def execute_query(state: AnalyticsState) -> AnalyticsState:

    try:
        cleaned = (
            state["generated_queries"]
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        queries = json.loads(cleaned)

    except Exception as e:
        print("\nJSON PARSE ERROR")
        print(e)

        return {
            "query_results": {},
            "chart_info": [],
            "errors": {"json": str(e)}
        }

    results = {}
    errors = {}

    for q in queries:

        title = q.get("title", "Untitled")

        sql = q["query"].replace("data", state["table_name"])

        # psycopg2's default paramstyle treats a bare "%" as the start
        # of a placeholder; escape it since no bind params are ever used.
        sql = sql.replace("%", "%%")

        print("\n" + "=" * 80)
        print(title)
        print(sql)

        try:

            result_df = pd.read_sql(sql, engine)

            print(result_df.head())
            print(result_df.shape)

            if result_df.empty:
                errors[title] = "Query returned zero rows"

            else:
                results[title] = result_df

        except Exception as e:

            errors[title] = str(e)
            print("SQL ERROR:", e)

    return {
        "query_results": results,
        "chart_info": queries,
        "errors": errors
    }


def plot_result(state: AnalyticsState) -> AnalyticsState:

    query_results = state.get("query_results", {})
    queries = state.get("chart_info", [])

    figures = []

    for q in queries:

        title = q.get("title", "Untitled")
        chart_type = q.get("chart_type", "table")

        df = query_results.get(title)

        # Query failed
        if df is None:
            figures.append(None)
            continue

        # Empty dataframe
        if df.empty:
            figures.append(None)
            continue

        numeric_cols = df.select_dtypes(include="number").columns.tolist()

        categorical_cols = [
            c for c in df.columns
            if c not in numeric_cols
        ]

        # No numeric column
        if len(numeric_cols) == 0:
            figures.append("table")
            continue

        x = categorical_cols[0] if categorical_cols else df.columns[0]
        y = numeric_cols[0]

        try:

            if chart_type == "pie":

                if len(df) > 20:
                    figures.append("table")
                    continue

                fig = px.pie(
                    df,
                    names=x,
                    values=y,
                    title=title
                )

            elif chart_type == "horizontal_bar":

                fig = px.bar(
                    df,
                    x=y,
                    y=x,
                    orientation="h",
                    title=title
                )

            elif chart_type == "bar":

                fig = px.bar(
                    df,
                    x=x,
                    y=y,
                    title=title
                )

            elif chart_type == "line":

                fig = px.line(
                    df,
                    x=x,
                    y=y,
                    title=title
                )

            elif chart_type == "scatter":

                if len(numeric_cols) >= 2:

                    fig = px.scatter(
                        df,
                        x=numeric_cols[0],
                        y=numeric_cols[1],
                        title=title
                    )

                else:

                    fig = px.bar(
                        df,
                        x=x,
                        y=y,
                        title=title
                    )

            elif chart_type == "table":

                figures.append("table")
                continue

            else:

                # Unknown chart type
                fig = px.bar(
                    df,
                    x=x,
                    y=y,
                    title=title
                )

            figures.append(fig)

        except Exception as e:

            print(f"PLOT ERROR ({title})")
            print(e)

            figures.append("table")

    return {
        "figures": figures
    }

# ----------------------------
# Graph Compilation
# ----------------------------
graph = StateGraph(AnalyticsState)

graph.add_node("load_file", load_file)
graph.add_node("data_cleaning", data_clean)
graph.add_node("upload_to_db", upload_to_db)
graph.add_node("llm_layer", llm_layer)
graph.add_node("execute_query", execute_query)
graph.add_node("plot_result", plot_result)

graph.add_edge(START, "load_file")
graph.add_edge("load_file", "data_cleaning")
graph.add_edge("data_cleaning", "upload_to_db")
graph.add_edge("upload_to_db", "llm_layer")
graph.add_edge("llm_layer", "execute_query")
graph.add_edge("execute_query", "plot_result")
graph.add_edge("plot_result", END)

analytics_agent = graph.compile()


# ----------------------------------------------------
# Test Execution
# ----------------------------------------------------
if __name__ == "__main__":

    test_state = {
        "file_path": "leads.csv"
    }

    print("=" * 100)
    print("STARTING ANALYTICS AGENT")
    print("=" * 100)

    result = analytics_agent.invoke(test_state)

    print("\n")
    print("=" * 100)
    print("DATA CLEANING REPORT")
    print("=" * 100)
    print(result.get("data_report"))

    print("\n")
    print("=" * 100)
    print("UPLOAD STATUS")
    print("=" * 100)
    print(result.get("upload_status"))

    print("\n")
    print("=" * 100)
    print("GENERATED SQL")
    print("=" * 100)
    print(result.get("generated_queries"))

    print("\n")
    print("=" * 100)
    print("SQL EXECUTION ERRORS")
    print("=" * 100)

    errors = result.get("errors", {})

    if errors:
        for k, v in errors.items():
            print(f"{k}")
            print(v)
            print("-" * 60)
    else:
        print("No SQL Errors")

    print("\n")
    print("=" * 100)
    print("QUERY RESULTS")
    print("=" * 100)

    for title, df in result.get("query_results", {}).items():

        print(f"\n{title}")
        print(df.head())
        print("Rows:", len(df))
        print("Columns:", list(df.columns))

    print("\n")
    print("=" * 100)
    print("PLOT STATUS")
    print("=" * 100)

    figures = result.get("figures", [])

    for i, fig in enumerate(figures):

        print(f"\nChart {i+1}")

        if fig is None:
            print("FAILED")

        elif fig == "table":
            print("TABLE")

        else:
            print("SUCCESS")
            print(type(fig))

            fig.show()

    print("\n")
    print("=" * 100)
    print("PIPELINE FINISHED")
    print("=" * 100)
