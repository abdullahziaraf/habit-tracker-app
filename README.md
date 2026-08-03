# Habit Tracker App

A simple habit tracking web app built with **Streamlit**, containerized with **Docker**, and deployed as part of a hands-on DevOps workflow covering Git, GitHub, and containerization.

## Features
- Add and track daily habits
- Mark habits as complete/incomplete
- View progress over time
- Simple, clean web interface built with Streamlit

## Tech Stack
- **Python** — core application logic
- **Streamlit** — web framework for the UI
- **Docker** — containerization and deployment
- **Git & GitHub** — version control

## Running Locally 
```bash
pip install -r requirements.txt
streamlit run app.py
```

App will be available at `http://localhost:8501`

## Running with Docker

Build the image:
```bash
docker build -t habit-tracker-app .
```

Run the container:
```bash
docker run -d -p 8080:80 --name habit-tracker habit-tracker-app
```

Visit `http://localhost:8080` (or your machine/VM's IP address on port 8080)

## Project Structure

```
habit-tracker-app/
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container build instructions
└── README.md           # Project documentation
```

## What This Project Demonstrates

This project was built as a practical exercise in core DevOps practices:
- Version control with Git and GitHub
- Writing a Dockerfile to containerize a Python web application
- Building and running Docker images/containers
- Configuring port mapping between host and container (external `8080` → internal `80`)
