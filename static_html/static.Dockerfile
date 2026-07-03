# Declared the base image
# FROM image name: latest
FROM python:3.15.0b3-trixie

WORKDIR /app 

COPY ./src .
# RUN mkdir -p static_folder
# COPY ./static_html /static_folder 

# RUN echo "Hello" > index.html



# 1 - docker build -f Dockerfile -t pyapp .
# 2 - docker run -it pyapp
# 3 - docker run -it -p 3000:8000 pyapp


# python -m http.server 8000
CMD ["python", "-m", "http.server", "8000"]