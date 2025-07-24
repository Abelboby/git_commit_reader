import argparse
import subprocess
import sys
import os
import datetime
import requests
from collections import defaultdict

REPO_LIST_FILE = 'repos.txt'
REPORTS_DIR = 'reports'

# Try to load .env if present

def load_dotenv_key(key_name):
    env_path = os.path.join(os.getcwd(), '.env')
    if os.path.isfile(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('#') or '=' not in line:
                        continue
                    k, v = line.strip().split('=', 1)
                    if k.strip() == key_name:
                        return v.strip().strip('"').strip("'")
        except Exception:
            pass
    return None

# Helper to parse git log

def fetch_commits(repo_path=None):
    try:
        cwd = repo_path if repo_path else os.getcwd()
        result = subprocess.run(
            [
                'git', 'log', '--pretty=format:%H|%ad|%s', '--date=short'
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            cwd=cwd
        )
        lines = result.stdout.strip().split('\n')
        commits = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split('|', 2)
            if len(parts) == 3:
                commit_hash, date, message = parts
                commits.append({'hash': commit_hash, 'date': date, 'message': message})
        return commits
    except Exception as e:
        print(f"Error fetching git log: {e}")
        return []

# Group commits by date
def group_commits_by_date(commits):
    grouped = defaultdict(list)
    for commit in commits:
        grouped[commit['date']].append(commit['message'])
    return grouped

# Filter commits by date or range
def filter_commits(commits, start_date=None, end_date=None):
    filtered = []
    for commit in commits:
        commit_date = datetime.datetime.strptime(commit['date'], '%Y-%m-%d').date()
        if start_date and commit_date < start_date:
            continue
        if end_date and commit_date > end_date:
            continue
        filtered.append(commit)
    return filtered

# Summarize using Gemini API
def summarize_with_gemini(messages, api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    prompt = "Summarize the following git commit messages as a daily work report, focusing on tasks completed. Messages: " + '\n'.join(messages)
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key
    }
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        if 'candidates' in result and result['candidates']:
            return result['candidates'][0]['content']['parts'][0]['text']
        return "[No summary returned by Gemini API]"
    except Exception as e:
        return f"[Gemini API error: {e}]"

def extract_task_points(summary):
    # Try to extract bullet points from the summary
    import re
    points = []
    # Look for lines starting with a bullet or dash
    for line in summary.splitlines():
        line = line.strip()
        if re.match(r'^[*-]\s+', line):
            points.append(line.lstrip('*-').strip())
    # If no bullets, just return the summary as a single point
    if not points and summary.strip():
        points = [summary.strip()]
    return points

# Main analysis function
def analyze_commits(commits, api_key, repo_path, start_date, end_date):
    grouped = group_commits_by_date(commits)
    repo_name = os.path.basename(os.path.abspath(repo_path))
    if start_date == end_date:
        date_str = start_date.strftime('%Y-%m-%d')
    else:
        date_str = f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}"
    report_folder = os.path.join(REPORTS_DIR, repo_name)
    os.makedirs(report_folder, exist_ok=True)
    report_file = os.path.join(report_folder, f"{date_str}.md")
    output_lines = [f"# Work Summary for {repo_name} ({date_str})\n"]
    all_points = []
    for date in sorted(grouped.keys()):
        messages = grouped[date]
        output_lines.append(f"## Date: {date}")
        summary = summarize_with_gemini(messages, api_key)
        output_lines.append(f"**Summary:** {summary}\n")
        output_lines.append("**Messages:**")
        for msg in messages:
            output_lines.append(f"- {msg}")
        output_lines.append("")
        # Extract points for this date
        points = extract_task_points(summary)
        all_points.extend(points)
    output = '\n'.join(output_lines)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(output)
    # Print only the concise list of tasks to the console
    for point in all_points:
        print(f"- {point}")

# Repo path management
def load_repo_paths():
    if not os.path.isfile(REPO_LIST_FILE):
        return []
    with open(REPO_LIST_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def save_repo_path(path):
    paths = load_repo_paths()
    if path not in paths:
        with open(REPO_LIST_FILE, 'a', encoding='utf-8') as f:
            f.write(path + '\n')

def prompt_repo_path():
    paths = load_repo_paths()
    if paths:
        print("Select a repo path:")
        for idx, p in enumerate(paths, 1):
            print(f"{idx}. {p}")
        print(f"{len(paths)+1}. Add new repo path")
        choice = input(f"Enter choice (1-{len(paths)+1}): ").strip()
        try:
            choice = int(choice)
            if 1 <= choice <= len(paths):
                return paths[choice-1]
            elif choice == len(paths)+1:
                new_path = input("Enter new repo path: ").strip()
                if os.path.isdir(new_path):
                    save_repo_path(new_path)
                    return new_path
                else:
                    print("Invalid directory path.")
                    sys.exit(1)
            else:
                print("Invalid choice.")
                sys.exit(1)
        except Exception:
            print("Invalid input.")
            sys.exit(1)
    else:
        new_path = input("Enter new repo path: ").strip()
        if os.path.isdir(new_path):
            save_repo_path(new_path)
            return new_path
        else:
            print("Invalid directory path.")
            sys.exit(1)

def prompt_user():
    repo_path = prompt_repo_path()
    print("Select analysis type:")
    print("1. All history")
    print("2. Specific date")
    print("3. Date range")
    print("4. Today")
    print("5. Yesterday")
    choice = input("Enter choice (1/2/3/4/5): ").strip()
    start_date = end_date = None
    if choice == '2':
        date_str = input("Enter date (YYYY-MM-DD): ").strip()
        try:
            start_date = end_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            print("Invalid date format.")
            sys.exit(1)
    elif choice == '3':
        start_str = input("Enter start date (YYYY-MM-DD): ").strip()
        end_str = input("Enter end date (YYYY-MM-DD): ").strip()
        try:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
        except Exception:
            print("Invalid date format.")
            sys.exit(1)
    elif choice == '4':  # Today
        today = datetime.date.today()
        start_date = end_date = today
    elif choice == '5':  # Yesterday
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        start_date = end_date = yesterday
    # else: all history (no date filtering)
    # Always use Gemini summary
    api_key = load_dotenv_key('GEMINI_API_KEY')
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        api_key = input("Enter Gemini API key (or set GEMINI_API_KEY env): ").strip()
    if not api_key:
        print("Gemini API key required for smart summary.")
        sys.exit(1)
    return repo_path, start_date, end_date, api_key

if __name__ == "__main__":
    repo_path, start_date, end_date, api_key = prompt_user()
    commits = fetch_commits(repo_path)
    if not commits:
        print("No commits found.")
        sys.exit(1)
    filtered_commits = filter_commits(commits, start_date, end_date)
    if not filtered_commits:
        print("No commits found for the specified date or range.")
        sys.exit(0)
    analyze_commits(
        filtered_commits,
        api_key=api_key,
        repo_path=repo_path,
        start_date=start_date if start_date else filtered_commits[0]['date'],
        end_date=end_date if end_date else filtered_commits[-1]['date']
    ) 