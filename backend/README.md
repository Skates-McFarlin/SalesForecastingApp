# Sales Forecasting Application

## Table of Contents
- [Introduction](#introduction)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database Setup](#database-setup)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Introduction

The Sales Forecasting Application is a web-based tool designed to predict future sales using historical data. Built with Flask for the backend and a React frontend, the application leverages machine learning models like Prophet to generate accurate sales forecasts and error metrics.

## Features

- **Sales Forecasting:** Predict future sales based on historical data.
- **Error Metrics Calculation:** Evaluate the accuracy of forecasts using MAE, RMSE, and MAPE.
- **File Upload:** Upload CSV files containing sales data for analysis.
- **Database Integration:** Store uploaded files and prediction results using MySQL.
- **RESTful API:** Interact with the application via well-defined API endpoints.
- **Responsive Frontend:** User-friendly interface built with React.

## Prerequisites

Before you begin, ensure you have met the following requirements:

- **Operating System:** Windows, macOS, or Linux.
- **Python:** Version 3.8 or higher.
- **Node.js and npm:** Required for the frontend (if applicable).
- **MySQL:** Version 5.7 or higher.
- **Git:** For cloning the repository.

## Installation

### 1. Set Up a Virtual Environment

It's recommended to use a virtual environment to manage dependencies.

```bash
python3 -m venv venv
```

Activate the virtual environment:

- **On Windows:**
  ```bash
  venv\Scripts\activate
  ```

- **On macOS and Linux:**
  ```bash
  source venv/bin/activate
  ```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## Configuration

### 1. Environment Variables

Create a `.env` file in the root directory to store environment variables. Here's a template:

```env
# Database Config
DB_USER=root
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=3306
DB_NAME=sales_forecasting_app
```

## Database Setup

### 1. Install MySQL

If you haven't installed MySQL:

- **Windows:** Download from [MySQL Downloads](https://dev.mysql.com/downloads/mysql/)
- **macOS:** Use Homebrew
  ```bash
  brew install mysql
  ```
- **Linux:** Use your distribution's package manager
  ```bash
  sudo apt-get install mysql-server
  ```

### 2. Create Database

Log in to MySQL and create the database:

```sql
CREATE DATABASE sales_forecasting_app;
```

### 3. Apply Migrations

Use Flask-Migrate to set up the database schema.

```bash
flask db init
flask db migrate -m "Initial migration."
flask db upgrade
```

This will create the necessary tables as defined in the `app/models` directory.

## Running the Application

### 1. Start the Backend Server

Ensure you're in the virtual environment and run:


```bash
python run.py
```

### 2. Access the Application

Open your web browser and navigate to `http://localhost:5000` to access the application.

## API Endpoints

The application provides the following API endpoints:

### 1. Generate Sales Forecast

- **URL:** `/api/predictions/generate`
- **Method:** `POST`
- **Description:** Generates sales forecasts based on uploaded CSV data.
- **Parameters:**
  - `file` (form-data): CSV file containing sales data.
  - `start_date` (form-data): Start date for forecasting (format: `YYYY-MM-DD`).
  - `duration` (form-data): Number of months to forecast.

- **Response:**
  - `201 Created` with JSON data containing forecast results.
  - `400 Bad Request` for invalid input.
  - `500 Internal Server Error` for server-side issues.

### 2. Calculate Error Metrics

- **URL:** `/api/predictions/error_metrics`
- **Method:** `POST`
- **Description:** Calculates error metrics (MAE, RMSE, MAPE) for the forecasts.
- **Parameters:**
  - `file` (form-data): CSV file containing sales data.
  - `start_date` (form-data): Start date for forecasting (format: `YYYY-MM-DD`).
  - `duration` (form-data): Number of months to forecast.

- **Response:**
  - `201 Created` with JSON data containing error metrics.
  - `400 Bad Request` for invalid input.
  - `500 Internal Server Error` for server-side issues.

## Project Structure

```plaintext
sales-forecasting-app/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── prediction_api.py
│   ├── controllers/   
│   │   ├── __init__.py
│   │   └── prediction_controller.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── file.py
│   │   └── prediction.py
│   ├── views/
│   │   ├── __init__.py
│   │   └── home.py
│   ├── extensions.py
│   ├── config.py
│   ├── routes.py
│   └── __init__.py
│   ├── migrations/
│   │   └── ... (migration files)
│   ├── build/
│   │   └── ... (frontend build files)
│   ├── requirements.txt
│   └── run.py
└── README.md
```

## Troubleshooting

- **Database Connection Issues:**
  - Ensure MySQL is running.
  - Verify the credentials in the `.env` file.
  - Check if the database `sales_forecasting_app` exists.

- **Module Not Found Errors:**
  - Ensure all dependencies are installed:
    ```bash
    pip install -r requirements.txt
    ```
  - Activate the virtual environment.

- **Port Already in Use:**
  - If port `5000` is occupied, specify a different port:
    ```bash
    python run.py --port=5001
    ```

## Contributing

Contributions are welcome! Please follow these steps:

1. **Fork the Repository**
2. **Create a Feature Branch**
   ```bash
   git checkout -b feature/YourFeature
   ```
3. **Commit Your Changes**
4. **Push to the Branch**
   ```bash
   git push origin feature/YourFeature
   ```
5. **Open a Pull Request**

Please ensure your code follows the project's coding standards and includes appropriate tests.

## License

This project is licensed under the [MIT License](LICENSE).
