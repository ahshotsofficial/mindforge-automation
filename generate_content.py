name: Daily Automation

on:
  schedule:
    - cron: "0 12 * * *"
  workflow_dispatch:

jobs:
  mindforge:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          pip install google-genai

      - name: Generate Mindforge Content
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          python generate_content.py
