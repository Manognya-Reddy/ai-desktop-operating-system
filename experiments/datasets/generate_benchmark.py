"""
Generates a small reproducible benchmark (spec section 23): 20-30
project/task entries covering exact, paraphrased, vague, contextual, and
ambiguous query types. Each entry is a project description plus a query
that should retrieve it.

This does NOT fabricate research results (section 38) — it only builds
the *input* benchmark. Accuracy numbers are produced later by
experiments/evaluation/run_retrieval_eval.py against a live PCM instance.

Run: python generate_benchmark.py  ->  writes benchmark.json alongside this file.
"""
import json
import os

PROJECTS = [
    {"name": "AI Resume Screener", "description": "FastAPI-based resume screening system using BERT and a React frontend."},
    {"name": "E-commerce Cart Service", "description": "Node.js microservice handling shopping cart and checkout for an online store."},
    {"name": "Weather Dashboard", "description": "React dashboard visualizing weather forecasts using an open weather API."},
    {"name": "Chat Application", "description": "Real-time chat app built with Socket.io and Express."},
    {"name": "Portfolio Website", "description": "Personal portfolio site built with Next.js and Tailwind CSS."},
    {"name": "Inventory Management System", "description": "Django app for tracking warehouse inventory and stock levels."},
    {"name": "Sentiment Analysis Tool", "description": "Python NLP tool for classifying tweet sentiment using scikit-learn."},
    {"name": "Recipe Finder App", "description": "Flutter mobile app for searching recipes by ingredient."},
    {"name": "Blog CMS", "description": "Headless content management system for blogging, built with Strapi."},
    {"name": "Expense Tracker", "description": "Personal finance app for tracking expenses, built with Vue and Firebase."},
    {"name": "Object Detection Pipeline", "description": "Computer vision pipeline using YOLO for detecting objects in video streams."},
    {"name": "Task Scheduler API", "description": "REST API for scheduling and managing background jobs with Celery."},
    {"name": "Music Streaming Backend", "description": "Backend service for streaming audio, built with Go and PostgreSQL."},
    {"name": "Study Planner App", "description": "Web app helping students plan study schedules, built with React and MongoDB."},
    {"name": "Movie Recommendation Engine", "description": "Collaborative filtering recommendation system for movies using Python."},
    {"name": "Fitness Tracker", "description": "Mobile app tracking workouts and calories, built with React Native."},
    {"name": "Job Board Platform", "description": "Full-stack job listing platform with employer and candidate portals."},
    {"name": "Code Review Bot", "description": "GitHub bot that automatically comments on pull requests with linting feedback."},
    {"name": "Password Manager", "description": "Secure local password manager with AES encryption, built in Python."},
    {"name": "Real Estate Listings Site", "description": "Property listing website with search and filtering, built with Next.js."},
    {"name": "Voice Note Transcriber", "description": "Tool that transcribes voice memos to text using a local speech model."},
    {"name": "Event Booking System", "description": "Platform for booking tickets to local events, built with Laravel."},
    {"name": "Plant Disease Classifier", "description": "CNN model classifying plant leaf diseases from images."},
    {"name": "Budget Forecasting Tool", "description": "Spreadsheet-style app forecasting monthly budgets, built with React."},
    {"name": "Resume Parsing Research", "description": "Research project extracting structured data from resumes using BERT embeddings."},
]

QUERY_TEMPLATES = {
    "exact": lambda p: f"Continue {p['name']}",
    "paraphrased": lambda p: f"Resume my project for {p['description'].split('.')[0].lower()}",
    "vague": lambda p: f"Continue the {p['name'].split()[0].lower()} project",
    "contextual": lambda p: f"Open the project where I was working on {p['description'].split(' ')[0]}",
    "ambiguous": lambda p: "Continue my research project" if "research" in p["name"].lower() or "research" in p["description"].lower() else f"Continue my {p['name'].split()[-1].lower()} project",
}


def build_benchmark():
    tasks = []
    for i, project in enumerate(PROJECTS):
        query_type = list(QUERY_TEMPLATES.keys())[i % len(QUERY_TEMPLATES)]
        query = QUERY_TEMPLATES[query_type](project)
        tasks.append({
            "task_id": f"task_{i+1:02d}",
            "project_name": project["name"],
            "project_description": project["description"],
            "query": query,
            "query_type": query_type,
            "correct_project": project["name"],
        })
    return tasks


if __name__ == "__main__":
    tasks = build_benchmark()
    out_path = os.path.join(os.path.dirname(__file__), "benchmark.json")
    with open(out_path, "w") as f:
        json.dump(tasks, f, indent=2)
    print(f"Wrote {len(tasks)} tasks to {out_path}")
