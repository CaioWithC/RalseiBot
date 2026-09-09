<<<<<<< HEAD
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

=======
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

>>>>>>> 2a7ffdd025e80bcbba2c5bcf2e6d47e6908cbc17
CMD ["python", "main.py"]