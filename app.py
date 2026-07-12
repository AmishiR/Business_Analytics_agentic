# --- app.py ---
import streamlit as st
import os
import tempfile
import json
from agent import analytics_agent  # This imports your working graph!

st.set_page_config(page_title="AI Data Analyst", page_icon="📊", layout="wide")

st.title("🤖 AI Business Analytics Agent")
st.markdown("Upload your dataset and let AI clean, analyze, query, and visualize your data.")

# 1. File Uploader in Sidebar
with st.sidebar:
    st.header("1. Upload Data")
    uploaded_file = st.file_uploader("Upload CSV or JSON", type=["csv", "json"])

# 2. Main Logic
if uploaded_file is not None:
    # We need to save the uploaded file temporarily so agent.py can read it from a file path
    file_extension = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_file_path = tmp_file.name

    st.success(f"File '{uploaded_file.name}' uploaded successfully!")

    if st.button("🚀 Run AI Analysis"):
        with st.spinner("Agent is working... Cleaning data, writing SQL, and generating charts (this may take a minute)..."):
            
            try:
                # --- RUN THE LANGGRAPH AGENT ---
                initial_state = {"file_path": tmp_file_path}
                result = analytics_agent.invoke(initial_state)
                
                # --- DISPLAY RESULTS ---
                
                # Data Report & DB Upload Status
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Data Cleaning Report")
                    report = result.get("data_report", {})
                    st.metric("Total Rows", report.get("rows", 0))
                    st.metric("Total Columns", report.get("columns", 0))
                    st.metric("Missing Values", report.get("total_missing", 0))
                    st.metric("Duplicate Rows", report.get("duplicate_rows", 0))
                
                with col2:
                    st.subheader(" Database")
                    st.info(result.get("upload_status", "No status returned"))
                    
                    st.subheader("SQL Queries")
                    with st.expander("View Raw JSON Queries "):
                        st.code(result.get("generated_queries"), language="json")

                st.divider()

                # Display Charts
                st.subheader(" Insights")
                figures = result.get("figures", [])
                chart_info = result.get("chart_info", [])
                query_results = result.get("query_results", {})

                if not figures:
                    st.warning("No charts were generated.")
                else:
                    # Create two columns for charts to make it look like a dashboard
                    chart_cols = st.columns(2)
                    
                    for i, fig in enumerate(figures):
                        # Get the title from chart info if available
                        title = chart_info[i].get("title", f"Insight {i+1}") if i < len(chart_info) else f"Insight {i+1}"
                        
                        # Alternate between column 1 and column 2
                        col = chart_cols[i % 2]
                        
                        with col:
                            if fig is None:
                                st.error("Failed to generate chart. Data might be insufficient.")
                            elif fig == "table":
                                st.dataframe(query_results.get(title), use_container_width=True)
                            else:
                                st.plotly_chart(fig, use_container_width=True)
                                
            except Exception as e:
                st.error(f"An error occurred while running the agent: {e}")
                
            finally:
                # Clean up the temporary file
                if os.path.exists(tmp_file_path):
                    os.remove(tmp_file_path)
else:
    st.info("👈 Please upload a dataset in the sidebar to begin.")