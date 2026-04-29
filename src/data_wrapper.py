import pandas as pd
import os

class DataLoader:
    def __init__(self, use_api=False):
        self.use_api = use_api
        self.mock_file_path = os.path.join("data", "raw", "mock_library.csv")

    def fetch_user_library(self):
        """
        Fetches the song library. 
        Currently uses mock CSV, easily toggled to API later.
        """
        if self.use_api:
            print("Fetching from Spotify API...")
            # TODO: Add your logic here later
            return self._fetch_from_spotify()
        else:
            print("Loading mock library for local testing...")
            return pd.read_csv(self.mock_file_path)

    def _fetch_from_spotify(self):
        # Your future API code goes here
        pass

# Other member can now call this to get her pandas DataFrame instantly:
# loader = DataLoader(use_api=False)
# df = loader.fetch_user_library()