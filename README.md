# Sonique — Hybrid AI Music Recommendation Agent

Sonique is an intelligent music recommendation agent designed to demonstrate both Natural Language Reasoning (via local LLMs) and Content-Based Filtering (via a custom multi-attribute scoring algorithm).

The system operates in a hybrid architecture:
1. Individual Discovery: Uses a local Ollama (Llama 3.2) model to perform zero-shot inference on live window titles to suggest songs based on current "vibe."
2. History-Based Intelligence: Uses a Custom Weighted Scoring Algorithm (SQLite-backed) to analyze the user’s listening history and provide high-confidence recommendations based on artist and genre frequency.

---------------------------------------------------------------------------------------------------------------------------------------

## 1. Environment Setup

To ensure the code runs exactly as developed, we recommend using Miniconda or Anaconda to manage the environment.

### Prerequisites
* Python 3.10+
* Ollama Desktop: https://ollama.com/ (Required for the "Now Playing" LLM features).
* Windows OS: (Required for the pywin32 window detection module).

### Installation Steps
1. Create a clean environment:
   conda create -n sonique_env python=3.11
   conda activate sonique_env

2. Install Project Dependencies:
   pip install ollama pystray pillow pywin32 psutil

3. Prepare the Local LLM:
   Ensure Ollama is running in your system tray, then pull the required model:
   ollama pull llama3.2

---------------------------------------------------------------------------------------------------------------------------------------

## 2. Running the Application

1. Start the Agent:
   Navigate to the src directory and run the main script:
   python sonique.py

2. Access the Interface:
   * The application will launch a Graphical User Interface (GUI).
   * It will also place a Sonique Icon in your Windows System Tray (bottom right). You can right-click this icon to navigate between tabs.

---------------------------------------------------------------------------------------------------------------------------------------

## 3. Proof of Algorithm Behavior

To evaluate the system, please perform the following tests within the interface:

### Test A: History-Based Scoring (The Custom Algorithm)
1. Add some songs either through the Now Playing tab or manually adding them through the Log Song tab
2. Navigate to the History tab.
3. Navigate to the Recs tab and click "Get recommendations."
4. The Result: You will see 5 recommendation cards. 
   * The Logic: The system calculates a Match Percentage by analyzing the frequency of artists and genres in the loaded history. 
   * Verification: High-frequency artists in the history will result in higher match percentages (e.g., 90%+), while generic popular fallbacks will show lower confidence scores.

### Test B: Real-Time Discovery (The LLM Agent)
1. Open a browser (Chrome/Edge) and play a song on YouTube or open the Spotify desktop app.
2. In Sonique, go to the Now Playing tab.
3. Wait ~4 seconds for the Auto-Detection to identify your song title and artist from the active window.
4. Click "Get recommendations for this song."
5. The Result: The system will send the track metadata to the Llama 3.2 model via Ollama. It will return a JSON parsed list of songs that match the "vibe" of the current track, even if those songs are not in the local database.

---------------------------------------------------------------------------------------------------------------------------------------

## 4. Technical Notes

* Database: Serverless SQLite (.sonique_pro.db) stored in the User home directory.
* Multi-Threading: The GUI remains responsive during AI fetches by utilizing Python threading for background requests.

---------------------------------------------------------------------------------------------------------------------------------------

