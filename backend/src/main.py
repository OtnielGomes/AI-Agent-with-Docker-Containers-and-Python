# imports 
import os
from fastapi import FastAPI

# Create a fastapi app
app = FastAPI()

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise NotImplementedError("API_KEY is not set")

MY_PROJECT = os.environ.get("MY_PROJECT") or "This is a default project"

# Create a route
@app.get("/")
def read_index():
    return {"Hello": "World",  "MY PROJECT NAME": MY_PROJECT}
