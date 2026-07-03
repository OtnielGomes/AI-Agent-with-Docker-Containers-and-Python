# imports 
from fastapi import FastAPI

# create a fastapi app
app = FastAPI()

# create a route
@app.get("/")
def read_index():
    return {"Hello": "World"}
