# Recruiter Demo Guide: Automated BI Pipeline

*A 3-5 minute walkthrough script demonstrating the value of Project 2.*

---

## 1. The Hook (30 seconds)
**Goal:** Establish the business problem and your solution.

"Hi, I'm [Your Name]. This is my Automated BI Pipeline with AI Enrichment. 
Every company struggles with disconnected data — marketing has leads, operations has orders, and support has tickets. 
I built a production-grade system that orchestrates data extraction from 5 sources, enriches it with AI, and delivers bilingual insights automatically."

## 2. The Architecture (45 seconds)
**Goal:** Show you are a serious engineer who understands production environments.

*(Show the `docker-compose.yml` or Airflow UI)*
"I didn't just write a python script. I built this on a modern data stack.
- It runs on **Docker Compose** for complete local reproducibility.
- **Apache Airflow** orchestrates the ETL DAG.
- **PostgreSQL** serves as the data warehouse with strict `raw` and `mart` schemas.
- And I built a pluggable AI layer that can use Anthropic, Ollama, or mock endpoints to control costs."

## 3. The Core Execution (1 minute)
**Goal:** Prove the code works end-to-end.

*(Trigger the DAG in Airflow)*
"Let's run the pipeline. As you can see in Airflow, it’s executing the `bi_pipeline` DAG. 
Behind the scenes, Python Pandas is transforming the raw data, and our LLM enricher is categorizing support tickets, summarizing product reviews in two languages, and detecting revenue anomalies. 
It then safely loads this into Postgres and generates a PDF report."

## 4. The Business Value (1 minute)
**Goal:** Show the outcome stakeholders care about.

*(Open Streamlit Dashboard at localhost:8501)*
"Here is the Streamlit dashboard that reads from the enriched mart. 
Notice the bilingual toggle — I built this with the EMEA market in mind (French/English).
Because of the AI enrichment, we aren't just looking at raw ticket counts. We can see AI-classified sentiment and urgency. We can see AI-detected revenue anomalies with human-readable explanations. 
This is what bridges the gap between raw data and business intelligence."

## 5. Security & Tests (30 seconds)
**Goal:** Alleviate hiring manager fears.

"To wrap up: 
- **Security:** There are absolutely no hardcoded API keys; everything is handled via `.env` and environment variables. 
- **Database Safety:** The dashboard connects using a read-only Postgres role.
- **Testing:** The pipeline is covered by `pytest` unit tests, ensuring transforms and logic are reliable before deployment.

This proves I can build AI automation that ships safely to production."
